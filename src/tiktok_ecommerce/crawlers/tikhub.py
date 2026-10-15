"""TikHub TikTok Shop 网页 API 真实数据源（商品搜索 + 商品评论）。

为什么加 TikHub（日常批量付费源，2026-10 官方文档核实）：
- tikhub.io 注册即送 $0.05 体验额度（约 50 次请求），按量付费低至 $0.001/次，
  量大 30k+/天可低至 $0.0005/次 —— 比 FastMoss($0.01/次) 便宜约 10~20 倍
- 无需官方开发者账号/应用审核/OAuth；Bearer Token 鉴权；默认 10 RPS

已核实的端点（Apifox 文档，docs-site 4705614）：
    GET /api/v1/tiktok/shop/web/fetch_search_products_list_v2  商品搜索（移动端精简版）
        参数：search_word(必填)/offset/page_token/region
        官方区域：US/GB/SG/MY/PH/TH/VN/ID（未含 JP；日本站搜索建议用 SocialCrawl/FastMoss）
    GET /api/v1/tiktok/shop/web/fetch_product_reviews_v2       商品评论 V2
        参数：product_id(必填)/page_start/sort_rule/filter_type/filter_value/region
        官方区域：US/SG/MY/PH/TH/VN/ID/JP/MX（含 JP，日本站评论可用）

响应（通用 envelope）：
    外层 code==200 表示计费成功；业务数据在 data.data：
      搜索  data.data.products[]   {product_id,title,image,product_price_info,rate_info,
                                     sold_info,seller_info,seo_url,product_marketing_info}
      评论  data.data.product_reviews[] {review_id,review_rating,review_text,review_time,
                                         reviewer_name,review_images,is_verified_purchase}
    data.data.has_more=true 时 page_start+1 继续翻页

设计要点：
- code != 200 抛 CrawlerError 并带官方 message/message_zh
- 官方建议 timeout 30s、400 错误重试 3 次（由统一 HttpClient 的 retry 策略承载）
- 评论映射字段完全按文档；搜索的子结构（price_info 等）官方未展开，
  做宽容解析并注明"启发式兼容"
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from tiktok_ecommerce.common.exceptions import CrawlerError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.crawlers.base import ProductCrawler
from tiktok_ecommerce.crawlers.http import HttpClient
from tiktok_ecommerce.models.product import Product, Review

logger = get_logger(__name__)

TIKHUB_API_BASE = "https://api.tikhub.io"
SEARCH_ENDPOINT = "/api/v1/tiktok/shop/web/fetch_search_products_list_v2"
REVIEWS_ENDPOINT = "/api/v1/tiktok/shop/web/fetch_product_reviews_v2"

# 官方区域支持（见上注释：搜索未含 JP，评论含 JP）
SEARCH_SUPPORTED_REGIONS = ["US", "GB", "SG", "MY", "PH", "TH", "VN", "ID"]
REVIEWS_SUPPORTED_REGIONS = ["US", "SG", "MY", "PH", "TH", "VN", "ID", "JP", "MX"]


def _pick(d: dict, keys: tuple[str, ...], default="") -> str:
    """按候选键顺序取子结构字段（官方未展开结构时的启发式兼容）。"""
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return str(v)
    return default


class TikHubProductCrawler(ProductCrawler):
    """TikHub TikTok Shop 商品/评论采集器（日常批量付费源）。

    Args:
        api_key: user.tikhub.io/dashboard/api 生成的 API 密钥
        region: 目标市场，默认 JP。注意官方搜索区域未含 JP，本实现不做硬校验，
                若 API 对 JP 搜索报错，请改用 SocialCrawl/FastMoss 做搜索、TikHub 做评论。
        api_base: 官方默认 https://api.tikhub.io
    """

    def __init__(
        self,
        client: HttpClient,
        api_key: str,
        *,
        region: str = "JP",
        api_base: str = TIKHUB_API_BASE,
    ):
        self.client = client
        self.api_key = api_key
        self.region = region
        self.api_base = api_base.rstrip("/")

    # ---------- 鉴权与请求 ----------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _get(self, endpoint: str, params: dict) -> dict:
        # 官方提示：接口风控原因 timeout 需 30s；400 错误需重试 3 次
        payload = self.client.get_json(
            f"{self.api_base}{endpoint}",
            method="GET",
            params=params,
            headers=self._headers(),
        )
        # TikHub 统一 envelope：外层 code 200 = 计费成功
        if payload.get("code") != 200:
            raise CrawlerError(
                f"TikHub 接口返回错误 code={payload.get('code')}",
                detail=str(payload.get("message_zh") or payload.get("message") or ""),
            )
        data = payload.get("data") or {}
        # 业务数据在 data.data（评论 V2 结构）或 data（搜索 V1/V2 文档示意结构）
        inner = data.get("data") if isinstance(data, dict) and isinstance(data.get("data"), dict) else {}
        if isinstance(inner, dict) and (inner.get("products") is not None or inner.get("product_reviews") is not None):
            return inner
        return data if isinstance(data, dict) else {}

    # ---------- 商品映射（纯函数，可单测） ----------

    @staticmethod
    def _map_product(item: dict, region: str = "JP") -> Product:
        """把 TikHub 搜索商品映射为领域模型 Product。

        官方文档只展开 product_id/title/image/seo_url；价格/评分/销量在
        product_price_info/rate_info/sold_info 子结构中，字段名未公开，
        采用启发式候选键兼容（找不到则为空，不伪造）。
        """
        price_info = item.get("product_price_info")
        rate_info = item.get("rate_info")
        sold_info = item.get("sold_info")
        price_info = price_info if isinstance(price_info, dict) else {}
        rate_info = rate_info if isinstance(rate_info, dict) else {}
        sold_info = sold_info if isinstance(sold_info, dict) else {}

        price = _pick(price_info, ("price", "sale_price", "current_price", "value", "min_price", "max_price"))
        currency = _pick(price_info, ("currency", "currency_code", "symbol"), "")
        rating = _pick(rate_info, ("average_rating", "rating", "score", "avg_rating"), "0")
        sold = _pick(sold_info, ("sold", "sales", "volume", "sold_count"), "0")

        specs: dict[str, str] = {}
        if rating != "0":
            specs["rating"] = rating
        if sold != "0":
            specs["sold"] = sold

        try:
            sold_int = int(float(sold))
        except ValueError:
            sold_int = 0

        return Product(
            id=str(item.get("product_id") or ""),
            title=str(item.get("title") or ""),
            price=price,
            currency=currency or _currency_for(region),
            url=str(item.get("seo_url") or ""),
            description="",
            sales=sold_int,
            category="",
            specs=specs,
            tags=[region],
            reviews=[],
        )

    @staticmethod
    def _map_review(item: dict) -> Review:
        """把 TikHub 评论记录映射为领域模型 Review（字段完全按官方文档）。"""
        content = str(item.get("review_text") or "")
        created = None
        t = item.get("review_time")
        if t:
            try:
                created = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
            except ValueError:
                created = None
        return Review(
            content=content,
            rating=float(item.get("review_rating") or 0),
            helpful_count=0,
            author=str(item.get("reviewer_name") or "") or None,
            created_at=created,
            raw=content,
        )

    # ---------- 产品采集接口 ----------

    def search_products(self, keyword: str, limit: int = 5) -> list[Product]:
        """按关键词搜索 TikTok Shop 商品（官方每页 30 条，1 次请求 $0.001）。"""
        data = self._get(SEARCH_ENDPOINT, {
            "search_word": keyword,
            "offset": 0,
            "page_token": "",
            "region": self.region,
        })
        products = data.get("products") or []
        logger.info(
            "TikHub 搜索 '%s' (%s) 返回 %d 条（has_more=%s）",
            keyword, self.region, len(products), data.get("has_more"),
        )
        return [self._map_product(x, self.region) for x in products[:limit] if isinstance(x, dict)]

    def fetch_product(self, url: str) -> Product:
        """按商品链接/ID 采集（评论 + 基本信息兜底；TikHub 搜索可回捞商品）。"""
        product_id = self._extract_product_id(url)
        # 用搜索接口按 ID 回捞（TikHub 无公开的商品详情简化端点保证，以评论为主）
        data = self._get(SEARCH_ENDPOINT, {
            "search_word": product_id,
            "offset": 0,
            "page_token": "",
            "region": self.region,
        })
        products = data.get("products") or []
        if not products:
            raise CrawlerError(f"TikHub 未找到商品: {url}", detail=f"product_id={product_id}")
        product = self._map_product(products[0], self.region)
        product.reviews = self.fetch_reviews(product_id)
        return product

    def fetch_reviews(self, product_id: str, max_comments: int = 50) -> list[Review]:
        """拉取指定商品评论（评论 V2；官方区域含 JP；page_start 分页）。"""
        reviews: list[Review] = []
        page = 1
        while len(reviews) < max_comments and page <= 5:  # 最多翻 5 页防失控
            data = self._get(REVIEWS_ENDPOINT, {
                "product_id": product_id,
                "page_start": page,
                "sort_rule": 2,          # 2=最近
                "filter_type": 1,        # 1=全部
                "filter_value": 6,       # 6=全部星级
                "region": self.region,
            })
            items = data.get("product_reviews") or []
            for x in items:
                if isinstance(x, dict):
                    reviews.append(self._map_review(x))
            if not data.get("has_more") or not items:
                break
            page += 1
        logger.info("TikHub 拉取评论 %s 共 %d 条（含翻页）", product_id, len(reviews))
        return reviews[:max_comments]

    # ---------- 工具 ----------

    @staticmethod
    def _extract_product_id(url_or_id: str) -> str:
        """从商品链接/纯 ID 中提取 product_id。"""
        s = url_or_id.strip()
        if not s:
            raise CrawlerError("TikHub 商品链接为空")
        tail = s.rstrip("/").rsplit("/", 1)[-1]
        if tail.isdigit():
            return tail
        return s


def _currency_for(region: str) -> str:
    """区域 → ISO 货币代码兜底。"""
    return {
        "JP": "JPY", "US": "USD", "GB": "GBP", "MX": "MXN",
        "ID": "IDR", "MY": "MYR", "PH": "PHP", "SG": "SGD", "TH": "THB", "VN": "VND",
    }.get(region, "")
