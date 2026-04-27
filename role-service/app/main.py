from fastapi import FastAPI
import logging

from app.core.dependencies import auth_validation_client
from app.application.container import role_repository
from app.interfaces.http.router import router as roles_router


class _SkipHealthAccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return 'GET /health' not in record.getMessage()


logging.getLogger("uvicorn.access").addFilter(_SkipHealthAccessLogFilter())

app = FastAPI(title="LabConnect Role Service", version="1.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "role-service"}


@app.on_event("shutdown")
def on_shutdown() -> None:
    auth_validation_client.close()
    close_repository = getattr(role_repository, "close", None)
    if callable(close_repository):
        close_repository()


app.include_router(roles_router)
