"""运行配置状态接口：返回当前数据源/检索后端（脱敏），供前端展示。"""
from __future__ import annotations

from fastapi import APIRouter

from tiktok_ecommerce.config import get_settings

router = APIRouter()


def _mask_key(key: str) -> str:
    """密钥脱敏：保留前 4 后 4，中间打码；空值返回空。"""
    if not key:
        return ""
    if len(key) <= 10:
        return key[:3] + "****"
    return key[:4] + "****" + key[-4:]


@router.get("/config")
def runtime_config() -> dict:
    """当前运行配置（数据源/检索后端/语言体系），密钥脱敏展示。"""
    s = get_settings()
    return {
        "product_source": s.crawler.product_source,
        "supplier_source": s.crawler.supplier_source,
        "rag_backend": s.rag.backend,
        "fastmoss_region": s.crawler.fastmoss_region,
        "has_fastmoss_key": bool(s.crawler.third_party_product_api_key),
        "fastmoss_key_masked": _mask_key(s.crawler.third_party_product_api_key),
        "has_socialcrawl_key": bool(s.crawler.socialcrawl_api_key),
        "socialcrawl_key_masked": _mask_key(s.crawler.socialcrawl_api_key),
        "has_tikhub_key": bool(s.crawler.tikhub_api_key),
        "tikhub_key_masked": _mask_key(s.crawler.tikhub_api_key),
        "jiafang_base_url": s.crawler.jiafang_base_url,
        "llm_model": s.llm.model if s.llm else "",
        "embedding_model": s.llm.embedding_model if s.llm else "",
    }
