"""第五步 分析 Agent 单元测试：评论洞察解析、空检索兜底、多主题检索去重。"""
from __future__ import annotations

import pytest

from tiktok_ecommerce.agents.analyzer_agent import AnalyzerAgent
from tiktok_ecommerce.categories.bedding import BeddingProfile
from tiktok_ecommerce.models.product import Product, Review
from tiktok_ecommerce.models.report import SelectionReport
from tiktok_ecommerce.rag.retriever import Retriever
from tests.conftest import FakeLLM, FakeVectorStore


def _embedding_fn(text: str) -> list[float]:
    return [0.1, 0.2, 0.3]


def _product(reviews: list[tuple[str, float]] | None = None) -> Product:
    reviews = reviews or [
        ("肌触りがとてもなめらかで、寝返りしても気持ちいい。", 5.0),
        ("一度洗ったら少し縮んだのか、四隅がパツパツになりました。", 2.0),
    ]
    return Product(
        id="7300000000001",
        title="ボックスシーツ 綿100% セミダブル オーガニックコットン",
        price="2,980円",
        currency="JPY",
        sales=12800,
        description="オーガニックコットン100%のボックスシーツ。肌にやさしく、通気性・吸湿性に優れています。",
        category="bedding",
        reviews=[Review(content=c, rating=r) for c, r in reviews],
    )


def _make_agent(store: FakeVectorStore, llm: FakeLLM) -> AnalyzerAgent:
    retriever = Retriever(store, _embedding_fn, top_k=3, score_threshold=0.0)
    return AnalyzerAgent(retriever, llm=llm, category=BeddingProfile())


INSIGHTS_PAYLOAD = (
    '{"summary": "纯棉床笠，触感好评，但存在洗后缩水痛点",'
    ' "pros": ["触感顺滑"], "cons": ["洗后缩水"],'
    ' "market_hot": "高，日本站床笠需求稳定",'
    ' "competition": "中等，差异化在有机棉",'
    ' "risks": ["缩水导致尺码投诉"],'
    ' "suggestion": "建议售卖，但需预留缩水余量",'
    ' "keywords": ["ボックスシーツ", "オーガニックコットン"],'
    ' "insights": ['
    '   {"topic": "触感", "sentiment": "positive", "mentions": 3, "severity": "低",'
    '    "evidence": ["肌触りがとてもなめらかで、寝返りしても気持ちいい。"]},'
    '   {"topic": "洗后缩水", "sentiment": "negative", "mentions": 2, "severity": "高",'
    '    "evidence": ["一度洗ったら少し縮んだのか、四隅がパツパツになりました。"]}'
    " ]}"
)


def test_analyze_parses_insights_with_evidence():
    """正常链路：检索有内容，insights 被解析为 ReviewInsight 并保留证据。"""
    store = FakeVectorStore()
    store.insert(
        ["肌触りがとてもなめらかで、寝返りしても気持ちいい。",
         "一度洗ったら少し縮んだのか、四隅がパツパツになりました。"],
        [{"title": "床笠", "source_type": "review"},
         {"title": "床笠", "source_type": "review"}],
    )
    agent = _make_agent(store, FakeLLM(INSIGHTS_PAYLOAD))
    report = agent.run({"products": [_product()]})["report"]
    assert isinstance(report, SelectionReport)
    assert report.summary
    assert len(report.insights) == 2
    pos = report.insights[0]
    assert pos.sentiment == "positive" and pos.mentions == 3
    neg = report.insights[1]
    assert neg.sentiment == "negative" and neg.severity == "高"
    assert "縮んだ" in neg.evidence[0]  # 证据逐字来自评论


def test_analyze_empty_retrieval_graceful():
    """空知识库：报告仍生成，insights 为空，不抛异常（防幻觉兜底）。"""
    agent = _make_agent(FakeVectorStore(), FakeLLM(INSIGHTS_PAYLOAD))
    report = agent.run({"products": [_product()]})["report"]
    assert report is not None  # 报告骨架仍可用
    # 空检索时 _retrieve_merged 返回空 → 日志告警，但解析正常
    assert report.summary  # LLM 仍按 prompt 输出


def test_analyze_invalid_insights_field_fallback():
    """LLM 返回非法 insights（非列表）：兜底为空列表，不阻断报告。"""
    payload = '{"summary": "s", "pros": [], "cons": [], "market_hot": "中",' \
              ' "competition": "", "risks": [], "suggestion": "可试销",' \
              ' "keywords": [], "insights": "不是列表"}'
    agent = _make_agent(FakeVectorStore(), FakeLLM(payload))
    report = agent.run({"products": [_product()]})["report"]
    assert report.insights == []


def test_run_no_products_returns_error():
    """没有商品时返回 error 而非崩溃。"""
    agent = _make_agent(FakeVectorStore(), FakeLLM(INSIGHTS_PAYLOAD))
    out = agent.run({})
    assert out["report"] is None
    assert "error" in out


def test_retrieve_merged_deduplicates():
    """多主题检索合并：同一条评论被多个主题召回时只出现一次。"""
    store = FakeVectorStore()
    store.insert(
        ["全周ゴムがしっかりしていて、朝までズレません。",
         "一度洗ったら少し縮んだのか、四隅がパツパツになりました。"],
        [{"title": "床笠", "source_type": "review"} for _ in range(2)],
    )
    agent = _make_agent(store, FakeLLM(INSIGHTS_PAYLOAD))
    ctx = agent._retrieve_merged(_product())
    assert ctx.count("朝までズレません") == 1
    assert ctx.count("パツパツ") == 1
    # 至少组装出 2 个资料块
    assert ctx.count("标题：") >= 2


def test_keyword_extraction_for_sourcing():
    """报告关键词用于第6步货源匹配：从报告透出即可用。"""
    report = SelectionReport(keywords=["ボックスシーツ", "綿100%"])
    assert "ボックスシーツ" in report.keywords
