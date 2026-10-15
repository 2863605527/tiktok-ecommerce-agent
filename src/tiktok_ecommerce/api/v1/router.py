"""v1 路由聚合。"""
from fastapi import APIRouter

from tiktok_ecommerce.api.v1.auth import router as auth_router
from tiktok_ecommerce.api.v1.business import router as business_router
from tiktok_ecommerce.api.v1.chat import router as chat_router
from tiktok_ecommerce.api.v1.config import router as config_router
from tiktok_ecommerce.api.v1.diagnostics import router as diagnostics_router
from tiktok_ecommerce.api.v1.images import router as images_router
from tiktok_ecommerce.api.v1.listings import router as listings_router
from tiktok_ecommerce.api.v1.selection import router as selection_router

api_router = APIRouter()
api_router.include_router(auth_router, tags=["auth"])
api_router.include_router(selection_router, tags=["selection"])
api_router.include_router(config_router, tags=["config"])
api_router.include_router(chat_router, tags=["chat"])
api_router.include_router(images_router, tags=["images"])
api_router.include_router(listings_router, tags=["listings"])
api_router.include_router(business_router, tags=["business"])
api_router.include_router(diagnostics_router, tags=["diagnostics"])
