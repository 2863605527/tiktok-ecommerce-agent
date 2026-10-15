"""FastMoss OpenAPI 客户端单元测试（纯离线，用 FakeHttpClient 模拟官方响应）。"""
import pytest

from tiktok_ecommerce.common.exceptions import CrawlerError
from tiktok_ecommerce.crawlers.fastmoss import (
    FastMossProductCrawler,
    REVIEW_ENDPOINT,
    SEARCH_ENDPOINT,
)
from tiktok_ecommerce.crawlers.http import HttpClient


class FakeHttpClient(HttpClient):
    """记录请求并返回预设响应的 HTTP 客户端替身。"""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[tuple[str, str, dict]] = []
        super().__init__(min_interval=0)

    def get_json(self, url, *, params=None, headers=None, json_body=None, method="GET"):
        self.calls.append((url, method, json_body))
        for key, payload in self.responses.items():
            if url.endswith(key):
                return payload
        return {"code": 0, "data": {"list": [], "total": 0}}


# 官方文档示例响应（developers.fastmoss.com/api/docs/product/v1/search.html）
_SEARCH_RESPONSE = {
    "code": 0,
    "data": {
        "list": [
            {
                "product_id": "1729514474840169156",
                "title": "HALMAI-taladro de uñas Ultra Power",
                "region": "ES",
                "creator_count": 101,
                "category": {"l1": {"id": 14, "name": "Beauty & Personal Care"},
                             "l2": {"id": 849416, "name": "Appliances"}},
                "total_units_sold": 4921,
                "total_gmv": 134661,
                "commission_rate": "12.5%",
                "product_rating": 4.9,
                "is_free_shipping": 1,
                "off_shelves": 0,
                "price": "29,99 €",
                "floor_price": 29.99,
                "sku_count": 4,
                "fastmoss_url": "https://www.fastmoss.com/zh/e-commerce/detail/1729514474840169156",
                "shop": {"seller_id": 123, "name": "test", "total_units_sold": 123},
            }
        ],
        "total": 1,
    },
    "message": "",
}

# 官方文档示例响应（product/v1/reviewList.html）
_REVIEW_RESPONSE = {
    "code": 0,
    "data": {
        "list": [
            {
                "review_id": "7354810045655336747",
                "uid": "7354810045655336700",
                "sku_id": "1729448464509800494",
                "sku_specification": "Item: Default",
                "rating": 5,
                "digg_count": 12,
                "content": "肌触りがとてもなめらかで、寝返りしても気持ちいい。",
                "create_time": 1712425181310,
            }
        ],
        "total": "3809",
    },
    "message": "success",
}


def _crawler(responses: dict | None = None) -> tuple[FastMossProductCrawler, FakeHttpClient]:
    client = FakeHttpClient(responses or {})
    return FastMossProductCrawler(client, api_key="sk-test", region="JP"), client


class TestFastMossSearch:
    def test_search_request_body_and_mapping(self):
        crawler, client = _crawler({SEARCH_ENDPOINT: _SEARCH_RESPONSE})
        products = crawler.search_products("ボックスシーツ", limit=5)

        url, method, body = client.calls[0]
        assert method == "POST"
        assert url.endswith(SEARCH_ENDPOINT)
        assert body["keywords"] == "ボックスシーツ"
        assert body["filter"] == {"region": "JP"}
        assert body["orderby"] == [{"field": "day7_units_sold", "order": "desc"}]
        assert body["pagesize"] == 5

        assert len(products) == 1
        p = products[0]
        assert p.id == "1729514474840169156"
        assert p.title == "HALMAI-taladro de uñas Ultra Power"
        assert p.price == "29,99 €"
        assert p.currency == "JPY"  # region=JP → JPY
        assert p.sales == 4921
        assert p.category == "Beauty & Personal Care"
        assert p.url.startswith("https://www.fastmoss.com")
        assert p.specs["rating"] == "4.9"

    def test_pagesize_capped_at_100(self):
        crawler, client = _crawler({SEARCH_ENDPOINT: {"code": 0, "data": {"list": []}}})
        crawler.search_products("床笠", limit=500)
        assert client.calls[0][2]["pagesize"] == 100

    def test_unsupported_region_raises(self):
        client = FakeHttpClient({})
        with pytest.raises(CrawlerError):
            FastMossProductCrawler(client, api_key="x", region="XX")


class TestFastMossReviews:
    def test_fetch_reviews_mapping(self):
        crawler, client = _crawler({REVIEW_ENDPOINT: _REVIEW_RESPONSE})
        reviews = crawler.fetch_reviews("1729448464509734958", max_comments=10)

        url, method, body = client.calls[0]
        assert method == "POST"
        assert url.endswith(REVIEW_ENDPOINT)
        assert body["filter"] == {"product_id": "1729448464509734958"}
        assert body["orderby"] == {"field": "rating", "order": "desc"}

        assert len(reviews) == 1
        r = reviews[0]
        assert r.rating == 5.0
        assert r.helpful_count == 12
        assert r.content == "肌触りがとてもなめらかで、寝返りしても気持ちいい。"
        assert "7354****6700" == r.author  # UID 脱敏（保留首尾4位）
        assert "****" in r.author
        assert r.created_at is not None

    def test_fetch_product_fetches_reviews(self):
        crawler, client = _crawler({
            SEARCH_ENDPOINT: _SEARCH_RESPONSE,
            REVIEW_ENDPOINT: _REVIEW_RESPONSE,
        })
        product = crawler.fetch_product("1729514474840169156")
        assert product.id == "1729514474840169156"
        assert len(product.reviews) == 1  # 详情接口自动附带评论

    def test_fetch_product_not_found(self):
        crawler, client = _crawler({SEARCH_ENDPOINT: {"code": 0, "data": {"list": [], "total": 0}}})
        with pytest.raises(CrawlerError):
            crawler.fetch_product("9999999999")


class TestFastMossErrors:
    def test_business_error_raises(self):
        crawler, _ = _crawler({
            SEARCH_ENDPOINT: {"code": 40001, "message": "insufficient balance", "data": None},
        })
        with pytest.raises(CrawlerError, match="40001"):
            crawler.search_products("床笠")

    def test_extract_product_id(self):
        c = FastMossProductCrawler._extract_product_id
        assert c("https://www.fastmoss.com/zh/e-commerce/detail/1729514474840169156") \
            == "1729514474840169156"
        assert c("https://www.tiktok.com/@shop/video/7354810045655336747") \
            == "7354810045655336747"
        assert c("1729514474840169156") == "1729514474840169156"
