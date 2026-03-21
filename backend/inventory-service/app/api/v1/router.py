from fastapi import APIRouter

from app.api.v1.endpoints.assets import router as assets_router
from app.api.v1.endpoints.stock import router as stock_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(assets_router)
api_router.include_router(stock_router)