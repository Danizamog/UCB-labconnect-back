from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from jose import JWTError, jwt

from app.core.config import settings


security = HTTPBearer(auto_error=False)
auth_validation_client = httpx.Client(
    timeout=httpx.Timeout(5.0, connect=3.0),
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
)


def _decode_token_payload(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido o expirado") from exc

    subject = payload.get("sub")
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido o expirado")

    permissions = payload.get("permissions")
    if not isinstance(permissions, list):
        permissions = []

    return {
        "username": str(subject),
        "role": str(payload.get("role") or "user"),
        "permissions": permissions,
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
            body = response.json()
            if isinstance(body, dict):
                detail = body.get("detail") or detail
        except ValueError:
            pass
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo validar la sesion actual",
        )

    body = response.json()
    if not isinstance(body, dict):
        return fallback_payload

    live_permissions = body.get("permissions")
    if not isinstance(live_permissions, list):
        live_permissions = fallback_payload.get("permissions") or []

    return {
        "username": str(body.get("subject") or body.get("sub") or fallback_payload["username"]),
        "role": str(body.get("role") or fallback_payload.get("role") or "user"),
        "permissions": [str(p).strip() for p in live_permissions if str(p).strip()],
    }


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falta token Bearer")

    fallback_payload = _decode_token_payload(credentials.credentials)
    resolved_payload = _resolve_live_payload(credentials.credentials, fallback_payload)
    resolved_payload["access_token"] = credentials.credentials
    return resolved_payload


def ensure_any_permission(current_user: dict, required_permissions: set[str], detail: str) -> None:
    permissions = set(current_user.get("permissions") or [])
    if current_user.get("role") == "admin" or "*" in permissions or permissions.intersection(required_permissions):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
