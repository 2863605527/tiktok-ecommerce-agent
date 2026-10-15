"""SocialCrawl TikTok Shop API 真实数据源（商品搜索 + 商品详情 + 评论）。

为什么加 SocialCrawl：
- FastMoss 需注册充值才能验证；SocialCrawl 新账号送 100 credits（无信用卡、不过期），
  适合"先免费验证真实数据能跑通全流程"再切换到批量付费源
- 官方 TikTok Shop API（2026-10 抓取 socialcrawl.dev/platforms/tiktokshop）：
    GET /v1/tiktokshop/search           关键词搜索（query/region，多区域含 JP）
    GET /v1/tiktokshop/product          商品详情（url/product_id；US-only 上游）
    GET /v1/tiktokshop/product/reviews  商品评论（url/product_id/region，含 JP）
- 计费：每个端点 1 credit/次（live miss）；缓存命中 0 credits；空结果/失败自动退款
- 鉴权：header `x-api-key`
- 搜索/评论支持 16 区域：US, GB, DE, FR, IT, ID, MY, MX, PH, SG, ES, TH, VN, BR, JP, IE

设计要点（与 fastmoss.py 对齐）：
- 端点/字段 100% 按官方文档实现；success != true 抛 CrawlerError 并带官方 message
- 映射逻辑 _map_product/_map_review 为纯静态方法，可离线单测
- 评论分页：官方"Page 1 only"（Reviews 端点说明），默认取第 1 页 10 条
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

SOCIALCRAWL_API_BASE = "https://www.socialcrawl.dev"
SEARCH_ENDPOINT = "/v1/tiktokshop/search"
PRODUCT_ENDPOINT = "/v1/tiktokshop/product"
REVIEWS_ENDPOINT = "/v1/tiktokshop/product/reviews"

# 官方支持区域（search/reviews；product 详情 US-only 上游）
SUPPORTED_REGIONS = [
    "US", "GB", "DE", "FR", "IT", "ID", "MY", "MX", "PH",
    "SG", "ES", "TH", "VN", "BR", "JP", "IE",
]


class SocialCrawlProductCrawler(ProductCrawler):
    """SocialCrawl TikTok Shop 商品/评论采集器（免费额度验证/低量真实数据源）。

    Args:
        api_key: socialcrawl.dev 注册后生成的 x-api-key（新账号 100 credits 免费）
        region: 目标市场，默认 JP（日本站；官方支持列表见 SUPPORTED_REGIONS）
        api_base: 官方默认 https://www.socialcrawl.dev
    """

    def __init__(
        self,
        client: HttpClient,
        api_key: str,
        *,
        region: str = "JP",
        api_base: str = SOCIALCRAWL_API_BASE,
    ):
        if region not in SUPPORTED_REGIONS:
            raise CrawlerError(
                f"SocialCrawl 不支持区域: {region}",
                detail=f"支持: {', '.join(SUPPORTED_REGIONS)}",
            )
        self.client = client
        self.api_key = api_key
        self.region = region
        self.api_base = api_base.rstrip("/")

    # ---------- 鉴权与请求 ----------

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key}

    def _get(self, endpoint: str, params: dict) -> dict:
        payload = self.client.get_json(
            f"{self.api_base}{endpoint}",
            method="GET",
            params=params,
            headers=self._headers(),
        )
        # SocialCrawl 统一 envelope：{success, data, credits_used, credits_remaining,
        #                              request_id, cached, pagination?}
        if payload.get("success") is not True:
            raise CrawlerError(
                "SocialCrawl 接口返回失败",
                detail=str(payload.get("data") or payload.get("message") or ""),
            )
        return payload

    # ---------- 商品映射（纯函数，可单测） ----------

    @staticmethod
    def _map_product(item: dict, region: str = "JP") -> Product:
        """把 SocialCrawl 商品卡片（search/products 返回）映射为领域模型 Product。

        注意：SocialCrawl 搜索卡片不返回销量字段（JP 站小店无公开销量统计），
        sales 保持 0 表示"未披露"；把评分/评论数/卖家/品牌/库存映射为热度代理指标，
        供选品评估在销量缺失时仍能给出有依据的判断。
        """
        product = item.get("product") or item if isinstance(item, dict) else {}
        price = product.get("price") or {}
        current = price.get("current")
        currency = price.get("currency") or ""
        rating = product.get("rating")
        if isinstance(rating, dict):
            rating_avg = rating.get("average")
            rating_count = rating.get("count")
        else:
            # 兼容标量评分（部分文档样例直接给 4.7）
            rating_avg = rating if isinstance(rating, (int, float)) else None
            rating_count = None
        reviews_count = product.get("reviews_count")
        seller = product.get("seller") or {}
        availability = product.get("availability") or ""
        return Product(
            id=str(product.get("id") or ""),
            title=str(product.get("title") or ""),
            price=str(current) if current not in (None, "") else "",
            currency=str(currency) or _currency_for(region),
            url=str(product.get("url") or ""),
            description=str(product.get("description") or ""),
            sales=0,  # SocialCrawl 搜索卡无销量字段 → 0 表示未披露（勿改成猜测值）
            rating=float(rating_avg) if isinstance(rating_avg, (int, float)) else None,
            reviews_count=int(reviews_count) if isinstance(reviews_count, (int, float)) else
            (int(rating_count) if isinstance(rating_count, (int, float)) else None),
            seller=str(seller.get("name") or "") if isinstance(seller, dict) else "",
            brand=str(product.get("brand") or ""),
            availability=str(availability),
            category="",
            specs={},
            tags=[region],
            images=[u for u in (product.get("image_urls") or []) if isinstance(u, str) and u],
            reviews=[],
        )

    @staticmethod
    def _map_review(item: dict) -> Review:
        """把 SocialCrawl 评论记录映射为领域模型 Review。"""
        review = item.get("review") or item if isinstance(item, dict) else {}
        rating = review.get("rating") or {}
        ext = review.get("ext") or {}
        tt = ext.get("tiktokshop") or {}
        content = str(review.get("text") or "")
        created = None
        pub = review.get("published_at")
        if pub:
            try:
                created = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
            except ValueError:
                created = None
        author = review.get("author") or {}
        return Review(
            content=content,
            rating=float(rating.get("value") or 0),
            helpful_count=0,
            author=str(author.get("name") or "") or None,
            created_at=created,
            raw=content,
        )

    @staticmethod
    def review_is_incentivized(item: dict) -> bool:
        """是否激励性评论（官方字段 ext.tiktokshop.is_incentivized_review）。"""
        review = item.get("review") or item if isinstance(item, dict) else {}
        ext = review.get("ext") or {}
        tt = ext.get("tiktokshop") or {}
        return bool(tt.get("is_incentivized_review"))

    # ---------- 产品采集接口 ----------

    def search_products(self, keyword: str, limit: int = 5) -> list[Product]:
        """按关键词搜索 TikTok Shop 商品（官方 1 credit/次）。"""
        payload = self._get(SEARCH_ENDPOINT, {"query": keyword, "region": self.region})
        data = payload.get("data") or {}
        items = data.get("items") or []
        logger.info(
            "SocialCrawl 搜索 '%s' (%s) 返回 %d 条（credits_used=%s）",
            keyword, self.region, len(items), payload.get("credits_used"),
        )
        return [self._map_product(x, self.region) for x in items[:limit] if isinstance(x, dict)]

    def fetch_product(self, url: str) -> Product:
        """按商品链接/ID 采集详情（官方注明 US-only 上游）＋评论。"""
        product_id = self._extract_product_id(url)
        payload = self._get(
            PRODUCT_ENDPOINT,
            {"product_id": product_id, "region": "US"},  # product 详情仅 US 可用
        )
        data = payload.get("data") or {}
        items = data.get("items") or []
        if not items:
            raise CrawlerError(f"SocialCrawl 未找到商品: {url}", detail=f"product_id={product_id}")
        product = self._map_product(items[0], self.region)
        product.reviews = self.fetch_reviews(product_id)
        return product

    def fetch_reviews(self, product_id: str, max_comments: int = 10) -> list[Review]:
        """拉取指定商品评论（官方 Reviews 端点 Page 1，10 条/页；1 credit/页）。"""
        payload = self._get(
            REVIEWS_ENDPOINT,
            {"product_id": product_id, "region": self.region},
        )
        data = payload.get("data") or {}
        items = data.get("items") or []
        logger.info(
            "SocialCrawl 拉取评论 %s 共 %d 条（total=%s, credits=%s）",
            product_id, len(items), data.get("total"), payload.get("credits_used"),
        )
        return [self._map_review(x) for x in items[:max_comments] if isinstance(x, dict)]

    # ---------- 工具 ----------

    @staticmethod
    def _extract_product_id(url_or_id: str) -> str:
        """从商品链接/纯 ID 中提取 product_id（链接尾部为纯数字 ID）。"""
        s = url_or_id.strip()
        if not s:
            raise CrawlerError("SocialCrawl 商品链接为空")
        tail = s.rstrip("/").rsplit("/", 1)[-1]
        if tail.isdigit():
            return tail
        return s


def _currency_for(region: str) -> str:
    """区域 → ISO 货币代码（仅用于 SocialCrawl 未返回 currency 时的兜底）。"""
    return {
        "JP": "JPY", "US": "USD", "GB": "GBP", "MX": "MXN", "BR": "BRL",
        "ES": "EUR", "DE": "EUR", "FR": "EUR", "IT": "EUR", "IE": "EUR",
        "ID": "IDR", "MY": "MYR", "PH": "PHP", "SG": "SGD", "TH": "THB", "VN": "VND",
    }.get(region, "")
