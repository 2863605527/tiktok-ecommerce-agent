"""文本切片（Chunking）：把长文本切成带重叠的小块，用于向量化入库。

为什么需要切片（RAG 基础）：
- 向量模型有最大长度，整页文本无法直接 embedding
- 块太大 → 检索召回不精准、主题混杂；块太小 → 语义不完整
- 块之间保留 overlap（重叠），避免把一句话/一个观点硬切成两半导致语义丢失

策略：在目标长度内尽量靠后地寻找自然边界（段落 > 句子 > 标点 > 空格），
找不到再硬切，兼顾中日英文本（中文/日文按字符计长）。
"""
from __future__ import annotations

# 优先级从高到低的自然分隔符（覆盖中日英）
_SEPARATORS = ["\n\n", "\n", "。", "．", ".", "！", "？", "!", "?", "、", "，", ",", " "]


def split_text(text: str, chunk_size: int = 300, overlap: int = 30) -> list[str]:
    """把长文本切成带重叠的块。

    Args:
        text: 原始文本
        chunk_size: 每块目标字符数
        overlap: 相邻块重叠字符数（< chunk_size）
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须为正整数")
    overlap = max(0, min(overlap, chunk_size - 1))

    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            boundary = _find_boundary(text, start, end)
            if boundary is not None and boundary > start:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        # 下一块回退 overlap，保证上下文连续；至少前进 1 字符防止死循环
        start = max(end - overlap, start + 1)
    return chunks


def _find_boundary(text: str, start: int, end: int) -> int | None:
    """在 [start, end] 内、尽量靠后地寻找自然分隔符位置（返回分隔符之后的下标）。"""
    window = text[start:end]
    for sep in _SEPARATORS:
        idx = window.rfind(sep)
        # 要求切点不要太靠前（至少吃掉一半目标长度），否则块过小
        if idx >= chunk_min_len(end - start):
            return start + idx + len(sep)
    return None


def chunk_min_len(chunk_size: int) -> int:
    """切点至少应覆盖的长度（块的一半），避免碎块。"""
    return max(1, chunk_size // 2)


def split_documents(
    texts: list[str],
    metadatas: list[dict] | None = None,
    chunk_size: int = 300,
    overlap: int = 30,
) -> tuple[list[str], list[dict]]:
    """批量切片，切片后元数据自动补 chunk_index（与原文本对齐）。"""
    if metadatas is None:
        metadatas = [{} for _ in texts]
    out_texts: list[str] = []
    out_metas: list[dict] = []
    for i, (text, meta) in enumerate(zip(texts, metadatas)):
        pieces = split_text(text, chunk_size, overlap)
        for j, piece in enumerate(pieces):
            m = dict(meta)
            m["chunk_index"] = j
            m["source_index"] = i
            out_texts.append(piece)
            out_metas.append(m)
    return out_texts, out_metas
