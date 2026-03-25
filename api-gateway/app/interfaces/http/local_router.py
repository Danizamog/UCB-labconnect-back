from fastapi import APIRouter

from app.routers.availability import router as availability_router
from app.routers.classes import router as classes_router

router = APIRouter()
router.include_router(availability_router)
router.include_router(classes_router)
