from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from jose import JWTError, jwt

from app.core.config import settings
from app.db.session import SessionLocal


security = HTTPBearer(auto_error=False)
MANAGER_ROLES = {"admin", "lab_manager", "encargado"}
MANAGER_PERMISSIONS = {"gestionar_reservas", "gestionar_tutorias", "gestionar_roles_permisos"}
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


def decode_user_payload(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
        ) from exc

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
        )

    return {
        "username": str(subject),
        "user_id": str(payload.get("user_id") or subject),
        "role": str(payload.get("role") or "user"),
        "name": payload.get("name"),
        "permissions": payload.get("permissions") if isinstance(payload.get("permissions"), list) else [],
        "raw": payload,
    }


def _resolve_live_payload(token: str, fallback_payload: dict) -> dict:
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
        detail = "Token invalido o expirado"
        try:
            payload = response.json()
            if isinstance(payload, dict):
                detail = payload.get("detail") or detail
        except ValueError:
            pass
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)

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
        live_permissions = fallback_payload.get("permissions") or []

    return {
        "username": str(live_payload.get("subject") or live_payload.get("sub") or fallback_payload["username"]),
        "user_id": str(live_payload.get("user_id") or fallback_payload["user_id"]),
        "role": str(live_payload.get("role") or fallback_payload.get("role") or "user"),
        "name": live_payload.get("name") or fallback_payload.get("name"),
        "permissions": [str(permission).strip() for permission in live_permissions if str(permission).strip()],
        "raw": fallback_payload.get("raw", {}),
    }


def get_optional_current_user_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict | None:
    if not credentials:
        return None
    fallback_payload = decode_user_payload(credentials.credentials)
    return _resolve_live_payload(credentials.credentials, fallback_payload)


def get_current_user_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta token Bearer",
        )
    fallback_payload = decode_user_payload(credentials.credentials)
    return _resolve_live_payload(credentials.credentials, fallback_payload)


def ensure_manager(current_user: dict | None) -> None:
    permissions = set(current_user.get("permissions") or []) if current_user else set()
    role = current_user.get("role") if current_user else None
    if (
        not current_user
        or (
            role not in MANAGER_ROLES
            and "*" not in permissions
            and not permissions.intersection(MANAGER_PERMISSIONS)
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autorizado para gestionar reservas y laboratorios",
        )


def ensure_any_permission(current_user: dict | None, required_permissions: set[str], detail: str) -> None:
    permissions = set(current_user.get("permissions") or []) if current_user else set()
    role = current_user.get("role") if current_user else None
    if (
        current_user
        and (
            role in MANAGER_ROLES
            or "*" in permissions
            or permissions.intersection(required_permissions)
        )
    ):
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )
