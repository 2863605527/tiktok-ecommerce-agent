"""第三轮：决策增强单元测试（评分/市场概况/关键词挖掘/利润测算）。"""
from __future__ import annotations

import pytest

from tiktok_ecommerce.services.keyword_mining import extract_keyword_insights
from tiktok_ecommerce.services.market import build_market_overview
from tiktok_ecommerce.services.profit import ProfitRequest, compute_profit
from tiktok_ecommerce.services.scoring import compute_selection_score


def _result(products=None, report=None, offers=None, listing_path="") -> dict:
    return {
        "products": products or [],
        "report": report,
        "offers": offers or [],
        "listing_path": listing_path,
    }


def _offer(price="¥12.50", match=0.9):
    return {"title": "t", "price": price, "match_score": match, "supplier_name": "s"}


# ---------- 评分 ----------

def test_score_strong_result():
    r = _result(
        products=[{"title": "x", "price": "1,800", "rating": 4.5, "reviews_count": 120}],
        report={"market_hot": "高，冬季热卖", "insights": [
            {"topic": "触感", "sentiment": "positive", "mentions": 8},
            {"topic": "缩水", "sentiment": "negative", "mentions": 2},
        ]},
        offers=[_offer()],
        listing_path="listings/x/listing.json",
    )
    s = compute_selection_score(r)
    assert s["total"] >= 70
    assert s["level"] in ("推荐", "强烈推荐")
    assert s["dims"]["heat"]["score"] >= 25
    assert s["dims"]["supply"]["score"] >= 22
    assert s["dims"]["listing"]["score"] == 15


def test_score_empty_result_is_conservative():
    s = compute_selection_score(_result())
    assert s["total"] < 40
    assert s["level"] == "谨慎"
    # 无报告 → 口碑中性分
    assert s["dims"]["demand"]["score"] == 12


def test_score_dim_ranges():
    r = _result(
        products=[{"title": "x", "price": "999"}],
        report={"market_hot": "低"},
        offers=[],
    )
    s = compute_selection_score(r)
    assert 0 <= s["dims"]["heat"]["score"] <= 30
    assert 0 <= s["dims"]["supply"]["score"] <= 25
    assert s["dims"]["listing"]["score"] == 0


# ---------- 市场概况 ----------

def test_market_overview_bands():
    products = [{"title": f"p{i}", "price": str(v), "currency": "JPY"}
                for i, v in enumerate([500, 1500, 2500, 4000, 6000])]
    m = build_market_overview(products)
    assert m["sample_count"] == 5
    assert m["median_price"] == 2500
    assert sum(b["count"] for b in m["bands"]) == 5
    assert m["bands"][0]["label"].startswith("低价")
    assert m["bands"][4]["label"].startswith("高价")
    assert m["bands"][0]["count"] == 1


def test_market_overview_empty():
    m = build_market_overview([])
    assert m["sample_count"] == 0
    assert m["note"]


# ---------- 关键词挖掘 ----------

def test_keyword_insights_sources():
    r = _result(
        products=[{"title": "ボックスシーツ 冬用 あったか ベッドシーツ"}],
        report={
            "keywords": ["床笠", "冬用"],
            "insights": [{"topic": "触感", "sentiment": "positive", "mentions": 3}],
        },
    )
    k = extract_keyword_insights(r)
    words = [w["word"] for w in k["top"]]
    assert "床笠" in words or "冬用" in words
    assert "触感" in words
    # 竞品标题命中品类词
    assert any("ボックスシーツ" in w or "シーツ" in w for w in words)
    assert all(w["source"] for w in k["top"])


def test_keyword_insights_empty():
    k = extract_keyword_insights(_result())
    assert k["top"] == []
    assert "没有" in k["note"]


def test_keyword_insights_fallback_from_query():
    """三个真实来源为空时，用检索词兜底拆词，保证面板可用。"""
    k = extract_keyword_insights(_result(), query="牛奶绒床笠 四件套")
    words = [i["word"] for i in k["top"]]
    assert words, "兜底关键词不应为空"
    assert "牛奶绒" in words or "床笠" in words
    assert all(i["source"] == "检索词" for i in k["top"])
    assert "兜底" in k["note"]


def test_keyword_insights_fallback_none_when_no_query():
    k = extract_keyword_insights(_result())
    assert k["top"] == []


# ---------- 利润测算 ----------

def test_profit_positive():
    r = compute_profit(ProfitRequest(selling_price_jpy=3000, cost_cny=80, shipping_cny=30))
    assert r.selling_price_jpy == 3000
    assert r.cost_jpy == 80 * r.fx_used
    assert r.net_margin > 0
    assert r.platform_fee_jpy == pytest.approx(3000 * 0.08, abs=0.1)
    assert "估算" in r.note


def test_profit_negative_margin():
    r = compute_profit(ProfitRequest(selling_price_jpy=1000, cost_cny=80, shipping_cny=20))
    assert r.net_profit_jpy < 0
    assert r.net_margin < 0


def test_profit_break_even():
    r = compute_profit(ProfitRequest(selling_price_jpy=8000, cost_cny=80,
                                     shipping_cny=30, ads_jpy=3000))
    assert r.break_even_units is not None and r.break_even_units > 0
    # 广告 0 → 无需回本
    r2 = compute_profit(ProfitRequest(selling_price_jpy=8000, cost_cny=80, shipping_cny=30))
    assert r2.break_even_units is None


def test_profit_custom_fx():
    r = compute_profit(ProfitRequest(selling_price_jpy=3000, cost_cny=100, fx_cny_jpy=20))
    assert r.fx_used == 20
    assert r.cost_jpy == 2000
