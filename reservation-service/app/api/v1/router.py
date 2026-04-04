from fastapi import APIRouter

from app.api.v1.endpoints.availability import router as availability_router
from app.api.v1.endpoints.blocks import router as blocks_router
from app.api.v1.endpoints.realtime import router as realtime_router
from app.api.v1.endpoints.reservations import router as reservations_router
from app.api.v1.endpoints.schedules import router as schedules_router

api_router = APIRouter(prefix="/v1")

api_router.include_router(reservations_router)
api_router.include_router(schedules_router)
api_router.include_router(blocks_router)
api_router.include_router(availability_router)
api_router.include_router(realtime_router)
