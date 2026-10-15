"""选品推荐评分：把流水线结果量化为 0-100 可解释分数（决策辅助）。

设计（企业级）：
- 纯规则打分，无 LLM 调用：可复现、可单测、零成本
- 四维打分：热度(30) + 口碑需求(30) + 货源匹配(25) + 上架完整度(15)
- 每个维度输出理由（reasons），分数可解释、可审计
- 数据缺失时给保守基础分并注明，不编造高分
"""
from __future__ import annotations

from typing import Any


def _heat_score(report: dict[str, Any] | None, products: list[dict[str, Any]]) -> tuple[float, list[str]]:
    """热度维度（满分 30）：market_hot 文本 + 热度代理指标（评分/评论数/销量）。"""
    score = 0.0
    reasons: list[str] = []
    if report:
        hot = (report.get("market_hot") or "").lower()
        if "高" in hot:
            score += 22
            reasons.append("市场热度判定为高")
        elif "中" in hot:
            score += 15
            reasons.append("市场热度判定为中")
        elif "低" in hot:
            score += 7
            reasons.append("市场热度判定为低（谨慎）")
    p = products[0] if products else {}
    if p.get("rating"):
        score += 3
        reasons.append(f"竞品有评分 {p['rating']}")
    if p.get("reviews_count"):
        score += 3
        reasons.append(f"竞品有评论数 {p['reviews_count']}")
    if p.get("sales"):
        score += 2
        reasons.append(f"竞品销量 {p['sales']}")
    return min(30.0, score), reasons


def _demand_score(report: dict[str, Any] | None) -> tuple[float, list[str]]:
    """口碑需求维度（满分 30）：评论聚类正/负提及比。"""
    insights = (report or {}).get("insights") or []
    if not insights:
        return 12.0, ["评论资料不足，口碑维度取中性分（12/30）"]
    pos = sum(int(i.get("mentions", 0)) for i in insights if i.get("sentiment") == "positive")
    neg = sum(int(i.get("mentions", 0)) for i in insights if i.get("sentiment") == "negative")
    total = pos + neg
    if total == 0:
        return 12.0, ["评论聚类无提及统计，取中性分"]
    ratio = pos / total
    score = 10 + 20 * ratio  # 全负面 10，全正面 30
    pos_topics = [i.get("topic", "") for i in insights if i.get("sentiment") == "positive"][:2]
    neg_topics = [i.get("topic", "") for i in insights if i.get("sentiment") == "negative"][:2]
    reasons = [f"评论口碑 {pos}/{total} 正面（{score:.0f}/30）"]
    if pos_topics:
        reasons.append("正面主题：" + "、".join(pos_topics))
    if neg_topics:
        reasons.append("负面主题：" + "、".join(neg_topics))
    return round(min(30.0, max(10.0, score)), 1), reasons


def _supply_score(offers: list[dict[str, Any]]) -> tuple[float, list[str]]:
    """货源匹配维度（满分 25）：有货源 + Top 匹配度。"""
    if not offers:
        return 5.0, ["暂无匹配货源（可换关键词再找）"]
    top = offers[0]
    match = float(top.get("match_score", 0.0) or 0.0)
    score = 10 + 15 * match
    reasons = [f"匹配到 {len(offers)} 条真实货源，Top 匹配度 {match:.2f}"]
    if top.get("price"):
        reasons.append(f"最低供货价 {top['price']}")
    return round(min(25.0, score), 1), reasons


def _listing_score(result: dict[str, Any]) -> tuple[float, list[str]]:
    """上架完整度维度（满分 15）：素材包是否落地。"""
    if result.get("listing_path"):
        return 15.0, ["日文上架素材包已生成（可直接导出）"]
    if result.get("listing"):
        return 10.0, ["已生成素材文案，但未落盘文件"]
    return 0.0, ["尚未生成上架素材（可补跑「上架素材」阶段）"]


def _timing_score(products: list[dict[str, Any]]) -> tuple[float, list[str]]:
    """进场时机维度（旁路参考，0-100，不占四维总分）：生命周期阶段 → 时机分。

    用竞品生命周期判断"现在进场是否来得及"：
      萌芽期 85（窗口最宽）/ 成长期 70（开放）/ 爆款期 50（收窄，靠差异化）
      / 衰退期 20（不建议）/ 数据不足 45（诚实中立，注明原因）。
    """
    if not products:
        return 45.0, ["无竞品数据，进场时机无法判断（中立分）"]
    stage = products[0].get("lifecycle_stage") or ""
    if not stage:
        return 45.0, ["评论时间数据不足，无法判断进场时机（中立分）"]
    table = {"萌芽期": 85.0, "成长期": 70.0, "爆款期": 50.0, "衰退期": 20.0}
    score = table.get(stage, 45.0)
    reasons = {
        "萌芽期": "竞品处于萌芽期：窗口最宽，小批量试单验证",
        "成长期": "竞品处于成长期：热度上升，对标中位价进场",
        "爆款期": "竞品处于爆款期：窗口收窄，需差异化（规格/花色）",
        "衰退期": "竞品处于衰退期：热度退潮，不建议进场",
    }
    return score, [reasons.get(stage, "生命周期阶段未知")]


def compute_selection_score(result: dict[str, Any]) -> dict[str, Any]:
    """计算选品推荐分（0-100），返回结构化分数与理由。

    result 结构兼容流水线状态与 API SelectionResponse：
      products / report / offers / listing / listing_path
    """
    products = [p for p in (result.get("products") or []) if isinstance(p, dict)]
    offers = [o for o in (result.get("offers") or []) if isinstance(o, dict)]
    report = result.get("report")
    if isinstance(report, dict):
        pass
    elif hasattr(report, "model_dump"):
        report = report.model_dump()
    else:
        report = None

    heat, heat_reasons = _heat_score(report, products)
    demand, demand_reasons = _demand_score(report)
    supply, supply_reasons = _supply_score(offers)
    listing, listing_reasons = _listing_score(result)
    timing, timing_reasons = _timing_score(products)  # 旁路参考，不计入总分

    total = round(heat + demand + supply + listing, 1)
    if total >= 80:
        level, verdict = "强烈推荐", "热度与口碑双高，货源充足，建议尽快上架"
    elif total >= 65:
        level, verdict = "推荐", "整体条件不错，可按评估中的风险点微调后上架"
    elif total >= 50:
        level, verdict = "观望", "有条件成立，建议先小批量测试"
    else:
        level, verdict = "谨慎", "存在明显短板（热度/口碑/货源至少一项不足），不建议贸然投入"

    return {
        "total": total,
        "level": level,
        "verdict": verdict,
        "dims": {
            "heat": {"score": heat, "max": 30, "label": "市场热度", "reasons": heat_reasons},
            "demand": {"score": demand, "max": 30, "label": "评论口碑", "reasons": demand_reasons},
            "supply": {"score": supply, "max": 25, "label": "货源匹配", "reasons": supply_reasons},
            "listing": {"score": listing, "max": 15, "label": "上架就绪", "reasons": listing_reasons},
        },
        "timing": {
            "score": timing, "max": 100, "label": "进场时机",
            "reasons": timing_reasons,
            "note": "旁路参考（基于竞品生命周期，不计入总分）",
        },
    }
