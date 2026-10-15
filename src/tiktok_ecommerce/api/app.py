"""FastAPI 应用工厂：统一异常处理 + 路由注册 + 健康检查。

企业级要点：
- create_app() 工厂模式：便于测试时注入不同配置
- 全局异常处理器：AppError → 稳定 JSON 错误结构
- API 版本化：/api/v1
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from tiktok_ecommerce.api.ui import router as ui_router
from tiktok_ecommerce.api.v1.router import api_router
from tiktok_ecommerce.common.exceptions import AppError, ConfigError
from tiktok_ecommerce.common.logging import get_logger, setup_logging
from tiktok_ecommerce.config import get_settings

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """应用工厂。"""
    setup_logging()
    app = FastAPI(
        title="tiktok-ecommerce-agent API",
        version="0.1.0",
        description="TikTok 跨境选品与上架全链路多 Agent 系统",
    )

    # 静态产物（图片优化输出等）：/static/images/** → output/images/**
    s = get_settings()
    (s.output_dir / "images").mkdir(parents=True, exist_ok=True)
    app.mount("/static/images", StaticFiles(directory=s.output_dir / "images"), name="images")

    # 注册路由
    app.include_router(api_router, prefix="/api/v1")
    # Web 选择页面：根路径提供页面，/api/v1 提供品类列表
    app.include_router(ui_router)
    app.include_router(ui_router, prefix="/api/v1")

    # 健康检查
    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # 统一异常处理
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        logger.error("业务异常 %s: %s", exc.code, exc.message)
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    @app.exception_handler(ConfigError)
    async def config_error_handler(request: Request, exc: ConfigError):
        return JSONResponse(status_code=500, content=exc.to_dict())

    return app
