"""第五步 评论RAG分析演示：采集样本 → 入库 → 多主题检索 → LLM 输出带证据的选品报告。

运行（项目根目录，需真实 LLM Key，见 .env）：
    .venv\\Scripts\\python scripts\\demo_analyze.py
后端与第四步一致（RAG_BACKEND=memory|milvus|ragflow），默认按 .env 配置。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tiktok_ecommerce.agents.analyzer_agent import AnalyzerAgent  # noqa: E402
from tiktok_ecommerce.agents.crawler_agent import CrawlerAgent  # noqa: E402
from tiktok_ecommerce.categories.registry import get_category  # noqa: E402
from tiktok_ecommerce.common.llm import create_embedding_fn, create_llm  # noqa: E402
from tiktok_ecommerce.config import get_settings  # noqa: E402
from tiktok_ecommerce.crawlers.factory import get_product_crawler  # noqa: E402
from tiktok_ecommerce.rag.factory import get_vector_store  # noqa: E402
from tiktok_ecommerce.rag.retriever import Retriever  # noqa: E402


def main() -> int:
    s = get_settings()
    category = get_category(s.pipeline.default_category)
    print("=" * 64)
    print(f"第五步 评论RAG分析 | 后端 = {s.rag.backend} | 品类 = {category.display_name}")
    print("=" * 64)

    llm = create_llm(s)
    embedding_fn = create_embedding_fn(s)
    store = get_vector_store(s)

    # 1. 采集 + 切片入库（已有数据则跳过）
    if store.count() == 0:
        crawler = get_product_crawler(s, category=s.pipeline.default_category)
        agent = CrawlerAgent(
            crawler, store, embedding_fn,
            chunk_size=s.pipeline.chunk_size,
            chunk_overlap=s.pipeline.chunk_overlap,
        )
        result = agent.run({"query": "ボックスシーツ 綿100%", "region": "JP"})
        print(f"已采集并入库 {len(result.get('products', []))} 个商品，"
              f"知识库共 {store.count()} 条/个\n")
    else:
        print(f"知识库已有 {store.count()} 条数据，跳过入库。\n")

    # 2. 分析 Agent：多主题检索 → LLM → 带洞察的报告
    retriever = Retriever(
        store, embedding_fn,
        top_k=s.milvus.top_k,
        score_threshold=s.milvus.score_threshold,
    )
    analyzer = AnalyzerAgent(retriever, llm=llm, category=category)

    products = crawler_products(s)
    out = analyzer.run({"products": products, "region": "JP"})
    report = out.get("report")
    if not report:
        print("分析失败：", out.get("error"))
        return 1

    print(report.to_markdown())
    print("\n" + "=" * 64)
    print("说明：insights.evidence 逐字来自检索资料中的真实评论（防幻觉）。")
    print("=" * 64)
    return 0


def crawler_products(s) -> list:
    """直接搜索样本商品（不重复入库），供分析 Agent 使用。"""
    crawler = get_product_crawler(s, category=s.pipeline.default_category)
    return crawler.search_products("ボックスシーツ 綿100%", limit=2)


if __name__ == "__main__":
    raise SystemExit(main())
