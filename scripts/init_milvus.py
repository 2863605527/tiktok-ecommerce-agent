"""初始化脚本：检查 Milvus 连通性并准备集合。

用法：
    python scripts/init_milvus.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tiktok_ecommerce.common.logging import setup_logging  # noqa: E402
from tiktok_ecommerce.config import get_settings  # noqa: E402
from tiktok_ecommerce.rag.milvus_store import MilvusStore  # noqa: E402


def main() -> None:
    setup_logging()
    settings = get_settings()
    store = MilvusStore(
        host=settings.milvus.host,
        port=settings.milvus.port,
        collection_name=settings.milvus.collection,
        dim=settings.milvus.embedding_dim,
    )
    print(f"✅ Milvus 连接正常，集合 {settings.milvus.collection} 就绪，当前 {store.count()} 条数据")


if __name__ == "__main__":
    main()
