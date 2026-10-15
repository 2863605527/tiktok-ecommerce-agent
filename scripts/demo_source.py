"""第六步 货源匹配演示：选品报告 → LLM 精炼关键词 → 家纺货源 → 多维打分对比。

运行（项目根目录，需真实 LLM Key）：
    .venv\\Scripts\\python scripts\\demo_source.py
数据源由 .env 的 SUPPLIER_SOURCE 决定：sample（91家纺风格样本，默认）
| jiafang（91家纺直连扩展点）| 1688（可选）| api（开放平台）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tiktok_ecommerce.agents.sourcing_agent import SourcingAgent  # noqa: E402
from tiktok_ecommerce.categories.registry import get_category  # noqa: E402
from tiktok_ecommerce.common.llm import create_llm  # noqa: E402
from tiktok_ecommerce.config import get_settings  # noqa: E402
from tiktok_ecommerce.crawlers.factory import get_supplier_crawler  # noqa: E402
from tiktok_ecommerce.models.report import SelectionReport  # noqa: E402

# 演示用的选品报告（生产环境来自第5步 AnalyzerAgent 输出）
SAMPLE_REPORT = SelectionReport(
    summary="纯棉床笠（ボックスシーツ）触感好评，但存在洗后缩水痛点，日本站需求稳定",
    pros=["触感顺滑", "全周皮筋防移位"],
    cons=["洗后缩水", "四角变紧"],
    market_hot="高，日本站床笠需求稳定",
    competition="中等，差异化在有机棉与尺寸适配",
    risks=["缩水导致尺码投诉", "日本尺寸体系需换算"],
    suggestion="建议售卖：选预留缩水余量的货源，规格按日本尺寸标注",
    keywords=["床笠 全棉 60支", "ボックスシーツ", "オーガニックコットン", "四件套 日式"],
    insights=[],
)


def main() -> int:
    s = get_settings()
    category = get_category(s.pipeline.default_category)
    print("=" * 72)
    print(f"第六步 货源匹配 | 数据源 = {s.crawler.supplier_source} | 品类 = {category.display_name}")
    print("=" * 72)

    llm = create_llm(s)
    crawler = get_supplier_crawler(s, category=s.pipeline.default_category)
    agent = SourcingAgent(crawler, llm=llm, top_n=s.pipeline.sourcing_top_n, category=category)

    out = agent.run({"report": SAMPLE_REPORT, "region": "JP"})
    offers = out.get("offers", [])
    print(f"\nLLM 精炼搜索词: {out.get('sourcing_keywords')}\n")

    if not offers:
        print("未匹配到货源。")
        return 1

    print(f"共 {len(offers)} 条货源（按综合匹配分排序）\n")
    weights = {"title_hit": 0.40, "price": 0.15, "min_order": 0.15,
               "delivery": 0.15, "jp_match": 0.10, "brand": 0.05}
    for i, o in enumerate(offers, 1):
        print(f"[{i}] 综合 {o.match_score:.2f} | {o.title}")
        print(f"    {o.price} | {o.min_order} | {o.delivery} | {o.supplier_name}")
        detail = "  ".join(f"{k}={v:.2f}(×{weights[k]:.2f})" for k, v in o.score_breakdown.items())
        print(f"    打分明细: {detail}")
        print()
    print("=" * 72)
    print("打分维度：标题命中(40%) + 价格(15%) + 起批(15%) + 发货(15%)"
          "\n          + 日文规格词(10%，日本站适配) + 供应商背书(5%)")
    print("切换真实货源：.env 设置 SUPPLIER_SOURCE=jiafang（91家纺）或 1688，并配代理。")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
