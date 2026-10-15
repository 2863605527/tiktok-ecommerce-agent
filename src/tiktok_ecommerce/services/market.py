"""市场概况：基于真实采集的竞品价格做价位段分布与均价分析。

用途（真实卖家决策）：
- 看这个品类在目标市场卖多少钱：低价带是否拥挤、中高价位是否有空档
- 均价/中位辅助自己定价（新卖家通常先对标中位价）
- 价位段占比条形图数据（前端可视化直接用）
"""
from __future__ import annotations

import statistics
from typing import Any

# 价位段（按目标市场货币数值划分，JP 站即 JPY）：
#   低价 <1000 / 中低价 1000-1999 / 中价 2000-2999 / 中高价 3000-4999 / 高价 >=5000
PRICE_BANDS: list[tuple[str, float | None, float | None]] = [
    ("低价 <1,000", None, 1000),
    ("中低价 1,000-1,999", 1000, 2000),
    ("中价 2,000-2,999", 2000, 3000),
    ("中高价 3,000-4,999", 3000, 5000),
    ("高价 ≥5,000", 5000, None),
]


def build_market_overview(products: list[Any]) -> dict[str, Any]:
    """聚合竞品价格 → 价位段分布 + 均价/中位。

    只统计价格可解析（>0）的样本；币种以采集结果为准（JP 站为 JPY），
    调用方在 UI 上标注货币。样本 <3 时返回 note 提示参考意义有限。
    """
    prices: list[float] = []
    for p in products:
        raw = p.get("price") if isinstance(p, dict) else getattr(p, "price", "")
        v = 0.0
        if isinstance(p, dict):
            v = float(p.get("price_value", 0.0) or 0.0)
        if v <= 0 and raw:
            from tiktok_ecommerce.common.text import parse_price
            v = parse_price(raw)
        if v > 0:
            prices.append(v)

    sample_count = len(prices)
    if not prices:
        return {
            "bands": [{"label": b, "count": 0, "share": 0.0} for b, *_ in PRICE_BANDS],
            "avg_price": 0, "median_price": 0, "sample_count": 0,
            "note": "竞品价格数据不足（本数据源搜索卡不返回价格明细），无法统计价位分布。",
        }

    band_counts: dict[str, int] = {}
    for label, lo, hi in PRICE_BANDS:
        n = 0
        for v in prices:
            if (lo is None or v >= lo) and (hi is None or v < hi):
                n += 1
        band_counts[label] = n

    total = len(prices)
    bands = [
        {"label": label, "count": band_counts[label],
         "share": round(band_counts[label] / total, 3)}
        for label, *_ in PRICE_BANDS
    ]
    note = ""
    if sample_count < 3:
        note = f"样本仅 {sample_count} 个，价位分布参考意义有限。"
    return {
        "bands": bands,
        "avg_price": round(statistics.mean(prices), 1),
        "median_price": round(statistics.median(prices), 1),
        "min_price": min(prices),
        "max_price": max(prices),
        "sample_count": sample_count,
        "note": note,
    }
