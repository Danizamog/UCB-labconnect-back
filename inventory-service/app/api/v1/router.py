from fastapi import APIRouter

from app.api.v1.endpoints.assets import router as assets_router
from app.api.v1.endpoints.loans import router as loans_router
from app.api.v1.endpoints.stock import router as stock_router

api_router = APIRouter()
api_router.include_router(assets_router, prefix="/v1/inventory")
api_router.include_router(loans_router, prefix="/v1/inventory")
api_router.include_router(stock_router, prefix="/v1/inventory")
