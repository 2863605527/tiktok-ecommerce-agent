"""产品生命周期判断（跟卖窗口分析）——市面项目对标点（FastMoss 式）。

纯规则 + 真实数据：不调用 LLM、不花钱、可单测。输入是竞品真实评论时间序列
（reviews[].created_at，SocialCrawl JP 评论接口返回），用「评论热度的时间分布」
判断商品处于哪个阶段，并据此给出跟卖窗口建议。

阶段规则（评论是销量滞后的代理指标）：
- 萌芽期：总评论少（<15）且近 7 天出现新增评论 → 新品刚起量，跟卖窗口最宽但数据少
- 成长期：近 30 天评论占比 ≥ 40% → 热度上升，窗口开放、利润尚可
- 爆款期：评论总量多且近 30 天占比稳定在 20%-40% → 大盘在售，窗口收窄、靠差异化
- 衰退期：近 30 天占比 < 15% 或近 7 天零新增 → 热度退潮，不建议进场

数据不足时诚实降级：无评论时间 → None（不编造阶段）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from tiktok_ecommerce.models.product import Product


@dataclass
class LifecycleInsight:
    """一条生命周期/跟卖窗口结论（全部字段可空=数据不足，不编造）。"""

    stage: str = ""  # 萌芽期/成长期/爆款期/衰退期
    trend: str = ""  # 上升/平稳/下降
    recent30_ratio: float = 0.0  # 近 30 天评论占全部评论比例
    total_comments: int = 0
    window_advice: str = ""  # 跟卖窗口建议
    confidence: str = "低"  # 高/中/低（评论样本量决定）
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "trend": self.trend,
            "recent30_ratio": round(self.recent30_ratio, 3),
            "total_comments": self.total_comments,
            "window_advice": self.window_advice,
            "confidence": self.confidence,
            "note": self.note,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def analyze_lifecycle(product: Product | None,
                      now: datetime | None = None) -> LifecycleInsight:
    """根据竞品评论时间序列判断生命周期阶段与跟卖窗口。"""
    if product is None:
        return LifecycleInsight(note="无商品数据，无法判断生命周期")

    now = now or _now()
    reviews = getattr(product, "reviews", None) or []
    times = [r.created_at for r in reviews
             if isinstance(getattr(r, "created_at", None), datetime)]
    times = [t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in times]
    total = len(times)
    if total == 0:
        # 无评论时间：用评论数/销量代理（销量为 0 表示未披露，不能当真实 0）
        rc = getattr(product, "reviews_count", None)
        if rc:
            return LifecycleInsight(
                total_comments=int(rc),
                note="该数据源不返回评论时间，仅能确认有评论热度，无法判断所处阶段",
            )
        return LifecycleInsight(note="无评论数据，无法判断生命周期")

    recent30 = sum(1 for t in times if t >= now - timedelta(days=30))
    recent7 = sum(1 for t in times if t >= now - timedelta(days=7))
    ratio = recent30 / total

    # 置信度：样本量不足时只给方向不给强结论
    confidence = "高" if total >= 30 else ("中" if total >= 10 else "低")

    if total < 15 and recent7 > 0:
        stage, trend = "萌芽期", "上升"
        advice = "新品刚起量，跟卖窗口最宽；但样本少，建议小批量试单验证"
    elif ratio >= 0.40:
        stage, trend = "成长期", "上升"
        advice = "评论热度上升中，跟卖窗口开放；对标中位价入场，注意货源稳定"
    elif ratio >= 0.15:
        stage, trend = "爆款期", "平稳"
        advice = "已是大盘在售爆款，窗口收窄；建议差异化（规格/花色/组合）再跟"
    else:
        stage, trend = "衰退期", "下降"
        advice = "近 30 天评论占比低、热度退潮，不建议进场；除非有明确差异化打法"

    return LifecycleInsight(
        stage=stage, trend=trend, recent30_ratio=ratio,
        total_comments=total, window_advice=advice, confidence=confidence,
    )


def lifecycle_block(insight: LifecycleInsight) -> str:
    """转成给 LLM 的报告上下文片段（让分析 Agent 引用真实阶段结论）。"""
    if not insight.stage:
        return insight.note or "（无生命周期数据）"
    return (f"生命周期判断（规则引擎，基于 {insight.total_comments} 条真实评论时间序列）："
            f"{insight.stage}，近 30 天评论占比 {insight.recent30_ratio:.0%}，"
            f"趋势{insight.trend}，置信度{insight.confidence}。"
            f"跟卖建议：{insight.window_advice}")


def aggregate_competitors(products: list[Product],
                          now: datetime | None = None) -> dict:
    """多个竞品的生命周期汇总（选品报告市场概况用）。"""
    rows = []
    for p in products:
        ins = analyze_lifecycle(p, now)
        if ins.stage:
            rows.append({
                "title": (p.title or "")[:40],
                "stage": ins.stage,
                "trend": ins.trend,
                "recent30_ratio": round(ins.recent30_ratio, 3),
                "total_comments": ins.total_comments,
                "confidence": ins.confidence,
            })
    stages = {}
    for r in rows:
        stages[r["stage"]] = stages.get(r["stage"], 0) + 1
    return {
        "per_product": rows,
        "stage_distribution": stages,
        "summary": ("；".join(f"{k} {v} 个" for k, v in sorted(stages.items(),
                                                              key=lambda x: -x[1]))
                    if stages else "评论时间数据不足，无法判断阶段分布"),
    }
