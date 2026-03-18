from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.db.base import Base
from app.db.session import engine
from app.services.redis_service import redis_client
from app.core.security import get_password_hash
from app.models.user import User
from sqlalchemy.orm import Session


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    db = Session(bind=engine)
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            db.add(
                User(
                    username="admin",
                    full_name="Administrador General",
                    email="admin@ucb.edu.bo",
                    hashed_password=get_password_hash("admin123"),
                    role="admin",
                    is_active=True,
                )
            )
            db.add(
                User(
                    username="ariel",
                    full_name="Usuario Demo",
                    email="ariel@ucb.edu.bo",
                    hashed_password=get_password_hash("user123"),
                    role="user",
                    is_active=True,
                )
            )
            db.commit()
    finally:
        db.close()

    yield
    await redis_client.aclose()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root():
    return {"message": "LabConnect Auth Service running"}