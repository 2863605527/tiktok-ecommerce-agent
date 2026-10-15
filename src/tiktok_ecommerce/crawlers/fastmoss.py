"""FastMoss OpenAPI 真实数据源（TikTok 商品 + 评论）。

为什么选 FastMoss 作为 TikTok 侧生产数据源：
- 官方开放平台 TTS API 只面向开发者应用（Partner Center 申请+审核+卖家 OAuth 授权），
  个人卖家短期拿不到商品/评论全量数据；TikTok 页面直连受 JS 渲染、X-Bogus/
  msToken/_signature 签名、设备指纹与滑块风控三重阻断（详见 docs/DATA_SOURCES.md）
- FastMoss 是 TikTok Shop 数据引擎：500M+ 商品、300M+ 达人、1200+ 天历史，
  45+ REST 端点，按调用计费（$0.01/call 起、pagesize>10 按 ceil(pagesize/10) 扣额度、
  空结果不计费），region 支持 JP —— 对本项目（TikTok 日本站）最对口

已按官方文档核实的端点（2026-10 抓取 developers.fastmoss.com/api/docs/）：
  POST /product/v1/search      商品搜索（keywords/filter/orderby/page/pagesize）
  POST /product/v1/reviewList  商品评论列表（filter.product_id 必填）
  POST /product/v1/rank/topSelling  热销榜（filter.region/category_id/date_info）

计费与配额（官方文档原话）：
  "The standard unit price per call covers a pagesize of up to 10.
   For pagesize > 10, the consumption quota increases proportionally:
   Quota = ceil(pagesize / 10). No quota is deducted if zero results are returned."

设计要点：
- 端点/字段 100% 按官方文档实现，不猜测
- 只有 code==0 才算成功，业务错误（额度不足/密钥无效）抛 CrawlerError 并带官方 message
- 映射逻辑（_map_product/_map_review）为纯静态方法，可离线单测
- 请求体里 pagesize 上限 100，遵守官方约束 page*pagesize <= 5000
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

# 官方 API 基地址与端点（来自 developers.fastmoss.com/api/docs/）
FASTMOSS_API_BASE = "https://openapi.fastmoss.com"
SEARCH_ENDPOINT = "/product/v1/search"
REVIEW_ENDPOINT = "/product/v1/reviewList"
RANK_ENDPOINT = "/product/v1/rank/topSelling"

# region 代码 → 货币（FastMoss 返回的 price 是带货币符号的展示字符串，货币码按区域映射）
_REGION_CURRENCY = {
    "JP": "JPY", "US": "USD", "GB": "GBP", "MX": "MXN", "ES": "EUR",
    "DE": "EUR", "IT": "EUR", "FR": "EUR", "PT": "EUR", "NL": "EUR",
    "BE": "EUR", "AT": "EUR", "PL": "PLN", "ID": "IDR", "VN": "VND",
    "MY": "MYR", "TH": "THB", "PH": "PHP", "BR": "BRL", "SG": "SGD",
}
# 官方支持的区域列表（product/v1/search 文档 filter.region）
SUPPORTED_REGIONS = list(_REGION_CURRENCY.keys())


def _mask_uid(uid: str) -> str:
    """对评论者 UID 脱敏（保留首尾 4 位，中间打码），避免泄露平台用户隐私。"""
    if len(uid) <= 8:
        return uid[:2] + "****"
    return uid[:4] + "****" + uid[-4:]


class FastMossProductCrawler(ProductCrawler):
    """FastMoss OpenAPI 商品/评论采集器（生产环境首选数据源）。

    Args:
        api_key: Console 创建的 client_secret（申请方式见 docs/HOW_TO_GET_DATA.md）
        region: TikTok Shop 区域，默认 JP（日本站）
        api_base: 官方默认 https://openapi.fastmoss.com
    """

    def __init__(
        self,
        client: HttpClient,
        api_key: str,
        *,
        region: str = "JP",
        api_base: str = FASTMOSS_API_BASE,
    ):
        if region not in SUPPORTED_REGIONS:
            raise CrawlerError(
                f"FastMoss 不支持区域: {region}",
                detail=f"支持: {', '.join(SUPPORTED_REGIONS)}",
            )
        self.client = client
        self.api_key = api_key
        self.region = region
        self.api_base = api_base.rstrip("/")

    # ---------- 鉴权与请求 ----------

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, endpoint: str, body: dict) -> dict:
        payload = self.client.get_json(
            f"{self.api_base}{endpoint}",
            method="POST",
            json_body=body,
            headers=self._headers(),
        )
        # FastMoss 统一响应：{code, data, message, timestamp, request_id}
        code = payload.get("code")
        if code != 0:
            raise CrawlerError(
                f"FastMoss 接口返回错误 code={code}",
                detail=payload.get("message") or "",
            )
        data = payload.get("data") or {}
        return data if isinstance(data, dict) else {"list": data}

    # ---------- 商品映射（纯函数，可单测） ----------

    @staticmethod
    def _map_product(item: dict, region: str = "JP") -> Product:
        """把 FastMoss 商品记录映射为领域模型 Product。"""
        shop = item.get("shop") or {}
        category = item.get("category") or {}
        l1 = category.get("l1") or {}
        specs: dict[str, str] = {}
        for key, val in (
            ("rating", item.get("product_rating")),
            ("is_free_shipping", item.get("is_free_shipping")),
            ("sku_count", item.get("sku_count")),
        ):
            if val not in (None, ""):
                specs[str(key)] = str(val)
        return Product(
            id=str(item.get("product_id") or ""),
            title=str(item.get("title") or ""),
            price=str(item.get("price") or ""),
            currency=_REGION_CURRENCY.get(region, "JPY"),
            url=str(item.get("fastmoss_url") or item.get("tiktok_url") or ""),
            description=str(item.get("title") or ""),
            sales=int(item.get("total_units_sold") or 0),
            category=str(l1.get("name") or ""),
            specs=specs,
            tags=[str(item.get("region") or "")],
            reviews=[],
        )

    @staticmethod
    def _map_review(item: dict) -> Review:
        """把 FastMoss 评论记录映射为领域模型 Review。"""
        content = str(item.get("content") or "")
        ts = item.get("create_time")
        created = None
        if isinstance(ts, (int, float)) and ts:
            try:
                created = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            except (OverflowError, OSError, ValueError):
                created = None
        return Review(
            content=content,
            rating=float(item.get("rating") or 0),
            helpful_count=int(item.get("digg_count") or 0),
            author=_mask_uid(str(item.get("uid") or "")) or None,
            created_at=created,
            raw=content,
        )

    # ---------- 产品采集接口 ----------

    def search_products(self, keyword: str, limit: int = 5) -> list[Product]:
        """按关键词搜索 TikTok 日本站商品（按 7 天销量降序）。"""
        pagesize = max(1, min(limit, 100))  # 官方 pagesize 范围 [1,100]
        body = {
            "keywords": keyword,
            "filter": {"region": self.region},
            "orderby": [{"field": "day7_units_sold", "order": "desc"}],
            "page": 1,
            "pagesize": pagesize,
        }
        data = self._post(SEARCH_ENDPOINT, body)
        records = data.get("list") or []
        logger.info(
            "FastMoss 搜索 '%s' (%s) 返回 %d 条（total=%s）",
            keyword, self.region, len(records), data.get("total"),
        )
        return [self._map_product(x, self.region) for x in records[:limit] if isinstance(x, dict)]

    def fetch_product(self, url: str) -> Product:
        """按商品链接/ID 采集商品详情 + 评论。

        url 支持：FastMoss 详情链接（.../detail/<product_id>）、
        TikTok 商品链接（尾部带商品 ID）、或直接传 product_id。
        内部先按 product_id 查商品，再拉评论（一次接口各一调用）。
        """
        product_id = self._extract_product_id(url)
        body = {
            "filter": {"region": self.region, "product_id": [product_id]},
            "page": 1,
            "pagesize": 10,
        }
        data = self._post(SEARCH_ENDPOINT, body)
        records = data.get("list") or []
        if not records:
            raise CrawlerError(f"FastMoss 未找到商品: {url}", detail=f"product_id={product_id}")
        product = self._map_product(records[0], self.region)
        product.reviews = self.fetch_reviews(product_id)
        return product

    def fetch_reviews(self, product_id: str, max_comments: int = 200) -> list[Review]:
        """拉取指定商品的评论（按评分降序，默认最多 200 条）。"""
        pagesize = max(1, min(max_comments, 100))  # 官方 pagesize 范围 [1,100]
        body = {
            "filter": {"product_id": product_id},
            "orderby": {"field": "rating", "order": "desc"},
            "page": 1,
            "pagesize": pagesize,
        }
        data = self._post(REVIEW_ENDPOINT, body)
        records = data.get("list") or []
        logger.info("FastMoss 拉取评论 %s 共 %d 条", product_id, len(records))
        return [self._map_review(x) for x in records[:max_comments] if isinstance(x, dict)]

    # ---------- 工具 ----------

    @staticmethod
    def _extract_product_id(url_or_id: str) -> str:
        """从任意格式（详情链接/商品链接/纯 ID）中提取 product_id。"""
        s = url_or_id.strip()
        if not s:
            raise CrawlerError("FastMoss 商品链接为空")
        # 取最后一段数字串（fastmoss_url 与 tiktok_url 的尾部都是纯数字 ID）
        tail = s.rstrip("/").rsplit("/", 1)[-1]
        if tail.isdigit():
            return tail
        # 纯数字 ID 直接返回；否则可能是 tiktok 的短链/别名，交给接口按原值查询
        return s
