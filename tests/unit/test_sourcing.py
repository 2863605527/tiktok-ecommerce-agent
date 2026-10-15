"""第六步 货源匹配 Agent 单元测试：多维打分、日语加分、LLM 精炼与回退。"""
from __future__ import annotations

import pytest

from tiktok_ecommerce.agents.sourcing_agent import SourcingAgent
from tiktok_ecommerce.categories.bedding import BeddingProfile
from tiktok_ecommerce.models.report import SelectionReport
from tiktok_ecommerce.models.supplier import SupplierOffer
from tests.conftest import FakeLLM


class FakeSupplierCrawler:
    """测试用货源爬虫（duck-type，不依赖抽象基类）。"""

    def __init__(self, offers: list[SupplierOffer]):
        self.offers = offers
        self.last_keywords: list[str] = []

    def search_offers(self, keywords: list[str], top_n: int = 10) -> list[SupplierOffer]:
        self.last_keywords = keywords
        return self.offers[:top_n]


def _offer(title: str, price: str = "¥20", min_order: str = "2件起批",
           delivery: str = "48小时发货", supplier: str = "南通XX家纺厂") -> SupplierOffer:
    return SupplierOffer(title=title, price=price, min_order=min_order,
                         delivery=delivery, supplier_name=supplier)


def _report(keywords: list[str] | None = None) -> SelectionReport:
    return SelectionReport(
        summary="纯棉床笠适合日本站", pros=["触感好"], cons=["缩水"],
        market_hot="高", competition="中", risks=[], suggestion="建议售卖",
        keywords=keywords or ["床笠 全棉 60支", "四件套 磨毛"],
    )


class TestScoring:
    def test_score_sort_by_total(self):
        offers = [
            _offer("日式纯棉床单笠件 全棉床罩席梦思床垫保护套 工厂直供 跨境专供",
                   price="¥18.50", min_order="2件起批", delivery="48小时发货"),
            _offer("夏季冷感床垫 凉感丝印花床护垫 可水洗", price="¥23.80",
                   min_order="2件起批", delivery="48小时发货"),
            _offer("日式磨毛四件套 加厚保暖床单被套 无印良品风 跨境一件代发",
                   price="¥79.00", min_order="1套起批", delivery="24小时发货"),
        ]
        keywords = ["床笠", "四件套", "純棉"]
        scored = SourcingAgent._score(offers, keywords)
        assert scored[0].match_score >= scored[1].match_score >= scored[2].match_score
        # 打分明细齐全
        assert set(scored[0].score_breakdown) == {
            "title_hit", "price", "min_order", "delivery", "jp_match", "brand",
        }

    def test_visual_label_survives_scoring(self):
        """以图找货的 visual/visual_label 在 _score 后必须保留（供前端展示）。"""
        offer = _offer("牛奶绒床笠 加厚保暖 90*200cm")
        offer.score_breakdown = {"visual": 0.72, "visual_label": "疑似同款"}
        scored = SourcingAgent._score([offer], ["牛奶绒床笠", "加厚"])
        assert scored[0].score_breakdown["visual_label"] == "疑似同款"
        assert scored[0].score_breakdown["visual"] == 0.72
        # 0.6*0.72 + 0.4*关键词分 → 视觉占主导
        assert scored[0].match_score >= 0.5

    def test_official_image_search_score_kept_authoritative(self):
        """官方视觉结果（ali_score）不被六维稀释，且 source/ali_score 标签保留。"""
        offer = _offer("北极绒床笠 宾利蓝 加厚保暖")
        offer.score_breakdown = {
            "visual": 1.0, "visual_label": "疑似同款",
            "ali_score": 1.0, "source": "official_image_search",
        }
        scored = SourcingAgent._score([offer], ["牛奶绒床笠", "加厚"])
        assert scored[0].match_score == 1.0  # 官方视觉分原样保留
        assert scored[0].score_breakdown["source"] == "official_image_search"
        assert scored[0].score_breakdown["ali_score"] == 1.0

    def test_jp_keywords_get_bonus(self):
        """含日文/中文商品词的货源 jp_match 加分（日本站场景）。"""
        offers = [
            _offer("ボックスシーツ 綿100% セミダブル オーガニックコットン", price="¥25"),
            _offer("通用款床单 无规格描述", price="¥20"),
        ]
        scored = SourcingAgent._score(offers, ["床笠", "ボックスシーツ"])
        assert scored[0].score_breakdown["jp_match"] > scored[1].score_breakdown["jp_match"]

    def test_brand_words_bonus(self):
        offers = [_offer("普通床单", supplier="小作坊"), _offer("床单 工厂直供 一件代发", supplier="X")]
        scored = SourcingAgent._score(offers, ["床单"])
        assert scored[0].score_breakdown["brand"] == 1.0
        assert scored[1].score_breakdown["brand"] == 0.3


class TestKeywordRefine:
    def test_llm_refine_success(self):
        agent = SourcingAgent(crawler=FakeSupplierCrawler([]), llm=FakeLLM(
            '```json\n["床笠 全棉 60支", "四件套 水洗棉"]\n```'))
        refined = agent._refine_keywords(_report(), ["兜底词"])
        assert refined == ["床笠 全棉 60支", "四件套 水洗棉"]

    def test_llm_refine_fallback_on_error(self):
        agent = SourcingAgent(crawler=FakeSupplierCrawler([]), llm=FakeLLM("抱歉，我无法"))
        assert agent._refine_keywords(_report(), ["兜底词1"]) == ["兜底词1"]


