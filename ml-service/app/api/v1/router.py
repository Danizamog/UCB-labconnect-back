from fastapi import APIRouter

from app.api.v1.endpoints.predictions import router as predictions_router

api_router = APIRouter(prefix="/v1")

api_router.include_router(predictions_router)
