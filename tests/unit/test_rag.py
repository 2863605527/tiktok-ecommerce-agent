"""检索层单元测试：内存库余弦检索、Retriever 端到端、RAGFlow 适配、工厂（全部离线）。"""
import json
from types import SimpleNamespace

import pytest

from tiktok_ecommerce.common.exceptions import RAGError
from tiktok_ecommerce.config import get_settings
from tiktok_ecommerce.rag.factory import get_vector_store
from tiktok_ecommerce.rag.memory_store import InMemoryStore, cosine_similarity
from tiktok_ecommerce.rag.ragflow_store import RAGFlowStore
from tiktok_ecommerce.rag.retriever import Retriever, _as_dict

# 小型词袋向量（确定性，不依赖真实模型），维度 = 词表大小
_VOCAB = ["纯棉", "床笠", "冷感", "床垫", "発送", "縮み", "ゴム"]


def bag_embedding(text: str) -> list[float]:
    return [1.0 if w in text else 0.0 for w in _VOCAB]


# ---------- 余弦相似度 ----------
class TestCosine:
    def test_basic(self):
        assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)
        assert cosine_similarity([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_dim_mismatch(self):
        with pytest.raises(RAGError):
            cosine_similarity([1, 0, 0], [1, 0])


# ---------- 内存向量库 ----------
class TestInMemoryStore:
    def test_insert_count_drop(self):
        store = InMemoryStore()
        n = store.insert(["纯棉床笠", "冷感床垫"], [{"title": "A"}, {"title": "B"}],
                         embedding_fn=bag_embedding)
        assert n == 2
        assert store.count() == 2
        store.drop()
        assert store.count() == 0

    def test_search_ranking(self):
        store = InMemoryStore()
        store.insert(
            ["纯棉床笠 肌触りが良い", "冷感床垫 夏用", "発送が早い"],
            [{"title": "床笠"}, {"title": "冷感"}, {"title": "物流"}],
            embedding_fn=bag_embedding,
        )
        hits = store.search(bag_embedding("纯棉床笠がほしい"), top_k=3)
        assert "纯棉床笠" in hits[0]["text"]  # 最相关排第一
        assert hits[0]["score"] > hits[1]["score"]  # 按相似度降序
        assert hits[0]["score"] == pytest.approx(1.0)  # query 与床笠文档同向

    def test_dim_mismatch_on_insert(self):
        store = InMemoryStore()
        store.insert(["纯棉床笠"], embedding_fn=bag_embedding)
        with pytest.raises(RAGError):
            store.insert(["其它维度"], embedding_fn=lambda t: [1.0, 2.0])

    def test_empty_search(self):
        assert InMemoryStore().search(bag_embedding("x"), top_k=3) == []


# ---------- Retriever 端到端 ----------
class TestRetriever:
    def _build(self):
        store = InMemoryStore()
        store.insert(
            ["纯棉床笠は肌触りが良くゴムでズレない", "冷感床垫は夏にひんやり", "発送がとても早い"],
            [{"title": "綿ボックスシーツ"}, {"title": "冷感敷きパッド"}, {"title": "物流"}],
            embedding_fn=bag_embedding,
        )
        return Retriever(store, bag_embedding, top_k=3, score_threshold=0.0)

    def test_retrieve_ranking(self):
        hits = self._build().retrieve("纯棉床笠")
        assert "纯棉床笠" in hits[0]["text"]

    def test_threshold_filters(self):
        retriever = self._build()
        retriever.score_threshold = 1.01  # 余弦最大为 1，全部被过滤
        assert retriever.retrieve("纯棉床笠") == []

    def test_build_context(self):
        ctx = self._build().build_context("ゴム ズレ 床笠")
        assert "[资料1]" in ctx
        assert "綿ボックスシーツ" in ctx

    def test_metadata_dict_or_json(self):
        assert _as_dict('{"a": 1}') == {"a": 1}
        assert _as_dict({"b": 2}) == {"b": 2}
        assert _as_dict("not-json") == {}
        assert _as_dict(None) == {}


# ---------- RAGFlow 适配（mock HTTP）----------
class FakeRagClient:
    """模拟 RAGFlow HTTP：按 method+url 返回预设响应，并记录调用。"""

    def __init__(self, existing=None, chunks=None, list_code=0):
        self.existing = existing
        self.chunks = chunks or []
        self.list_code = list_code
        self.created_body = None
        self.uploaded: list = []
        self.upload_resp: dict = {"code": 0, "data": [{"id": "doc_new_1", "name": "p100.md"}]}
        self.parse_body = None
        self.retrieval_body = None

    def get_json(self, url, params=None, headers=None, json_body=None, method="GET"):
        if method == "GET" and url.endswith("/api/v1/datasets"):
            if self.list_code != 0:
                return {"code": self.list_code, "message": "authentication failed"}
            return {"code": 0, "data": self.existing or []}
        if method == "POST" and url.endswith("/api/v1/datasets"):
            self.created_body = json_body
            return {"code": 0, "data": {"id": "ds_new"}}
        if method == "POST" and url.endswith("/documents/parse"):
            self.parse_body = json_body
            return {"code": 0, "data": {"success_count": len(json_body["document_ids"])}}
        if method == "POST" and url.endswith("/api/v1/retrieval"):
            self.retrieval_body = json_body
            return {"code": 0, "data": {"chunks": self.chunks}}
        if method == "GET" and "/documents" in url:
            return {"code": 0, "data": {"total": 7}}
        return {"code": 0, "data": {}}

    def post_file(self, url, *, files, data=None, headers=None):
        self.uploaded.append((url, files.get("file"), data))
        return self.upload_resp


class TestRAGFlowStore:
    def test_reuse_existing_dataset(self):
        client = FakeRagClient(existing=[{"id": "ds1", "name": "tiktok_bedding_kb"}])
        store = RAGFlowStore(client, "http://localhost", "k", "tiktok_bedding_kb")
        assert store.ensure_dataset() == "ds1"
        assert client.created_body is None  # 已存在则不创建

    def test_create_dataset_when_missing(self):
        client = FakeRagClient(existing=[])
        store = RAGFlowStore(client, "http://localhost", "k", "tiktok_bedding_kb")
        assert store.ensure_dataset() == "ds_new"
        assert client.created_body["name"] == "tiktok_bedding_kb"

    def test_insert_uploads_markdown(self):
        client = FakeRagClient(existing=[{"id": "ds1", "name": "kb"}])
        store = RAGFlowStore(client, "http://localhost", "k", "kb")
        metas = [
            {"title": "床笠", "product_id": "p100", "source_type": "description"},
            {"title": "床笠", "product_id": "p100", "source_type": "review"},
        ]
        n = store.insert(["商品描述文本", "评论文本"], metas)
        assert n == 2
        assert len(client.uploaded) == 1
        url, file_tuple, form = client.uploaded[0]
        filename, content_bytes, mime = file_tuple
        assert filename == "p100.md"
        content = content_bytes.decode("utf-8")
        assert "商品描述文本" in content
        assert "description" in content and "review" in content  # 分节标注来源
        assert form["parser_id"] == "naive"
        # 上传后自动触发解析（v0.27 必需步骤）
        assert client.parse_body is not None
        assert client.parse_body["document_ids"] == ["doc_new_1"]

    def test_insert_without_doc_id_skips_parse(self):
        # 上传响应没带文档 id 时不报错，只告警（不触发解析）
        client = FakeRagClient(existing=[{"id": "ds1", "name": "kb"}])
        client.upload_resp = {"code": 0, "data": {}}
        store = RAGFlowStore(client, "http://localhost", "k", "kb")
        n = store.insert(["文本"], [{"title": "t", "product_id": "p", "source_type": "review"}])
        assert n == 1
        assert client.parse_body is None

    def test_retrieval_mapping(self):
        client = FakeRagClient(
            existing=[{"id": "ds1", "name": "kb"}],
            chunks=[{"content": "肌触りが良い", "document_name": "p100.md",
                     "similarity": 0.91, "document_id": "doc1"}],
        )
        store = RAGFlowStore(client, "http://localhost", "k", "kb")
        hits = store.search_by_text("肌触りはどう？", top_k=5)
        assert len(hits) == 1
        assert hits[0]["text"] == "肌触りが良い"
        assert hits[0]["score"] == 0.91
        assert hits[0]["metadata"]["document_name"] == "p100.md"
        assert client.retrieval_body["question"] == "肌触りはどう？"
        assert client.retrieval_body["dataset_ids"] == ["ds1"]

    def test_vector_search_not_supported(self):
        client = FakeRagClient(existing=[{"id": "ds1", "name": "kb"}])
        store = RAGFlowStore(client, "http://localhost", "k", "kb")
        with pytest.raises(RAGError):
            store.search([0.1, 0.2], top_k=3)

    def test_count(self):
        client = FakeRagClient(existing=[{"id": "ds1", "name": "kb"}])
        store = RAGFlowStore(client, "http://localhost", "k", "kb")
        assert store.count() == 7

    def test_business_error_raises(self):
        client = FakeRagClient(list_code=102)
        store = RAGFlowStore(client, "http://localhost", "k", "kb")
        with pytest.raises(RAGError):
            store.ensure_dataset()

    def test_missing_key_raises(self):
        with pytest.raises(RAGError):
            RAGFlowStore(FakeRagClient(), "http://localhost", "", "kb")


# ---------- 向量库工厂 ----------
def _cfg(backend: str, **rag):
    return SimpleNamespace(rag=SimpleNamespace(backend=backend, **rag))


class TestVectorStoreFactory:
    def test_memory_backend(self):
        store = get_vector_store(_cfg("memory"))
        assert isinstance(store, InMemoryStore)

    def test_ragflow_without_key_raises(self):
        cfg = _cfg("ragflow", base_url="http://localhost", api_key="",
                   dataset="kb", similarity_threshold=0.2, vector_weight=0.3)
        with pytest.raises(RAGError):
            get_vector_store(cfg)

    def test_ragflow_backend_creates_store(self):
        cfg = _cfg("ragflow", base_url="http://localhost", api_key="test-key",
                   dataset="kb", similarity_threshold=0.2, vector_weight=0.3)
        store = get_vector_store(cfg)
        assert isinstance(store, RAGFlowStore)

    def test_unknown_backend_raises(self):
        with pytest.raises(RAGError):
            get_vector_store(_cfg("xyz"))
