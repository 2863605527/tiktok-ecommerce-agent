"""TikHub TikTok Shop 客户端单元测试（纯离线，FakeHttpClient 模拟官方响应）。"""
import copy

import pytest

from tiktok_ecommerce.common.exceptions import CrawlerError
from tiktok_ecommerce.crawlers.http import HttpClient
from tiktok_ecommerce.crawlers.tikhub import (
    REVIEWS_ENDPOINT,
    SEARCH_ENDPOINT,
    TikHubProductCrawler,
)


class FakeHttpClient(HttpClient):
    """记录请求并返回预设响应的 HTTP 客户端替身。"""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[tuple[str, str, dict]] = []
        super().__init__(min_interval=0)

    def get_json(self, url, *, params=None, headers=None, json_body=None, method="GET"):
        self.calls.append((url, method, params))
        for key, payload in self.responses.items():
            if url.endswith(key):
                return payload
        return {"code": 200, "data": {"data": {"products": []}}}


# 官方文档示例响应（评论 V2：data.data.product_reviews）
_REVIEWS_RESPONSE = {
    "code": 200,
    "request_id": "req_1",
    "message": "Request successful. This request will incur a charge.",
    "data": {
        "code": 0,
        "message": "success",
        "data": {
            "has_more": False,
            "total_reviews": "100",
            "product_reviews": [
                {
                    "review_id": "1234567890",
                    "product_id": "1731128793906516409",
                    "review_rating": 5,
                    "review_time": "2026-10-01",
                    "review_text": "Example review",
                    "reviewer_name": "Example reviewer",
                    "review_images": [],
                    "is_verified_purchase": True,
                }
            ],
            "review_ratings": {"review_count": "100", "overall_score": 4.8},
        },
    },
}

# 官方文档示例响应（搜索 V2：data.data.products）
_SEARCH_RESPONSE = {
    "code": 200,
    "data": {
        "code": 0,
        "message": "success",
        "data": {
            "products": [
                {
                    "product_id": "1729408816995078528",
                    "title": "ボックスシーツ 綿100%",
                    "image": "https://example.com/img.jpg",
                    "product_price_info": {"price": "19.99", "currency": "USD"},
                    "rate_info": {"average_rating": "4.8"},
                    "sold_info": {"sold": "1200"},
                    "seller_info": {"seller_name": "test shop"},
                    "seo_url": "https://www.tiktok.com/shop/pdp/example/1729408816995078528",
                }
            ],
            "has_more": False,
        },
    },
}


def _crawler(responses: dict) -> TikHubProductCrawler:
    return TikHubProductCrawler(FakeHttpClient(responses), api_key="tk_test_key", region="JP")


def test_search_maps_product():
    c = _crawler({SEARCH_ENDPOINT: _SEARCH_RESPONSE})
    products = c.search_products("ボックスシーツ")
    assert len(products) == 1
    p = products[0]
    assert p.id == "1729408816995078528"
    assert p.title == "ボックスシーツ 綿100%"
    assert p.price == "19.99"
    assert p.currency == "USD"
    assert p.sales == 1200
    assert p.specs.get("rating") == "4.8"


def test_search_sends_params():
    c = _crawler({SEARCH_ENDPOINT: _SEARCH_RESPONSE})
    c.search_products("シーツ")
    _, _, params = c.client.calls[0]
    assert params["search_word"] == "シーツ"
    assert params["region"] == "JP"
    assert params["offset"] == 0


def test_reviews_maps_review():
    c = _crawler({REVIEWS_ENDPOINT: _REVIEWS_RESPONSE})
    reviews = c.fetch_reviews("1731128793906516409")
    assert len(reviews) == 1
    r = reviews[0]
    assert r.content == "Example review"
    assert r.rating == 5.0
    assert r.author == "Example reviewer"
    assert r.created_at is not None


def test_reviews_pagination():
    """has_more=true 时应继续翻页（page_start 递增）。"""
    page1 = copy.deepcopy(_REVIEWS_RESPONSE)
    page1["data"]["data"]["has_more"] = True
    page2 = copy.deepcopy(_REVIEWS_RESPONSE)
    page2["data"]["data"]["product_reviews"] = [
        {
            "review_id": "9",
            "product_id": "1731128793906516409",
            "review_rating": 4,
            "review_time": "2026-10-02",
            "review_text": "Second review",
            "reviewer_name": "user2",
            "review_images": [],
            "is_verified_purchase": False,
        }
    ]

    class PagedClient(FakeHttpClient):
        def get_json(self, url, *, params=None, headers=None, json_body=None, method="GET"):
            self.calls.append((url, method, params))
            page = (params or {}).get("page_start", 1)
            return page1 if page == 1 else page2

    c = TikHubProductCrawler(PagedClient({}), api_key="k", region="JP")
    reviews = c.fetch_reviews("1731128793906516409", max_comments=10)
    assert len(reviews) == 2
    assert c.client.calls[-1][2]["page_start"] == 2


def test_failure_raises_crawler_error():
    resp = {"code": 500, "message": "service error", "message_zh": "服务错误"}
    c = _crawler({SEARCH_ENDPOINT: resp})
    with pytest.raises(CrawlerError):
        c.search_products("シーツ")


def test_extract_product_id():
    c = TikHubProductCrawler(FakeHttpClient({}), api_key="k", region="JP")
    assert c._extract_product_id("https://www.tiktok.com/shop/pdp/x/1729408816995078528") \
        == "1729408816995078528"
    assert c._extract_product_id("1729408816995078528") == "1729408816995078528"
