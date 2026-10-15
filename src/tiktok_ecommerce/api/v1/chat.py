"""聊天接口：POST /api/v1/chat（同步）+ POST /api/v1/chat/stream（SSE 流式）。

请求示例：
    {"message": "帮我分析 ボックスシーツ 冬用 能不能卖", "region": "JP",
     "category": "bedding", "language": "ja"}
同步响应：
    {"reply": "自然语言回复", "intent": "select_product",
     "needs_product": false, "data": {可选结构化结果}}
流式响应（text/event-stream，每行 data: <json>）：
    {"type":"status","stage":"crawler","text":"正在采集竞品…"}
    {"type":"delta","text":"帮你分析了…"}          # 打字机文本块
    {"type":"done","reply":"...","intent":"...","needs_product":false,"data":{...}}
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from pydantic import BaseModel, Field

from tiktok_ecommerce.api.deps import get_pipeline
from tiktok_ecommerce.api.v1.auth import get_current_user
from tiktok_ecommerce.config import Settings, get_settings
from tiktok_ecommerce.crawlers.factory import get_supplier_crawler
from tiktok_ecommerce.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500, description="用户消息")
    region: str = Field("JP", description="目标市场（JP/US/...）")
    category: str = Field("bedding", description="品类（bedding/electronics/apparel）")
    language: str = Field("ja", description="上架文案语言（ja/en/es...）")
    conversation_id: str = Field("", max_length=128, description="会话 ID（前端会话持久化用，支持上下文引用）")


class ChatResponse(BaseModel):
    reply: str = Field(..., description="自然语言回复")
    intent: str = Field(..., description="意图：select_product/sourcing_only/listing_only/qa_ecommerce/out_of_scope")
    needs_product: bool = Field(False, description="是否需要用户补充商品词")
    data: dict | None = Field(None, description="结构化结果（前端渲染卡片）")


def _build_service(settings: Settings, category: str) -> ChatService:
    """组装聊天服务（同步/流式共用）。"""
    from tiktok_ecommerce.crawlers.factory import build_http_client
    from tiktok_ecommerce.common.llm import create_llm

    client = build_http_client(settings)
    supplier_crawler = get_supplier_crawler(settings, source=settings.crawler.supplier_source,
                                            client=client)
    # 运行时货源平台切换工厂：聊天说"去1688找货源 / 换回找家纺"时动态建 crawler
    supplier_factory = lambda src: get_supplier_crawler(  # noqa: E731
        settings, source=src, category=category, client=client)
    pipeline = get_pipeline(settings, category_name=category, enabled_stages=None)
    llm = create_llm(settings)  # 带货脚本生成器（与流水线同模型配置）
    return ChatService(
        settings=settings,
        pipeline_getter=lambda s, category_name, enabled_stages: pipeline,
        supplier_crawler=supplier_crawler,
        supplier_factory=supplier_factory,
        listing_agent=pipeline.agents["listing"],
        script_generator=llm,
    )


@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, settings: Settings = Depends(get_settings),
         user=Depends(get_current_user)) -> ChatResponse:
    """电商限定对话：意图路由 → 动作执行 → 回复（同步，兼容 CLI/旧客户端）。"""
    service = _build_service(settings, req.category)
    result = service.handle(req.message, region=req.region, category=req.category,
                            language=req.language, conversation_id=req.conversation_id,
                            user_id=str(user.id))
    return ChatResponse(**result)


@router.post("/stream")
def chat_stream(req: ChatRequest, settings: Settings = Depends(get_settings),
                user=Depends(get_current_user)) -> StreamingResponse:
    """SSE 流式对话：阶段进度 + 深度思考步骤 + 完成事件（前端聊天主通道）。"""
    service = _build_service(settings, req.category)

    def event_gen():
        for ev in service.handle_stream(req.message, region=req.region,
                                        category=req.category, language=req.language,
                                        conversation_id=req.conversation_id,
                                        user_id=str(user.id)):
            # default=str：data 中可能混入 datetime 等非 JSON 类型（如分析时间戳），
            # 兜底序列化避免 done 事件在流中断裂（曾导致前端永远"处理中…"）
            yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
