from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.application.container import lab_reservation_repo
from app.api.v1.router import api_router
from app.core.dependencies import auth_validation_client
from app.reminders.scheduler import reservation_reminder_scheduler

app = FastAPI(title="LabConnect Reservation Service", version="1.0.0")

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "reservation-service"}


@app.on_event("startup")
async def on_startup() -> None:
    lab_reservation_repo.sanitize_legacy_records()
    reservation_reminder_scheduler.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await reservation_reminder_scheduler.stop()
    auth_validation_client.close()


app.include_router(api_router)
