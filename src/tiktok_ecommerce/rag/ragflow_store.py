"""RAGFlow 向量/知识库实现（托管式 RAG，与自建 Milvus 平级、可配置切换）。

与自建 Milvus 的区别（"双实现"权衡）：
- Milvus：自己切片 → 自己调 embedding → 自己写向量 → 自己检索，原理透明、可控
- RAGFlow：上传文档后由平台负责解析/切片/向量化/混合检索（含关键词权重），
  工程上更省事、带文档管理与解析可视化，但 embedding 与分块策略由平台托管

本类把 RAGFlow 适配到统一 VectorStore 接口：
- insert：把一个商品的描述+评论聚合成一个 Markdown 文档上传（RAGFlow 内部 embedding）
- search_by_text：走 RAGFlow /retrieval 混合检索（覆写默认向量检索）
- search(向量)：RAGFlow 不接受外部向量，直接调用会明确报错

RAGFlow HTTP API（v1，Authorization: Bearer <API_KEY>）：
- GET    /api/v1/datasets                 列出知识库
- POST   /api/v1/datasets                 创建知识库
- POST   /api/v1/datasets/{id}/documents  上传文档（multipart）
- POST   /api/v1/retrieval                检索
- DELETE /api/v1/datasets                 删除知识库
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from tiktok_ecommerce.common.exceptions import RAGError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.crawlers.http import HttpClient
from tiktok_ecommerce.rag.base import VectorStore

logger = get_logger(__name__)


class RAGFlowStore(VectorStore):
    """基于 RAGFlow 的托管知识库。"""

    def __init__(
        self,
        client: HttpClient,
        api_base: str,
        api_key: str,
        dataset_name: str = "tiktok_bedding_kb",
        similarity_threshold: float = 0.2,
        vector_weight: float = 0.3,
    ):
        if not api_key:
            raise RAGError("未配置 RAGFlow API Key（RAG_RAGFLOW_API_KEY）")
        self.client = client
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.dataset_name = dataset_name
        self.similarity_threshold = similarity_threshold
        self.vector_weight = vector_weight
        self._dataset_id: str | None = None

    # ---------- 基础 ----------
    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _unwrap(self, resp: dict, action: str) -> Any:
        """RAGFlow 统一返回 {code:0, data:...}；非 0 视为业务失败。"""
        code = resp.get("code", 0)
        if code not in (0, "0"):
            raise RAGError(
                f"RAGFlow {action}失败: code={code}",
                detail=str(resp.get("message") or resp)[:300],
            )
        return resp.get("data")

    def ensure_dataset(self) -> str:
        """返回知识库 ID，不存在则创建（懒加载，避免构造时即连接）。"""
        if self._dataset_id:
            return self._dataset_id
        resp = self.client.get_json(
            f"{self.api_base}/api/v1/datasets",
            params={"page": 1, "page_size": 100},
            headers=self._auth(),
        )
        data = self._unwrap(resp, "查询知识库")
        items = data if isinstance(data, list) else (data or {}).get("docs", [])
        for ds in items:
            if isinstance(ds, dict) and ds.get("name") == self.dataset_name:
                self._dataset_id = ds.get("id")
                logger.info("复用 RAGFlow 知识库: %s (%s)", self.dataset_name, self._dataset_id)
                return self._dataset_id  # type: ignore[return-value]

        # 说明：部分 RAGFlow 版本建库接口仅接受 name（language/chunk_method 传了会报
        # code=101 "Extra inputs are not permitted"），分块方式与模型沿用系统默认即可。
        created = self.client.get_json(
            f"{self.api_base}/api/v1/datasets",
            method="POST",
            json_body={"name": self.dataset_name},
            headers=self._auth(),
        )
        cdata = self._unwrap(created, "创建知识库")
        if isinstance(cdata, list) and cdata:
            self._dataset_id = cdata[0].get("id")
        elif isinstance(cdata, dict):
            self._dataset_id = cdata.get("id")
        if not self._dataset_id:
            raise RAGError("RAGFlow 创建知识库未返回 id", detail=str(cdata))
        logger.info("已创建 RAGFlow 知识库: %s (%s)", self.dataset_name, self._dataset_id)
        return self._dataset_id

    # ---------- VectorStore 接口 ----------
    def insert(
        self,
        texts: list[str],
        metadatas: list[dict[str, Any]] | None = None,
        *,
        embedding_fn: Callable[[str], list[float]] | None = None,
    ) -> int:
        """把一批同商品文本聚合为一个 Markdown 文档上传（embedding 由 RAGFlow 完成）。"""
        if not texts:
            return 0
        if metadatas is None:
            metadatas = [{} for _ in texts]
        dataset_id = self.ensure_dataset()

        title = metadatas[0].get("title", "product")
        product_id = str(metadatas[0].get("product_id") or "")
        sections = []
        for idx, (text, meta) in enumerate(zip(texts, metadatas), 1):
            kind = meta.get("source_type", "内容")
            sections.append(f"### {idx}. {kind}\n{text}")
        content = f"# {title}\n\n" + "\n\n".join(sections)

        digest = hashlib.md5(content.encode("utf-8")).hexdigest()[:8]
        filename = f"{product_id or digest}.md"
        files = {"file": (filename, content.encode("utf-8"), "text/markdown")}
        resp = self.client.post_file(
            f"{self.api_base}/api/v1/datasets/{dataset_id}/documents",
            files=files,
            data={"parser_id": "naive"},
            headers=self._auth(),
        )
        data = self._unwrap(resp, "上传文档")
        logger.info("RAGFlow 上传文档 %s（%d 个片段）", filename, len(texts))

        # 上传后必须显式触发解析（RAGFlow 不会自动解析；v0.27 接口为 /documents/parse）
        doc_ids = self._extract_doc_ids(data)
        if doc_ids:
            self._start_parse(dataset_id, doc_ids)
        else:
            logger.warning("未能从上传响应解析 document_id，请在 RAGFlow 控制台手动触发解析")
        return len(texts)

    def _start_parse(self, dataset_id: str, document_ids: list[str]) -> None:
        """触发文档异步解析（分块 + 向量化）。"""
        resp = self.client.get_json(
            f"{self.api_base}/api/v1/datasets/{dataset_id}/documents/parse",
            method="POST",
            json_body={"document_ids": document_ids},
            headers=self._auth(),
        )
        self._unwrap(resp, "触发解析")
        logger.info("已触发 RAGFlow 解析 %d 个文档（异步，稍后可检索）", len(document_ids))

    @staticmethod
    def _extract_doc_ids(data: Any) -> list[str]:
        """从上传响应中提取文档 ID（兼容 list / dict 多种包裹）。"""
        if isinstance(data, list):
            return [d.get("id") for d in data if isinstance(d, dict) and d.get("id")]
        if isinstance(data, dict):
            for key in ("docs", "documents", "list", "data"):
                v = data.get(key)
                if isinstance(v, list):
                    return [d.get("id") for d in v if isinstance(d, dict) and d.get("id")]
            if data.get("id"):
                return [data["id"]]
        return []

    def search(self, query_vector: list[float], top_k: int = 5) -> list[dict[str, Any]]:
        raise RAGError(
            "RAGFlow 为托管检索，不接受外部向量，请调用 search_by_text(query) 而非 search(vector)"
        )

    def search_by_text(
        self,
        query: str,
        top_k: int = 5,
        *,
        embedding_fn: Callable[[str], list[float]] | None = None,
    ) -> list[dict[str, Any]]:
        """RAGFlow 混合检索（向量 + 关键词），question 直接交给平台。"""
        dataset_id = self.ensure_dataset()
        resp = self.client.get_json(
            f"{self.api_base}/api/v1/retrieval",
            method="POST",
            headers=self._auth(),
            json_body={
                "dataset_ids": [dataset_id],
                "question": query,
                "page": 1,
                "page_size": top_k,
                "top_k": top_k,
                "similarity_threshold": self.similarity_threshold,
                "vector_similarity_weight": self.vector_weight,
            },
        )
        data = self._unwrap(resp, "检索") or {}
        chunks = data.get("chunks", []) if isinstance(data, dict) else []
        hits = []
        for c in chunks:
            if not isinstance(c, dict):
                continue
            hits.append({
                "text": c.get("content", ""),
                "metadata": {
                    "document_name": c.get("document_name", ""),
                    "document_id": c.get("document_id", ""),
                    "title": c.get("document_name", ""),
                },
                "score": round(float(c.get("similarity", 0.0) or 0.0), 4),
            })
        logger.info("RAGFlow 检索 '%s' -> %d 条", query, len(hits))
        return hits

    def count(self) -> int:
        dataset_id = self.ensure_dataset()
        resp = self.client.get_json(
            f"{self.api_base}/api/v1/datasets/{dataset_id}/documents",
            params={"page": 1, "page_size": 1},
            headers=self._auth(),
        )
        data = self._unwrap(resp, "统计文档") or {}
        total = data.get("total") if isinstance(data, dict) else None
        return int(total or 0)

    def drop(self) -> None:
        if not self._dataset_id:
            try:
                self._dataset_id = self.ensure_dataset()
            except RAGError:
                return
        self.client._request(  # 复用统一请求层发 DELETE
            "DELETE",
            f"{self.api_base}/api/v1/datasets",
            json_body={"ids": [self._dataset_id]},
            headers=self._auth(),
        )
        logger.warning("已删除 RAGFlow 知识库: %s", self.dataset_name)
        self._dataset_id = None
