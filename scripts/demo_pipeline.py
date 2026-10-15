"""第八步 端到端演示：一键运行全流程（采集 → 分析 → 货源 → 上架素材）。

运行（项目根目录，需真实 LLM Key；RAG_BACKEND 默认按 .env）：
    .venv\\Scripts\\python scripts\\demo_pipeline.py
可选参数：
    python scripts\\demo_pipeline.py --query "ボックスシーツ 綿100%" --stages crawler,analyzer,listing
说明：crawler 阶段会把采集到的竞品评论写入向量库（首次会入库）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tiktok_ecommerce.api.deps import get_pipeline  # noqa: E402
from tiktok_ecommerce.config import get_settings  # noqa: E402
from tiktok_ecommerce.services.report_service import ReportService  # noqa: E402


def main() -> int:
    s = get_settings()
    args = sys.argv[1:]
    query = "ボックスシーツ 綿100%"
    stages = None
    i = 0
    while i < len(args):
        if args[i] == "--query" and i + 1 < len(args):
            query = args[i + 1]
            i += 2
        elif args[i] == "--stages" and i + 1 < len(args):
            stages = tuple(x.strip() for x in args[i + 1].split(","))
            i += 2
        else:
            i += 1

    print("=" * 72)
    print(f"第八步 端到端流水线 | 后端 = {s.rag.backend} | 阶段 = {stages or '全部'}")
    print(f"关键词: {query} | 目标市场: JP | 语言: ja（日本站）")
    print("=" * 72)

    pipeline = get_pipeline(s, category_name="bedding", enabled_stages=stages)
    result = pipeline.run(query=query, region="JP", category="bedding", language="ja")

    # 落盘报告（Markdown + JSON）
    report_service = ReportService(s.output_dir)
    path = report_service.save(result, query)
    print(f"\n报告已保存: {path}")

    if result.get("error"):
        print(f"\n【错误】{result['error']}")
        return 1
    if result.get("products"):
        print(f"\n【① 采集】{len(result['products'])} 个竞品")
        for p in result["products"][:3]:
            print(f"   - {p.title} | {p.price} | 销量 {p.sales}")
    if result.get("report"):
        print(f"\n【② 分析】{result['report'].summary}")
        print(f"  建议: {result['report'].suggestion}")
    if result.get("offers"):
        print(f"\n【③ 货源】Top {min(3, len(result['offers']))}")
        for o in result["offers"][:3]:
            print(f"   [{o.match_score:.2f}] {o.title} | {o.price} | {o.delivery}")
    if result.get("listing_path"):
        print(f"\n【④ 素材包】{result['listing_path']}")
    print("\n" + "=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
