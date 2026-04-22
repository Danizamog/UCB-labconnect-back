from fastapi import APIRouter

from app.api.v1.endpoints.areas import router as areas_router
from app.api.v1.endpoints.asset_maintenance import router as asset_maintenance_router
from app.api.v1.endpoints.laboratories import router as laboratories_router
from app.api.v1.endpoints.loans import router as loans_router
from app.api.v1.endpoints.reports import router as reports_router
from app.api.v1.endpoints.assets import router as assets_router
from app.api.v1.endpoints.stock_items import router as stock_items_router

api_router = APIRouter(prefix="/v1")

api_router.include_router(areas_router)
api_router.include_router(laboratories_router)
api_router.include_router(assets_router)
api_router.include_router(asset_maintenance_router)
api_router.include_router(loans_router)
api_router.include_router(stock_items_router)
api_router.include_router(reports_router)
