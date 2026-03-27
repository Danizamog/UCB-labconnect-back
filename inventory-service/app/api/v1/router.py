from fastapi import APIRouter

from app.api.v1.endpoints.areas import router as areas_router
from app.api.v1.endpoints.laboratories import router as laboratories_router
from app.api.v1.endpoints.assets import router as assets_router
from app.api.v1.endpoints.stock_items import router as stock_items_router

router = APIRouter(prefix="/v1")

router.include_router(areas_router)
router.include_router(laboratories_router)
router.include_router(assets_router)
router.include_router(stock_items_router)
