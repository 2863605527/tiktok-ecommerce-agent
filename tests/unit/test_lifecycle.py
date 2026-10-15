"""产品生命周期/跟卖窗口模块测试（纯规则、真实评论时间序列驱动）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tiktok_ecommerce.models.product import Product, Review
from tiktok_ecommerce.services.lifecycle import analyze_lifecycle, aggregate_competitors


def _mk(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def _product(review_days: list[int], reviews_count: int | None = None) -> Product:
    reviews = [Review(content=f"评论{i}", rating=4.5, created_at=_mk(d)) for i, d in enumerate(review_days)]
    return Product(id="p1", title="牛奶绒四件套", reviews=reviews, reviews_count=reviews_count)


def test_no_reviews_honest_note():
    ins = analyze_lifecycle(Product(id="p", title="t"))
    assert ins.stage == ""
    assert "无法判断" in ins.note


def test_no_review_time_uses_count_proxy():
    ins = analyze_lifecycle(_product([], reviews_count=88))
    assert ins.stage == ""
    assert ins.total_comments == 88
    assert "无法判断所处阶段" in ins.note


def test_growth_stage_high_recent30():
    # 大量评论集中在近 30 天 → 成长期
    days = [2, 4, 7, 9, 12, 15, 18, 22, 25, 29, 31, 45, 60, 90, 120, 150]
    ins = analyze_lifecycle(_product(days))
    assert ins.stage == "成长期"
    assert ins.trend == "上升"
    assert ins.recent30_ratio >= 0.40
    assert "窗口开放" in ins.window_advice


def test_decline_stage_low_recent30():
    # 评论集中在很久以前 → 衰退期
    days = [80, 90, 100, 110, 130, 150, 170, 190, 220, 260, 300, 340, 380, 420]
    ins = analyze_lifecycle(_product(days))
    assert ins.stage == "衰退期"
    assert ins.trend == "下降"
    assert "不建议进场" in ins.window_advice


def test_burst_stage_stable():
    days = list(range(3, 120, 5))  # 均匀分布
    ins = analyze_lifecycle(_product(days))
    assert ins.stage in {"成长期", "爆款期"}
    assert ins.trend in {"上升", "平稳"}


def test_aggregate_distribution():
    products = [
        _product([2, 4, 7, 10, 13]),
        _product([100, 110, 130, 150]),
        _product([3, 6, 9, 12, 15, 20, 25, 30, 40, 55, 70, 90, 120]),
    ]
    agg = aggregate_competitors(products)
    assert agg["per_product"]
    assert agg["stage_distribution"]
    assert "个" in agg["summary"]
