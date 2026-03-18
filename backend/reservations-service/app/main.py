from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.models.laboratory import Laboratory
from app.models.practice_request import PracticeRequest
from app.models.practice_material import PracticeMaterial


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    db = Session(bind=engine)
    try:
        labs_count = db.query(Laboratory).count()
        if labs_count == 0:
            db.add_all(
                [
                    Laboratory(
                        name="Laboratorio de Informática 1",
                        location="Bloque A",
                        capacity=30,
                        description="Laboratorio para prácticas de informática básica",
                        is_active=True,
                    ),
                    Laboratory(
                        name="Laboratorio de Redes",
                        location="Bloque B",
                        capacity=20,
                        description="Laboratorio para prácticas de redes y cableado",
                        is_active=True,
                    ),
                    Laboratory(
                        name="Laboratorio de Electrónica",
                        location="Bloque C",
                        capacity=25,
                        description="Laboratorio para prácticas de electrónica",
                        is_active=True,
                    ),
                ]
            )
            db.commit()
    finally:
        db.close()

    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root():
    return {"message": "LabConnect Reservations Service running"}