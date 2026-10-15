"""Milvus 向量库实现。

Milvus 核心概念：
- Collection ≈ MySQL 的表；Field ≈ 列
- 检索 = 把 query 向量化，在向量空间找最近的 N 条
"""
from __future__ import annotations

import json
import warnings
from collections.abc import Callable
from typing import Any

# PyMilvus 3.0 的 ORM 风格 API（Collection/utility/connections）将在 3.1 移除、
# 官方建议改用 MilvusClient；当前版本功能完全正常，先屏蔽其弃用告警保持日志干净。
# 技术债：后续可平滑迁移到 MilvusClient（search 返回结构需同步适配）。
warnings.filterwarnings("ignore", message=".*ORM-style PyMilvus API.*")

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from tiktok_ecommerce.common.exceptions import RAGError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.rag.base import VectorStore

logger = get_logger(__name__)


class MilvusStore(VectorStore):
    """基于 Milvus 的向量库。"""

    def __init__(self, host: str, port: int, collection_name: str, dim: int):
        self.collection_name = collection_name
        self.dim = dim
        try:
            connections.connect("default", host=host, port=str(port))
        except Exception as e:
            raise RAGError(f"连接 Milvus 失败 {host}:{port}，是否已启动？", detail=str(e)) from e

        if utility.has_collection(collection_name):
            self._collection = Collection(collection_name)
            logger.info("已连接集合: %s", collection_name)
        else:
            self._collection = self._create_collection(collection_name, dim)
            logger.info("已创建集合: %s (dim=%d)", collection_name, dim)

    @staticmethod
    def _create_collection(name: str, dim: int) -> Collection:
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=dim),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=4096),
            FieldSchema(name="metadata", dtype=DataType.JSON),
        ]
        schema = CollectionSchema(fields, description="TikTok 商品知识库")
        collection = Collection(name, schema)
        collection.create_index(
            "vector",
            {"index_type": "IVF_FLAT", "metric_type": "COSINE", "params": {"nlist": 128}},
        )
        return collection

    def insert(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        *,
        embedding_fn: Callable[[str], list[float]],
    ) -> int:
        if not texts:
            return 0
        if metadatas is None:
            metadatas = [{} for _ in texts]
        try:
            vectors = [embedding_fn(t) for t in texts]
            data = [vectors, texts, [json.dumps(m, ensure_ascii=False) for m in metadatas]]
            self._collection.insert(data)
            self._collection.flush()
        except Exception as e:
            raise RAGError("向量入库失败", detail=str(e)) from e
        logger.info("已插入 %d 条 -> %s", len(texts), self.collection_name)
        return len(texts)

    def search(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        try:
            self._collection.load()
            results = self._collection.search(
                data=[query_vector],
                anns_field="vector",
                param={"metric_type": "COSINE", "params": {"nprobe": 16}},
                limit=top_k,
                output_fields=["text", "metadata"],
            )
        except Exception as e:
            raise RAGError("向量检索失败", detail=str(e)) from e

        hits = []
        for hit in results[0]:
            hits.append({
                "text": hit.entity.get("text"),
                "metadata": hit.entity.get("metadata"),
                "score": round(hit.score, 4),
            })
        return hits

    def count(self) -> int:
        self._collection.load()
        return self._collection.num_entities

    def drop(self) -> None:
        if utility.has_collection(self.collection_name):
            utility.drop_collection(self.collection_name)
            logger.warning("已删除集合: %s", self.collection_name)
