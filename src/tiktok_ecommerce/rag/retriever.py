"""检索器：问题 → 向量检索 → 相关性过滤 → 上下文组装。

防幻觉关键：
- 检索结果按分数阈值过滤，低质量片段不进入 LLM 上下文
- 上下文明确标注来源，提示模型"只能依据资料回答"
"""
import json
from collections.abc import Callable
from typing import Any

from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.rag.base import VectorStore

logger = get_logger(__name__)


def _as_dict(meta: Any) -> dict:
    """metadata 可能是 dict（内存库/RAGFlow）或 JSON 字符串（部分 Milvus 版本）。"""
    if isinstance(meta, dict):
        return meta
    if isinstance(meta, str) and meta.strip():
        try:
            loaded = json.loads(meta)
            return loaded if isinstance(loaded, dict) else {}
        except ValueError:
            return {}
    return {}


class Retriever:
    """基于向量库的检索器。"""

    def __init__(
        self,
        store: VectorStore,
        embedding_fn: Callable[[str], list[float]],
        top_k: int = 5,
        score_threshold: float = 0.0,
    ):
        self.store = store
        self.embedding_fn = embedding_fn
        self.top_k = top_k
        self.score_threshold = score_threshold

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict[str, Any]]:
        """检索 + 过滤，返回 [{text, metadata, score}, ...]。

        统一走 search_by_text：自建库内部会向量化，RAGFlow 直接托管检索。
        """
        k = top_k or self.top_k
        hits = self.store.search_by_text(query, k, embedding_fn=self.embedding_fn)
        filtered = [h for h in hits if h.get("score", 0) >= self.score_threshold]
        logger.info("检索 '%s' -> %d 条，阈值过滤后 %d 条", query, len(hits), len(filtered))
        return filtered

    def build_context(self, query: str, top_k: int | None = None) -> str:
        """组装成给 LLM 的上下文文本（标注来源，约束模型只依据资料回答）。"""
        hits = self.retrieve(query, top_k)
        if not hits:
            return ""
        blocks = []
        for i, h in enumerate(hits, 1):
            meta = _as_dict(h.get("metadata"))
            title = meta.get("title") or meta.get("document_name") or "未知来源"
            blocks.append(f"[资料{i}] 标题：{title}\n内容：{h['text']}")
        return "\n---\n".join(blocks)
