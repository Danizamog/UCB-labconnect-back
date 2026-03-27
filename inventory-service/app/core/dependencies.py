from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import httpx
from jose import JWTError, jwt

from app.core.config import settings
from app.db.session import SessionLocal

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="http://localhost:8001/api/v1/auth/login")
auth_validation_client = httpx.Client(
    timeout=httpx.Timeout(5.0, connect=3.0),
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _is_trusted_internal_service(payload: dict, fallback_payload: dict) -> bool:
    subject = str(payload.get("sub") or fallback_payload.get("username") or "").strip()
    user_id = str(payload.get("user_id") or fallback_payload.get("user_id") or "").strip()
    permissions = fallback_payload.get("permissions") or []
    role = str(payload.get("role") or fallback_payload.get("role") or "").strip().lower()

    return (
        bool(subject)
        and subject == user_id
        and subject in settings.trusted_internal_services
        and ("*" in permissions or role in {"admin", "service"})
    )


def get_current_user_payload(token: str = Depends(oauth2_scheme)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        raise credentials_exception

    user_id = payload.get("user_id")
    username = payload.get("sub")
    role = payload.get("role")
    permissions = payload.get("permissions")
    if not isinstance(permissions, list):
        permissions = []

    if user_id is None or username is None:
        raise credentials_exception

    fallback_payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "permissions": permissions,
    }

    if _is_trusted_internal_service(payload, fallback_payload):
        return fallback_payload

    auth_service_url = settings.auth_service_url.strip().rstrip("/")
    if not auth_service_url:
        return fallback_payload

    try:
        response = auth_validation_client.get(
            f"{auth_service_url}/v1/auth/validate",
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo validar la sesion actual",
        ) from exc

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        raise credentials_exception

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo validar la sesion actual",
        )

    live_payload = response.json()
    if not isinstance(live_payload, dict):
        return fallback_payload

    live_permissions = live_payload.get("permissions")
    if not isinstance(live_permissions, list):
        live_permissions = permissions

    return {
        "user_id": live_payload.get("user_id") or user_id,
        "username": live_payload.get("subject") or live_payload.get("sub") or username,
        "role": live_payload.get("role") or role,
        "permissions": [str(permission).strip() for permission in live_permissions if str(permission).strip()],
    }


def ensure_any_permission(current_user: dict, required_permissions: set[str], detail: str) -> None:
    permissions = set(current_user.get("permissions") or [])
    if current_user.get("role") == "admin" or "*" in permissions or permissions.intersection(required_permissions):
        return
    raise HTTPException(status_code=403, detail=detail)
