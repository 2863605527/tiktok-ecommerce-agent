"""RAGFlow 连通性自检：验证地址/API Key，列出知识库，不存在则创建目标知识库。

运行（项目根目录）：
    .venv\\Scripts\\python scripts\\check_ragflow.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tiktok_ecommerce.config import get_settings  # noqa: E402
from tiktok_ecommerce.crawlers.http import HttpClient  # noqa: E402
from tiktok_ecommerce.rag.ragflow_store import RAGFlowStore  # noqa: E402


def main() -> int:
    s = get_settings()
    print("=" * 60)
    print(f"RAGFlow 地址: {s.rag.base_url} | 目标知识库: {s.rag.dataset}")
    print("=" * 60)

    client = HttpClient(min_interval=0.1, timeout=20, max_retries=1)
    store = RAGFlowStore(
        client,
        api_base=s.rag.base_url,
        api_key=s.rag.api_key,
        dataset_name=s.rag.dataset,
        similarity_threshold=s.rag.similarity_threshold,
        vector_weight=s.rag.vector_weight,
    )

    # 1. 列出已有知识库
    resp = client.get_json(
        f"{s.rag.base_url}/api/v1/datasets",
        params={"page": 1, "page_size": 50},
        headers=store._auth(),
    )
    code = resp.get("code", 0)
    if code not in (0, "0"):
        print(f"[FAIL] 连接/鉴权失败: code={code} {resp.get('message')}")
        print("       请检查 RAG_BASE_URL / RAG_API_KEY，以及 RAGFlow 是否已启动。")
        return 1

    data = resp.get("data") or []
    items = data if isinstance(data, list) else data.get("docs", [])
    print(f"[PASS] 连接成功，当前共有 {len(items)} 个知识库：")
    for ds in items:
        print(f"       - {ds.get('name')}  (id={ds.get('id')})")

    # 2. 确保目标知识库存在
    ds_id = store.ensure_dataset()
    print(f"[PASS] 目标知识库就绪: {s.rag.dataset} (id={ds_id})")
    print("\nRAGFlow 可用。第四步可在 .env 设置 RAG_BACKEND=ragflow 切换到托管检索。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
