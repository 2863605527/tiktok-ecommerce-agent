"""第三方数据平台 API 数据源（生产环境推荐方案）。

适用平台（均为 TikTok Shop 数据 SaaS，跨境电商常用）：
- FastMoss / Kalodata / EchoTik / TikStar 等：提供商品、销量、评论、达人 HTTP API
- 国内货源：1688 开放平台 / 阿里巴巴采购 API（需企业资质与 AppKey）

设计要点：
- 只依赖统一 HttpClient（Bearer 鉴权 + JSON），不耦合任何一家平台的 SDK
- 用"多候选字段名"做稳健映射，换平台只需调整字段候选或传 field_map
- 注意：各平台响应包裹与字段名不同，接入时按其文档微调 _find_records / _pick 候选
"""
from __future__ import annotations

from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.crawlers.base import ProductCrawler, SupplierCrawler
from tiktok_ecommerce.crawlers.http import HttpClient
from tiktok_ecommerce.models.product import Product, Review
from tiktok_ecommerce.models.supplier import SupplierOffer

logger = get_logger(__name__)


def _pick(d: dict, *keys: str, default=None):
    """按候选字段名顺序取第一个非空值（兼容不同平台字段命名）。"""
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return default


def _find_records(payload: dict) -> list[dict]:
    """从常见响应包裹中提取记录数组。

    兼容：{data: {list/records/items: [...]}}、{data: [...]}、{list/items: [...]}、[...]
    """
    if isinstance(payload, list):
        return payload
    data = payload.get("data", payload)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "records", "items", "products", "result", "rows"):
            v = data.get(key)
            if isinstance(v, list):
                return v
    for key in ("list", "records", "items", "results"):
        v = payload.get(key)
        if isinstance(v, list):
            return v
    return []


def _map_product(item: dict) -> Product:
    raw_reviews = _pick(item, "reviews", "comments", "feedback", default=[]) or []
    reviews = []
    for r in raw_reviews if isinstance(raw_reviews, list) else []:
        if not isinstance(r, dict):
            continue
        content = _pick(r, "content", "text", "comment", "content_text")
        if content:
            reviews.append(Review(
                content=str(content),
                rating=float(_pick(r, "rating", "star", "score", default=0) or 0),
                helpful_count=int(_pick(r, "helpful_count", "likes", default=0) or 0),
                author=_pick(r, "author", "user_name", "nickname"),
            ))
    return Product(
        id=str(_pick(item, "product_id", "id", "goods_id", default="")),
        title=str(_pick(item, "product_title", "title", "name", default="")),
        price=str(_pick(item, "price", "price_text", "sale_price", "min_price", default="")),
        currency=str(_pick(item, "currency", default="JPY")),
        url=str(_pick(item, "product_url", "url", "link", default="")),
        description=str(_pick(item, "description", "desc", default="")),
        sales=int(_pick(item, "sales", "sold", "sales_count", "volume", default=0) or 0),
        category=str(_pick(item, "category", "category_name", default="")),
        specs=_pick(item, "specs", "attributes", "skus", default={}) or {},
        tags=_pick(item, "tags", "keywords", default=[]) or [],
        reviews=reviews,
    )


def _map_offer(item: dict) -> SupplierOffer:
    return SupplierOffer(
        title=str(_pick(item, "title", "name", "subject", default="")),
        price=str(_pick(item, "price", "price_info", "wholesale_price", default="")),
        min_order=str(_pick(item, "min_order", "moq", "start_order", default="")),
        delivery=str(_pick(item, "delivery", "ship_time", "delivery_time", default="")),
        supplier_name=str(_pick(item, "company", "shop_name", "supplier", default="")),
        url=str(_pick(item, "url", "detail_url", "link", default="")),
    )


class ThirdPartyProductCrawler(ProductCrawler):
    """第三方 TikTok Shop 数据平台商品/评论采集。"""

    def __init__(
        self,
        client: HttpClient,
        api_base: str,
        api_key: str,
        search_endpoint: str = "/api/v1/product/search",
        detail_endpoint: str = "/api/v1/product/detail",
    ):
        self.client = client
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.search_endpoint = search_endpoint
        self.detail_endpoint = detail_endpoint

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def search_products(self, keyword: str, limit: int = 5) -> list[Product]:
        payload = self.client.get_json(
            f"{self.api_base}{self.search_endpoint}",
            params={"keyword": keyword, "page": 1, "size": limit},
            headers=self._auth_headers(),
        )
        records = _find_records(payload)
        logger.info("第三方平台搜索 '%s' 返回 %d 条", keyword, len(records))
        return [_map_product(x) for x in records[:limit] if isinstance(x, dict)]

    def fetch_product(self, url: str) -> Product:
        payload = self.client.get_json(
            f"{self.api_base}{self.detail_endpoint}",
            params={"product_id": url},
            headers=self._auth_headers(),
        )
        records = _find_records(payload)
        if not records:
            raise ValueError(f"第三方平台未返回商品: {url}")
        return _map_product(records[0])


class ThirdPartySupplierCrawler(SupplierCrawler):
    """第三方/开放平台国内货源采集（1688 开放平台等）。"""

    def __init__(
        self,
        client: HttpClient,
        api_base: str,
        api_key: str,
        search_endpoint: str = "/api/v1/supplier/search",
    ):
        self.client = client
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.search_endpoint = search_endpoint

    def search_offers(self, keywords: list[str], top_n: int = 10) -> list[SupplierOffer]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        seen: set[str] = set()
        offers: list[SupplierOffer] = []
        for kw in keywords[:3]:  # 控制请求量
            payload = self.client.get_json(
                f"{self.api_base}{self.search_endpoint}",
                params={"keyword": kw, "page": 1, "size": top_n},
                headers=headers,
            )
            for item in _find_records(payload):
                if not isinstance(item, dict):
                    continue
                offer = _map_offer(item)
                key = offer.url or offer.title
                if offer.title and key not in seen:
                    seen.add(key)
                    offers.append(offer)
        logger.info("第三方货源聚合 %d 条（去重后）", len(offers))
        return offers[:top_n]
