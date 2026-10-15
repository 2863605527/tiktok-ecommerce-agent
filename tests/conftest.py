"""pytest 共享夹具：内存向量库、Mock LLM 等。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# 保证 import tiktok_ecommerce（src layout 已通过 pip install -e 安装，此处兜底）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class FakeVectorStore:
    """测试用内存向量库（实现 VectorStore 接口的最小替代）。"""

    def __init__(self):
        self._items: list[dict[str, Any]] = []

    def insert(self, texts, metadatas=None, *, embedding_fn=None) -> int:
        if metadatas is None:
            metadatas = [{} for _ in texts]
        for t, m in zip(texts, metadatas):
            self._items.append({"text": t, "metadata": m, "score": 1.0})
        return len(texts)

    def search(self, query_vector, top_k=5) -> list[dict[str, Any]]:
        return self._items[:top_k]

    def search_by_text(self, query, top_k=5, *, embedding_fn=None) -> list[dict[str, Any]]:
        """文本检索（模板方法）：测试库不做真实向量化，直接返回全部。"""
        return self.search(query_vector=[0.0] * 3, top_k=top_k)

    def count(self) -> int:
        return len(self._items)

    def drop(self) -> None:
        self._items.clear()


class FakeLLM:
    """测试用 LLM：按 prompt 关键字返回固定 JSON，不触发网络。"""

    def __init__(self, payload: str):
        self.payload = payload

    def invoke(self, prompt: str):
        class _Resp:
            content = ""

        resp = _Resp()
        resp.content = self.payload
        return resp


@pytest.fixture
def fake_store() -> FakeVectorStore:
    return FakeVectorStore()


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM('{"summary": "测试", "pros": [], "cons": [], "market_hot": "中",'
                   ' "competition": "", "risks": [], "suggestion": "可试销",'
                   ' "keywords": ["耳机", "earbuds"]}')


@pytest.fixture(autouse=True)
def _reset_register_throttle():
    """每个测试前清空注册限流计数（多测试模块共用同一进程同一 IP，防止累计误拦）。"""
    from tiktok_ecommerce.api.v1.auth import reset_register_throttle

    reset_register_throttle()
    yield
    reset_register_throttle()
