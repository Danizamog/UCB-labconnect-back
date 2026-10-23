from fastapi import APIRouter

from app.api.v1.endpoints.supply_reservations import router as supply_reservations_router

api_router = APIRouter(prefix="/v1")

api_router.include_router(supply_reservations_router)
