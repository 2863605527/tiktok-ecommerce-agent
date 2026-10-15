"""内存向量库：纯 Python 余弦相似度，零外部依赖。

用途：
- 单元测试 / CI：不依赖 Milvus 进程即可验证检索链路
- 本地演示：没装 Docker 时用 RAG_BACKEND=memory 跑通全流程
- 与 MilvusStore / RAGFlowStore 实现同一套 VectorStore 接口，可无缝替换

注意：数据只在内存，进程退出即清空，不用于生产。
"""
from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from tiktok_ecommerce.common.exceptions import RAGError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.rag.base import VectorStore

logger = get_logger(__name__)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度（与 Milvus COSINE 度量口径一致）。"""
    if len(a) != len(b):
        raise RAGError(f"向量维度不一致: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryStore(VectorStore):
    """进程内向量库。"""

    def __init__(self):
        self._vectors: list[list[float]] = []
        self._texts: list[str] = []
        self._metadatas: list[dict[str, Any]] = []

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
        for text, meta in zip(texts, metadatas):
            vec = embedding_fn(text)
            if self._vectors and len(vec) != len(self._vectors[0]):
                raise RAGError(
                    f"向量维度与库内不一致: {len(vec)} vs {len(self._vectors[0])}"
                )
            self._vectors.append(vec)
            self._texts.append(text)
            self._metadatas.append(meta)
        logger.info("内存库插入 %d 条，当前共 %d 条", len(texts), len(self._texts))
        return len(texts)

    def search(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        if not self._vectors:
            return []
        scored = [
            (cosine_similarity(query_vector, vec), i)
            for i, vec in enumerate(self._vectors)
        ]
        scored.sort(key=lambda x: -x[0])
        hits = []
        for score, i in scored[:top_k]:
            hits.append({
                "text": self._texts[i],
                "metadata": self._metadatas[i],
                "score": round(score, 4),
            })
        return hits

    def count(self) -> int:
        return len(self._texts)

    def drop(self) -> None:
        self._vectors.clear()
        self._texts.clear()
        self._metadatas.clear()
        logger.warning("内存库已清空")