class TestRun:
    def test_run_no_report(self):
        agent = SourcingAgent(crawler=FakeSupplierCrawler([]), llm=FakeLLM("[]"))
        out = agent.run({"query": "x"})
        assert out["offers"] == [] and "跳过" in out["sourcing_note"]

    def test_run_full_flow(self):
        crawler = FakeSupplierCrawler([
            _offer("日式纯棉床笠 跨境专供"),
            _offer("冷感床垫 夏季"),
        ])
        agent = SourcingAgent(crawler=crawler, llm=FakeLLM(
            '["床笠 全棉", "四件套 磨毛"]'), category=BeddingProfile())
        out = agent.run({"report": _report(), "region": "JP"})
        assert crawler.last_keywords  # 搜索词已传给爬虫
        assert out["offers"] and out["sourcing_keywords"]
        assert all(0 <= o.match_score <= 1 for o in out["offers"])

    def test_run_translates_japanese_keywords(self):
        # LLM 输出日文关键词（真实发生过）→ 自动翻译为中文再搜中文货源站
        crawler = FakeSupplierCrawler([_offer("牛奶绒床笠 加厚 冬季")])
        agent = SourcingAgent(crawler=crawler, llm=FakeLLM(
            '["裏起毛 ボックスシーツ 冬用", "フランネル ベッドシーツ"]'),
            category=BeddingProfile())
        out = agent.run({"report": _report(), "region": "JP"})
        # 传给爬虫的必须是中文词（含床笠/法兰绒/保暖等），不含日文假名
        assert crawler.last_keywords
        assert any("床笠" in k for k in crawler.last_keywords)
        assert not any(any("\u3040" <= ch <= "\u30ff" for ch in k)
                       for k in crawler.last_keywords)

    def test_run_uses_image_search_when_product_has_image(self):
        # 采集的商品带图 → 优先走 search_offers_by_image（以图找货）
        class _ImageCrawler(FakeSupplierCrawler):
            def search_offers_by_image(self, query_image_url, keywords, top_n=6,
                                       query_title=""):
                self.last_image = query_image_url
                self.last_keywords = keywords
                self.last_title = query_title
                return [_offer("牛奶绒床笠 加厚")]

        class _Product:
            images = ["https://p16-oec-sg.ibyteimg.com/x.jpg"]
            title = "ポケットマットレス 冬用 フランネル"

        crawler = _ImageCrawler([_offer("牛奶绒床笠 加厚")])
        agent = SourcingAgent(crawler=crawler, llm=FakeLLM(
            '["牛奶绒床笠 加厚"]'), category=BeddingProfile())
        out = agent.run({"report": _report(), "region": "JP",
                         "products": [_Product()]})
        assert crawler.last_image == "https://p16-oec-sg.ibyteimg.com/x.jpg"
        assert crawler.last_title == "ポケットマットレス 冬用 フランネル"  # 标题传入作类目语义过滤
        assert out["offers"]

    def test_run_keyword_search_when_no_image(self):
        # 无商品图 → 回退关键词搜索（兼容无图数据源）
        crawler = FakeSupplierCrawler([_offer("牛奶绒床笠 加厚")])
        agent = SourcingAgent(crawler=crawler, llm=FakeLLM(
            '["牛奶绒床笠 加厚"]'), category=BeddingProfile())
        out = agent.run({"report": _report(), "region": "JP", "products": []})
        assert not hasattr(crawler, "last_image")  # 未走图搜
        assert out["offers"]

    def test_run_fallback_keywords_when_llm_words_no_stock(self):
        """真实案例：LLM 词（法兰绒床笠 加厚）在找家纺无货 → 自动用品类兜底词重试。"""
        class _EmptyFirstCrawler(FakeSupplierCrawler):
            def search_offers(self, keywords, top_n=6):
                self.last_keywords = keywords
                # 模拟：找家纺对"法兰绒床笠"组合无货（实测 0 条），对兜底模板词有货
                if any("法兰绒" in k and "床笠" in k for k in keywords):
                    return []
                return [_offer("牛奶绒床笠 加厚保暖 90*200cm")]
        crawler = _EmptyFirstCrawler([])
        agent = SourcingAgent(crawler=crawler, llm=FakeLLM(
            '["法兰绒床笠 加厚"]'), category=BeddingProfile())
        out = agent.run({"report": _report(), "region": "JP", "products": []})
        assert out["offers"], "LLM 词无货时必须用品类兜底词找到货源"
        assert any("床笠" in k for k in crawler.last_keywords)


class TestToChineseKeyword:
    def test_chinese_passthrough(self):
        from tiktok_ecommerce.agents.sourcing_agent import _to_chinese_keyword
        assert _to_chinese_keyword("牛奶绒床笠 加厚") == "牛奶绒床笠 加厚"

    def test_japanese_translated(self):
        from tiktok_ecommerce.agents.sourcing_agent import _to_chinese_keyword
        assert _to_chinese_keyword("ボックスシーツ 冬用") == "床笠 冬季 保暖"
        assert _to_chinese_keyword("ミルクフランネル 床笠") == "牛奶法兰绒 床笠"

    def test_untranslatable_returns_none(self):
        from tiktok_ecommerce.agents.sourcing_agent import _to_chinese_keyword
        # 纯片假名且不在映射表 → 丢弃（不硬塞给中文货源站）
        assert _to_chinese_keyword("ホゲホゲホゲ") is None
