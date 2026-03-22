from fastapi import FastAPI

from app.interfaces.http.router import router as auth_router

app = FastAPI(title="LabConnect Auth Service", version="2.0.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "auth-service"}


app.include_router(auth_router)
