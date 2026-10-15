"""CrawlerAgent 品类过滤测试：泛问时只保留本品类（床上用品）商品，非家纺如实剔除。"""
from __future__ import annotations

from tiktok_ecommerce.agents.crawler_agent import CrawlerAgent
from tiktok_ecommerce.categories.base import CategoryProfile
from tiktok_ecommerce.categories.bedding import BeddingProfile
from tiktok_ecommerce.models.product import Product


class _FakeCrawler:
    def __init__(self, products):
        self._products = products

    def search_products(self, query: str, limit: int = 3):
        return self._products[:limit]


class _FakeVectorStore:
    def __init__(self):
        self.inserted = []

    def insert(self, texts, metadatas, embedding_fn=None):
        self.inserted.extend(texts)


def _mk(title: str) -> Product:
    return Product(title=title, price="1200", currency="JPY", url=f"https://t/{title[:5]}",
                   description="", sales=0, category="bedding")


class TestBeddingMarkers:
    """判定词覆盖：日文/英文/中文家纺标题都能命中，非家纺不命中。"""

    def test_jp_bedding_hits(self):
        p = BeddingProfile()
        assert p.matches_category("クリスタルフランネル ボックスシーツ 冬用 速暖")
        assert p.matches_category("掛け布団カバー 4点セット 純棉")
        assert p.matches_category("羽毛布団 ダブル 保温")

    def test_en_zh_hits(self):
        p = BeddingProfile()
        assert p.matches_category("Electric Blanket Warm Winter")
        assert p.matches_category("四件套 纯棉 60支 1.8m")

    def test_non_bedding_misses(self):
        p = BeddingProfile()
        assert not p.matches_category("電気暖房ジャケット 日本製ヒーター")
        assert not p.matches_category("iPhone 16 Pro Case カバー")
        assert not p.matches_category("フード付きパーカー 冬用")


class TestCrawlerCategoryFilter:
    """采集后按品类过滤：保留家纺、剔除非家纺、全剔除时如实返回说明。"""

    def _agent(self, products, category: CategoryProfile | None = None):
        return CrawlerAgent(
            _FakeCrawler(products), _FakeVectorStore(), embedding_fn=lambda t: [0.0],
            category=category,
        )

    def test_mixed_keeps_bedding_only(self):
        products = [
            _mk("クリスタルフランネル ボックスシーツ 冬用 速暖"),   # 家纺
            _mk("電気暖房ジャケット 日本製ヒーター"),                 # 非家纺
            _mk("抗菌 布団カバー シングル"),                            # 家纺
        ]
        agent = self._agent(products, BeddingProfile())
        out = agent.run({"query": "日本冬天", "region": "JP"})
        assert len(out["products"]) == 2
        assert all("シーツ" in p.title or "布団" in p.title for p in out["products"])
        assert "品类过滤" in out.get("filtered_note", "")

    def test_all_non_bedding_returns_empty_with_note(self):
        products = [_mk("電気暖房ジャケット 日本製ヒーター"), _mk("フード付きパーカー")]
        agent = self._agent(products, BeddingProfile())
        out = agent.run({"query": "日本冬天有什么好卖", "region": "JP"})
        assert out["products"] == []
        assert "都不是床上用品" in out["filtered_note"]
        assert "ボックスシーツ" in out["filtered_note"]  # 引导用户明确家纺品名

    def test_generic_category_no_filter(self):
        products = [_mk("電気暖房ジャケット 日本製ヒーター")]
        agent = self._agent(products, CategoryProfile())  # 通用品类无判定词
        out = agent.run({"query": "x", "region": "JP"})
        assert len(out["products"]) == 1  # 不过滤
