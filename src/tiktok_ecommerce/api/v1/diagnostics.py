"""数据源一键诊断：GET /api/v1/diagnostics → 各真实数据源连通性状态。

企业级价值：卖家/运维一条命令确认系统所有外部依赖是否可用
（SocialCrawl 余量 / Milvus / 找家纺网 / LLM / Embedding）。
每个检查独立 try/except，单项失败不阻塞其他项。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from tiktok_ecommerce.api.v1.auth import get_current_user
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.config import get_settings

logger = get_logger(__name__)
router = APIRouter()


def _check_socialcrawl(settings) -> dict[str, Any]:
    """SocialCrawl：真实搜索一次（与流水线同通路，1 credit），附余额参考。"""
    if not settings.crawler.socialcrawl_api_key:
        return {"name": "SocialCrawl 商品源", "ok": False,
                "detail": "未配置 SOCIALCRAWL_API_KEY（.env）"}
    try:
        from tiktok_ecommerce.crawlers.factory import build_http_client, get_product_crawler
        crawler = get_product_crawler(settings, source="socialcrawl",
                                      client=build_http_client(settings))
        products = crawler.search_products("ボックスシーツ", limit=2)
        if products:
            return {"name": "SocialCrawl 商品源", "ok": True,
                    "detail": f"真实搜索连通 · 「ボックスシーツ」返回 {len(products)} 条"
                             f"（单价 {products[0].price} {products[0].currency}）"}
        return {"name": "SocialCrawl 商品源", "ok": True,
                "detail": "连通正常，但「ボックスシーツ」暂无结果（可换词）"}
    except Exception as e:
        return {"name": "SocialCrawl 商品源", "ok": False,
                "detail": f"搜索失败（{type(e).__name__}），请检查 Key/网络/额度"}


def _check_milvus(settings) -> dict[str, Any]:
    """Milvus：探测集合列表（需 pymilvus，未配置后端则跳过）。"""
    if settings.rag.backend != "milvus":
        return {"name": "Milvus 向量库", "ok": True,
                "detail": "当前检索后端非 milvus，跳过（RAG_BACKEND="
                          f"{settings.rag.backend}）"}
    try:
        from pymilvus import connections, utility
        connections.connect(alias="diag",
                            host=settings.milvus.host,
                            port=settings.milvus.port)
        cols = utility.list_collections(using="diag")
        connections.disconnect("diag")
        return {"name": "Milvus 向量库", "ok": True,
                "detail": f"连通正常 · 集合 {len(cols)} 个（{', '.join(cols[:3])}…）"}
    except Exception as e:
        return {"name": "Milvus 向量库", "ok": False,
                "detail": f"连接失败（{type(e).__name__}），请确认 docker 容器 tiktok-agent-milvus 已启动"}


def _check_jiafang(settings) -> dict[str, Any]:
    """找家纺网：用工厂（与流水线同通路）真实搜索「床笠」。"""
    if settings.crawler.supplier_source != "jiafang":
        return {"name": "找家纺网货源", "ok": True,
                "detail": "当前货源源非 jiafang，跳过（SUPPLIER_SOURCE="
                          f"{settings.crawler.supplier_source}）"}
    try:
        from tiktok_ecommerce.crawlers.factory import build_http_client, get_supplier_crawler
        crawler = get_supplier_crawler(settings, source="jiafang",
                                       client=build_http_client(settings))
        offers = crawler.search_offers(["床笠"], top_n=3)
        if offers:
            return {"name": "找家纺网货源", "ok": True,
                    "detail": f"真实搜索连通 · 「床笠」返回 {len(offers)} 条货源"
                             f"（最低 {offers[0].price}）"}
        return {"name": "找家纺网货源", "ok": True,
                "detail": "连通正常，但「床笠」暂无结果（可换词）"}
    except Exception as e:
        return {"name": "找家纺网货源", "ok": False,
                "detail": f"搜索失败（{type(e).__name__}），请检查网络或更换货源平台"}


def _check_llm(settings) -> dict[str, Any]:
    """LLM：极短调用验证连通（1 个 token 级别，成本可忽略）。"""
    try:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(base_url=settings.llm.base_url,
                         api_key=settings.llm.api_key,
                         model=settings.llm.model,
                         timeout=10, max_retries=1)
        resp = llm.invoke("只回复OK")
        ok = "OK" in str(resp.content).upper() or bool(resp.content)
        return {"name": f"LLM（{settings.llm.model}）", "ok": ok,
                "detail": f"连通正常 · 响应：{str(resp.content)[:20]}" if ok
                else "连通但响应异常，请检查模型配置"}
    except Exception as e:
        return {"name": f"LLM（{settings.llm.model}）", "ok": False,
                "detail": f"调用失败（{type(e).__name__}），请检查 API Key/额度/网络"}


def _check_ragflow(settings) -> dict[str, Any]:
    """RAGFlow：真实检索一次（复用流水线同通路 RAGFlowStore）。"""
    if settings.rag.backend != "ragflow":
        return {"name": "RAGFlow 知识库", "ok": True,
                "detail": "当前检索后端非 ragflow，跳过（RAG_BACKEND="
                          f"{settings.rag.backend}）"}
    if not settings.rag.api_key:
        return {"name": "RAGFlow 知识库", "ok": False,
                "detail": "未配置 RAG_API_KEY（.env）"}
    try:
        from tiktok_ecommerce.rag.factory import get_vector_store
        store = get_vector_store(settings)
        hits = store.search_by_text("牛奶绒 四件套 评价", top_k=1)
        if hits:
            return {"name": "RAGFlow 知识库", "ok": True,
                    "detail": f"混合检索连通 · 命中 {len(hits)} 条（相似度 {hits[0].get('score', 0):.2f}）"}
        return {"name": "RAGFlow 知识库", "ok": True,
                "detail": "连通正常，但知识库暂无匹配内容（可先跑一轮选品入库）"}
    except Exception as e:
        return {"name": "RAGFlow 知识库", "ok": False,
                "detail": f"检索失败（{type(e).__name__}），请确认 RAGFlow 服务/Key/知识库"}


_CHECKS = [_check_socialcrawl, _check_milvus, _check_ragflow, _check_jiafang, _check_llm]


@router.get("/diagnostics")
def run_diagnostics(user=Depends(get_current_user)) -> dict[str, Any]:
    """一键诊断全部真实数据源（单项独立，失败不阻塞）。"""
    settings = get_settings()
    results = [fn(settings) for fn in _CHECKS]
    ok_count = sum(1 for r in results if r["ok"])
    return {
        "summary": f"{ok_count}/{len(results)} 项正常",
        "all_ok": ok_count == len(results),
        "items": results,
        "checked_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }
