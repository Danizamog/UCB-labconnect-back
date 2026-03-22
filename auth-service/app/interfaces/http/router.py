from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.container import (
    login_user_use_case,
    register_user_use_case,
    validate_token_use_case,
)
from app.core.config import settings
from app.interfaces.http.schemas.auth import LoginRequest, RegisterRequest, TokenResponse

router = APIRouter(prefix="/v1/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest) -> dict:
    try:
        user = register_user_use_case.execute(payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return {"message": "Usuario registrado", "username": user.username}


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    try:
        token = login_user_use_case.execute(payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return TokenResponse(access_token=token, expires_in=settings.token_expire_minutes * 60)


@router.get("/validate")
async def validate_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta token Bearer",
        )

    try:
        payload = validate_token_use_case.execute(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return {
        "valid": True,
        "subject": payload.get("sub"),
        "expires_at": payload.get("exp"),
    }
