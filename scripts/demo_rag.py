"""第四步检索闭环演示：本地样本商品 → 切片 → bge-m3 向量化 → 入库 → 日语语义检索。

后端由 .env 的 RAG_BACKEND 决定：
    milvus ：自建 Milvus（需先 docker compose up -d milvus）
    memory ：内存库（无需 Docker，进程退出即清空）
    ragflow：托管 RAGFlow（上传后异步解析，首次检索可能需要等待解析完成）

运行（项目根目录）：
    .venv\\Scripts\\python scripts\\demo_rag.py
临时切换后端（PowerShell）：
    $env:RAG_BACKEND="memory"; .venv\\Scripts\\python scripts\\demo_rag.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tiktok_ecommerce.agents.crawler_agent import CrawlerAgent  # noqa: E402
from tiktok_ecommerce.common.llm import create_embedding_fn  # noqa: E402
from tiktok_ecommerce.config import get_settings  # noqa: E402
from tiktok_ecommerce.crawlers.factory import get_product_crawler  # noqa: E402
from tiktok_ecommerce.rag.factory import get_vector_store  # noqa: E402
from tiktok_ecommerce.rag.retriever import Retriever  # noqa: E402

# 用日语自然语言提问，验证"语义检索"而非关键词匹配
QUESTIONS = [
    "洗濯したあと縮みますか？",      # 洗后缩水吗
    "肌触りや寝心地はどうですか？",   # 触感/睡感如何
    "ゴムがズレたりしませんか？",    # 橡皮筋会移位吗
]


def main() -> int:
    s = get_settings()
    print("=" * 64)
    print(f"检索后端 = {s.rag.backend} | 向量模型 = {s.llm.embedding_model}")
    print("=" * 64)

    embedding_fn = create_embedding_fn(s)
    store = get_vector_store(s)

    # 1. 采集 + 切片 + 向量化入库（库里已有数据则跳过，避免重复）
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
        print(f"知识库已有 {store.count()} 条数据，跳过入库（避免重复）。\n")

    # 2. 日语语义检索
    retriever = Retriever(
        store, embedding_fn,
        top_k=s.milvus.top_k,
        score_threshold=s.milvus.score_threshold,
    )
    for q in QUESTIONS:
        print(f"【提问】{q}")
        hits = retriever.retrieve(q, top_k=3)
        if not hits:
            print("   （无命中；RAGFlow 可能仍在异步解析文档，请稍后重试）")
        for h in hits:
            text = h["text"].replace("\n", " ")
            print(f"   [{h['score']:.3f}] {text[:60]}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
