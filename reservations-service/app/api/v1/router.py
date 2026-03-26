from fastapi import APIRouter

from app.api.v1.endpoints.areas import router as areas_router
from app.api.v1.endpoints.availability import router as availability_router
from app.api.v1.endpoints.classes import router as classes_router
from app.api.v1.endpoints.class_tutorials import router as class_tutorials_router
from app.api.v1.endpoints.labs import router as labs_router
from app.api.v1.endpoints.practice_planning import router as practice_planning_router
from app.api.v1.endpoints.realtime import router as realtime_router


api_router = APIRouter(prefix="/v1")
api_router.include_router(areas_router)
api_router.include_router(labs_router)
api_router.include_router(practice_planning_router)
api_router.include_router(availability_router)
api_router.include_router(classes_router)
api_router.include_router(class_tutorials_router)
api_router.include_router(realtime_router)
