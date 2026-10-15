"""SocialCrawl TikTok Shop 客户端单元测试（纯离线，FakeHttpClient 模拟官方响应）。"""
import pytest

from tiktok_ecommerce.common.exceptions import CrawlerError
from tiktok_ecommerce.crawlers.http import HttpClient
from tiktok_ecommerce.crawlers.socialcrawl import (
    SocialCrawlProductCrawler,
    REVIEWS_ENDPOINT,
    SEARCH_ENDPOINT,
    SUPPORTED_REGIONS,
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
        return {"success": True, "data": {"items": []}}


# 官方文档示例响应（socialcrawl.dev/platforms/tiktokshop/product-reviews）
_REVIEWS_RESPONSE = {
    "success": True,
    "platform": "tiktokshop",
    "endpoint": "/v1/tiktokshop/product/reviews",
    "data": {
        "items": [
            {
                "review": {
                    "id": "7609467006076651278",
                    "entity_id": "1731578642912612516",
                    "text": "Sample comment text (redacted).",
                    "rating": {"value": 5, "max": 5},
                    "author": {"name": "user_54bd34", "avatar_url": None, "url": None},
                    "verified": True,
                    "published_at": "2026-02-21T23:38:43.706Z",
                    "ext": {"tiktokshop": {
                        "reviewer_id": "user_4a2160",
                        "is_incentivized_review": False,
                        "sku_specification": "Sample SKU",
                    }},
                }
            }
        ],
        "total": 1115,
    },
    "credits_used": 1,
    "request_id": "req_example000000",
    "cached": False,
    "pagination": {"next_cursor": "sc.eyJ2Ijoy", "has_more": True, "page_size": 10},
}

# 官方文档示例响应（search 端点）
_SEARCH_RESPONSE = {
    "success": True,
    "data": {
        "items": [
            {
                "product": {
                    "id": "1729587769570529799",
                    "title": "Example product",
                    "price": {"current": 19.99, "currency": "USD"},
                    "rating": 4.7,
                    "url": "https://www.tiktok.com/shop/pdp/example",
                    "seller": {"name": "test shop"},
                }
            }
        ]
    },
    "credits_used": 1,
    "credits_remaining": 99,
}


def _crawler(responses: dict) -> SocialCrawlProductCrawler:
    return SocialCrawlProductCrawler(
        FakeHttpClient(responses), api_key="sc_test_key", region="JP"
    )


def test_supported_regions_include_jp():
    assert "JP" in SUPPORTED_REGIONS  # 日本站可用


def test_search_maps_product():
    c = _crawler({SEARCH_ENDPOINT: _SEARCH_RESPONSE})
    products = c.search_products("ボックスシーツ", limit=5)
    assert len(products) == 1
    p = products[0]
    assert p.id == "1729587769570529799"
    assert p.title == "Example product"
    assert p.price == "19.99"
    assert p.currency == "USD"
    assert p.url.startswith("https://www.tiktok.com")
    # 热度代理指标：标量评分 → rating，卖家名映射
    assert p.rating == 4.7
    assert p.seller == "test shop"
    assert p.sales == 0  # SocialCrawl 搜索卡不返回销量 → 0 表示未披露


def test_search_maps_rating_dict_and_reviews_count():
    """真实 API 返回 rating 为 dict + reviews_count 字段时正确映射。"""
    resp = {
        "success": True,
        "data": {"items": [{"product": {
            "id": "1737431818501325857",
            "title": "ふわふわミルクフランネルボックスシーツ",
            "price": {"current": 1428},
            "rating": {"average": 3.9, "count": 12},
            "reviews_count": 8,
            "availability": "in_stock",
            "brand": "MilkHome",
            "seller": {"name": "ミルク寝具店"},
            "url": "https://www.tiktok.com/shop/pdp/x",
            "image_urls": ["https://img.example/1.jpg"],
        }}]},
        "credits_used": 1,
    }
    c = _crawler({SEARCH_ENDPOINT: resp})
    p = c.search_products("ボックスシーツ")[0]
    assert p.rating == 3.9
    assert p.reviews_count == 8
    assert p.availability == "in_stock"
    assert p.brand == "MilkHome"
    assert p.seller == "ミルク寝具店"
    assert p.images == ["https://img.example/1.jpg"]
    assert p.sales == 0


def test_search_sends_region():
    c = _crawler({SEARCH_ENDPOINT: _SEARCH_RESPONSE})
    c.search_products("シーツ")
    _, _, params = c.client.calls[0]
    assert params["region"] == "JP"
    assert params["query"] == "シーツ"


def test_reviews_maps_review():
    c = _crawler({REVIEWS_ENDPOINT: _REVIEWS_RESPONSE})
    reviews = c.fetch_reviews("1731578642912612516")
    assert len(reviews) == 1
    r = reviews[0]
    assert r.content == "Sample comment text (redacted)."
    assert r.rating == 5.0
    assert r.author == "user_54bd34"
    assert r.created_at is not None


def test_reviews_limit():
    resp = dict(_REVIEWS_RESPONSE)
    resp["data"] = {"items": [_REVIEWS_RESPONSE["data"]["items"][0]] * 20, "total": 20}
    c = _crawler({REVIEWS_ENDPOINT: resp})
    reviews = c.fetch_reviews("123", max_comments=3)
    assert len(reviews) == 3


def test_failure_raises_crawler_error():
    resp = {"success": False, "data": "quota exceeded"}
    c = _crawler({SEARCH_ENDPOINT: resp})
    with pytest.raises(CrawlerError):
        c.search_products("シーツ")


def test_unsupported_region_rejected():
    with pytest.raises(CrawlerError):
        SocialCrawlProductCrawler(
            FakeHttpClient({}), api_key="k", region="CN"
        )


def test_extract_product_id():
    c = SocialCrawlProductCrawler(FakeHttpClient({}), api_key="k", region="JP")
    assert c._extract_product_id("https://www.tiktok.com/shop/pdp/example/1731578642912612516") \
        == "1731578642912612516"
    assert c._extract_product_id("1731578642912612516") == "1731578642912612516"
