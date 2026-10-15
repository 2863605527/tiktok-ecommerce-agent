"""关键词挖掘：从选品结果聚合「真实可用的搜索关键词」建议。

数据来源（全部真实、可溯源，杜绝编造）：
- LLM 报告关键词（report.keywords）—— 来源标注「报告提炼」
- 评论主题聚类（insights.topic）—— 来源标注「评论聚类」
- 竞品标题命中的品类词（bedding.category_markers）—— 来源标注「竞品标题」

用途：上架标题 SEO / TikTok 站内搜索词 / 找货源搜索词 三合一建议。
"""
from __future__ import annotations

from collections import Counter
from typing import Any


def _dedupe_keep_order(items: list[str], max_n: int = 12) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        k = it.strip()
        if not k or k.lower() in seen:
            continue
        seen.add(k.lower())
        out.append(k)
        if len(out) >= max_n:
            break
    return out


def extract_keyword_insights(
    result: dict[str, Any],
    category_name: str = "bedding",
    query: str | None = None,
) -> dict[str, Any]:
    """聚合关键词建议：去重 + 来源标注 + 频次统计。

    query 为本次检索词（如「牛奶绒床笠 四件套」），当三个真实来源都为空时
    作为兜底拆词（标注「检索词」），保证关键词面板永远有可用内容。
    """
    report = result.get("report")
    if isinstance(report, dict):
        pass
    elif hasattr(report, "model_dump"):
        report = report.model_dump()
    else:
        report = None

    items: list[tuple[str, str, int]] = []  # (词, 来源, 权重)
    if report:
        for k in report.get("keywords") or []:
            if k:
                items.append((str(k), "报告提炼", 3))
        for ins in report.get("insights") or []:
            topic = (ins.get("topic") if isinstance(ins, dict) else getattr(ins, "topic", "")) or ""
            if topic:
                items.append((str(topic), "评论聚类", 2))

    # 竞品标题命中品类词 → 真实搜索词证据
    markers: list[str] = []
    try:
        from tiktok_ecommerce.categories.bedding import BeddingProfile
        markers = list(BeddingProfile.category_markers)
    except Exception:
        pass
    title_hits: Counter = Counter()
    for p in result.get("products") or []:
        title = p.get("title", "") if isinstance(p, dict) else getattr(p, "title", "")
        for m in markers:
            if m and m.lower() in str(title).lower():
                title_hits[m] += 1
    for word, cnt in title_hits.most_common(6):
        if cnt >= 1:
            items.append((word, f"竞品标题 ×{cnt}", 1))

    # 汇总：按来源优先级排序（报告提炼 > 评论聚类 > 竞品标题），同词频次累计
    freq: Counter = Counter()
    sources: dict[str, str] = {}
    for word, source, weight in items:
        freq[word] += weight
        sources.setdefault(word, source)
    ranked = sorted(freq.items(), key=lambda x: -x[1])
    top = [{"word": w, "count": c, "source": sources[w]} for w, c in ranked[:12]]

    note = "关键词来自报告提炼/评论聚类/竞品标题，可直接用于上架标题与搜索词。"
    if not top:
        # 兜底：从检索词拆出有意义的关键词（中文/日文名词短语），保证面板可用
        fallback = _fallback_from_query(query)
        if fallback:
            top = [{"word": w, "count": 1, "source": "检索词"} for w in fallback]
            note = "三个真实来源暂无可挖掘词，已用本次检索词作为关键词兜底（可换更细的搜索词重试）。"
        else:
            note = "当前结果没有可挖掘的关键词（缺少报告或竞品），可先跑完选品流程。"
    return {"top": top, "note": note}


def _fallback_from_query(query: str | None) -> list[str]:
    """从检索词拆出候选关键词：先按空格/逗号拆分，再按品类常见后缀拆分长词。"""
    if not query:
        return []
    q = str(query).strip()
    parts = [p.strip() for p in q.replace(",", " ").replace("，", " ").split() if p.strip()]
    out: list[str] = []
    for p in parts:
        out.append(p)
        # 长词（如「牛奶绒床笠」）→ 拆出材质词 + 品类词
        for suf in ("床笠", "四件套", "床单", "被套", "枕套", "床品", "毯", "垫"):
            if p.endswith(suf) and len(p) > len(suf) + 1:
                out.append(p[: -len(suf)])
                break
    return _dedupe_keep_order(out, max_n=8)
