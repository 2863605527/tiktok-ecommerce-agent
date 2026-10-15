"""向量库工厂：按 RAG_BACKEND 创建检索后端（可插拔）。

    RAG_BACKEND=milvus  → 自建 Milvus（默认，原理透明、生产）
    RAG_BACKEND=ragflow → 托管 RAGFlow（工程提效、带文档管理）
    RAG_BACKEND=memory  → 进程内内存库（无 Docker / 单元测试 / 快速演示）

选型考量：自建 Milvus 掌握向量检索全链路原理，RAGFlow 作为工程化提效方案，
两者实现同一 VectorStore 接口、配置切换，业务层（Retriever/Agent）零改动。
"""
from __future__ import annotations

from tiktok_ecommerce.common.exceptions import RAGError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.config import Settings
from tiktok_ecommerce.crawlers.http import HttpClient
from tiktok_ecommerce.rag.base import VectorStore
from tiktok_ecommerce.rag.memory_store import InMemoryStore
from tiktok_ecommerce.rag.milvus_store import MilvusStore
from tiktok_ecommerce.rag.ragflow_store import RAGFlowStore

logger = get_logger(__name__)


def get_vector_store(settings: Settings) -> VectorStore:
    """按配置构造向量库。"""
    backend = (settings.rag.backend or "milvus").lower()

    if backend == "milvus":
        logger.info("检索后端 = 自建 Milvus %s:%s", settings.milvus.host, settings.milvus.port)
        return MilvusStore(
            host=settings.milvus.host,
            port=settings.milvus.port,
            collection_name=settings.milvus.collection,
            dim=settings.milvus.embedding_dim,
        )

    if backend == "memory":
        logger.info("检索后端 = 内存库（进程内，退出即清空）")
        return InMemoryStore()

    if backend == "ragflow":
        if not settings.rag.api_key:
            raise RAGError(
                "检索后端为 ragflow，但未配置 RAG_API_KEY",
                detail="请在 .env 设置 RAG_BASE_URL 与 RAG_API_KEY",
            )
        logger.info("检索后端 = RAGFlow %s（知识库 %s）",
                    settings.rag.base_url, settings.rag.dataset)
        client = HttpClient(min_interval=0.1, timeout=30, max_retries=2)
        return RAGFlowStore(
            client,
            api_base=settings.rag.base_url,
            api_key=settings.rag.api_key,
            dataset_name=settings.rag.dataset,
            similarity_threshold=settings.rag.similarity_threshold,
            vector_weight=settings.rag.vector_weight,
        )

    raise RAGError(f"未知检索后端: {backend}", detail="可选: milvus | ragflow | memory")
