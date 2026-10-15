"""选品接口：POST /api/v1/selections（同步）+ POST /api/v1/selections/stream（SSE 进度）
+ 结果历史（GET/DELETE /api/v1/selections/history）。

可测试性设计（企业级）：按请求参数解析 pipeline 封装为 resolve_pipeline 依赖，
测试用 FastAPI dependency_overrides 替换为 Fake，无需真实 LLM/向量库。
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from tiktok_ecommerce.api.deps import get_pipeline
from tiktok_ecommerce.api.v1.auth import get_current_user
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.models.report import SelectionReport
from tiktok_ecommerce.models.supplier import ListingPackage, SupplierOffer
from tiktok_ecommerce.pipelines.selection import SelectionPipeline
from tiktok_ecommerce.storage.selection_store import SelectionStore, SavedSelection
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter()


class SelectionRequest(BaseModel):
    """触发选品的请求体。"""

    product: str = Field(..., min_length=1, max_length=200, description="商品关键词或链接")
    region: str = Field("US", max_length=10, description="目标市场")
    category: str = Field("bedding", description="品类：bedding/electronics/apparel/其他（未注册回退通用）")
    language: str = Field("ja", description="上架文案语言：ja（默认日语）/en/es/fr/de/ko")
    stages: list[str] | None = Field(None, description="流程阶段，默认全部：crawler/analyzer/sourcing/listing")
    image_dir: str | None = Field(None, description="商品图片目录（可选）")


class SelectionResponse(BaseModel):
    """选品流水线结果。"""

    products: list = []
    report: SelectionReport | None = None
    offers: list[SupplierOffer] = []
    listing: ListingPackage | None = None
    listing_path: str = ""
    error: str | None = None
    # 第三轮：决策增强（推荐评分 / 市场价位分布 / 关键词建议）
    score: dict | None = None
    market_overview: dict | None = None
    keyword_insights: dict | None = None


class SaveSelectionRequest(BaseModel):
    """手动保存选品结果（工作台/聊天可主动存档）。"""

    product: str = Field(..., min_length=1, max_length=200)
    region: str = Field("JP", max_length=10)
    category: str = Field("bedding")
    language: str = Field("ja")
    result: dict = Field(default_factory=dict)
    status: str = Field("ok", pattern="^(ok|error)$")


def resolve_pipeline(req: SelectionRequest) -> SelectionPipeline:
    """按请求参数解析流水线（品类 + 阶段裁剪），供 Depends 注入。"""
    stages = tuple(req.stages) if req.stages else None
    return get_pipeline(category_name=req.category, enabled_stages=stages)


@router.post("/selections", response_model=SelectionResponse)
def run_selection(
    req: SelectionRequest,
    pipeline: SelectionPipeline = Depends(resolve_pipeline),
    user=Depends(get_current_user),
) -> SelectionResponse:
    """执行选品流水线（可按品类 / 按阶段裁剪，同步）。"""
    logger.info("API 触发选品: %s 品类=%s 语言=%s 阶段=%s",
                req.product, req.category, req.language, req.stages)
    result = pipeline.run(
        query=req.product,
        region=req.region,
        image_dir=req.image_dir,
        category=req.category,
        language=req.language,
    )
    return _to_response(result, category=req.category, query=req.product)


def _to_response(result: dict, category: str = "bedding", query: str = "") -> SelectionResponse:
    """流水线结果 → API 响应（附决策增强：评分/市场/关键词）。"""
    from tiktok_ecommerce.services.keyword_mining import extract_keyword_insights
    from tiktok_ecommerce.services.market import build_market_overview
    from tiktok_ecommerce.services.scoring import compute_selection_score

    resp = SelectionResponse(
        products=result.get("products", []),
        report=result.get("report"),
        offers=result.get("offers", []),
        listing=result.get("listing"),
        listing_path=result.get("listing_path", ""),
        error=result.get("error"),
    )
    # 决策增强：评分/市场/关键词（纯函数，对空结果安全）
    if resp.error is None:
        resp.score = compute_selection_score(result)
        resp.market_overview = build_market_overview(resp.products)
        resp.keyword_insights = extract_keyword_insights(result, category, query=query)
    return resp


@router.post("/selections/stream")
def run_selection_stream(
    req: SelectionRequest,
    pipeline: SelectionPipeline = Depends(resolve_pipeline),
    user=Depends(get_current_user),
) -> StreamingResponse:
    """SSE 流式选品：实时推送各阶段进度（工作台运行时有明确反馈）。

    完成后自动写入选品结果库（按用户隔离，跨设备可回看）。
    """
    def event_gen():
        import queue
        import threading

        from tiktok_ecommerce.config import get_settings

        q: queue.Queue = queue.Queue()

        def _run() -> None:
            try:
                result = pipeline.run(
                    query=req.product,
                    region=req.region,
                    image_dir=req.image_dir,
                    category=req.category,
                    language=req.language,
                    on_progress=lambda stage, text, update=None: q.put(
                        {"type": "status", "stage": stage, "text": text}),
                )
                resp = _to_response(result, category=req.category, query=req.product)
                q.put({"type": "done", "result": json.loads(resp.model_dump_json())})
                # 自动存档（含失败结果，便于复盘）
                try:
                    store = SelectionStore(get_settings().data_dir / "app.db")
                    store.save(
                        user_id=int(user.id),
                        product=req.product,
                        region=req.region,
                        category=req.category,
                        language=req.language,
                        result=json.loads(resp.model_dump_json()),
                        status="ok" if resp.error is None else "error",
                    )
                except Exception:
                    logger.exception("选品结果自动存档失败")
            except Exception as e:
                logger.exception("流式选品失败: %s", e)
                q.put({"type": "error", "text": f"选品失败（{type(e).__name__}），请查看后端日志。"})

        threading.Thread(target=_run, daemon=True).start()
        while True:
            ev = q.get()
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            if ev["type"] in ("done", "error"):
                return

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---- 选品结果历史（企业级：跨设备持久化，按用户隔离） ----

def get_selection_store() -> SelectionStore:
    from tiktok_ecommerce.config import get_settings
    return SelectionStore(get_settings().data_dir / "app.db")


@router.post("/selections/history", response_model=SavedSelection)
def save_selection(
    req: SaveSelectionRequest,
    user=Depends(get_current_user),
    store: SelectionStore = Depends(get_selection_store),
) -> SavedSelection:
    """手动保存一次选品结果到历史库。"""
    return store.save(
        user_id=int(user.id),
        product=req.product,
        region=req.region,
        category=req.category,
        language=req.language,
        result=req.result,
        status=req.status,
    )


@router.get("/selections/history", response_model=list[SavedSelection])
def list_selections(
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    store: SelectionStore = Depends(get_selection_store),
) -> list[SavedSelection]:
    """当前用户的选品历史（倒序）。"""
    return store.list_for_user(user_id=int(user.id), limit=limit)


@router.delete("/selections/history/{record_id}")
def delete_selection(
    record_id: int,
    user=Depends(get_current_user),
    store: SelectionStore = Depends(get_selection_store),
) -> dict:
    """删除本人某条历史记录。"""
    store.delete(record_id=record_id, user_id=int(user.id))
    return {"ok": True}
