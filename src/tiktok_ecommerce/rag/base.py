"""向量库接口抽象：支持切换 Milvus / RAGFlow / 内存库等实现。

设计要点：
- search() 面向向量（自建库：客户端先 embedding 再传向量）
- search_by_text() 面向原始问题文本：默认实现 = embedding_fn(query) + search()；
  托管式检索（如 RAGFlow，内部自带 embedding）可覆写该方法直接传文本
"""
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class VectorStore(ABC):
    """向量数据库统一接口。"""

    @abstractmethod
    def insert(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        *,
        embedding_fn: Callable[[str], list[float]],
    ) -> int:
        """批量写入文本（自建库先向量化再入库；托管库可忽略 embedding_fn）。"""

    @abstractmethod
    def search(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        """向量检索，返回 [{text, metadata, score}, ...]。"""

    def search_by_text(
        self,
        query: str,
        top_k: int = 5,
        *,
        embedding_fn: Callable[[str], list[float]] | None = None,
    ) -> list[dict[str, Any]]:
        """文本检索（模板方法）：默认把问题向量化后走 search；托管库可覆写。"""
        if embedding_fn is None:
            raise NotImplementedError(
                f"{type(self).__name__} 未提供 embedding_fn，且未实现文本直查"
            )
        return self.search(embedding_fn(query), top_k=top_k)

    @abstractmethod
    def count(self) -> int:
        """当前库中条数。"""

    @abstractmethod
    def drop(self) -> None:
        """清空集合（危险操作）。"""
