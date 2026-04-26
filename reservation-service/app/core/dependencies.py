from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from jose import JWTError, jwt
from time import monotonic

from app.core.config import settings


security = HTTPBearer(auto_error=False)
auth_validation_client = httpx.Client(
    timeout=httpx.Timeout(5.0, connect=3.0),
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
)
_TOKEN_VALIDATION_CACHE: dict[str, tuple[float, dict]] = {}
_TOKEN_VALIDATION_CACHE_TTL_SECONDS = 15
_TOKEN_VALIDATION_CACHE_MAX_ITEMS = 300


def _get_cached_token_payload(token: str) -> dict | None:
    cached = _TOKEN_VALIDATION_CACHE.get(token)
    if not cached:
        return None

    expires_at, payload = cached
    if expires_at <= monotonic():
        _TOKEN_VALIDATION_CACHE.pop(token, None)
        return None

    return dict(payload)


def _set_cached_token_payload(token: str, payload: dict) -> None:
    if len(_TOKEN_VALIDATION_CACHE) >= _TOKEN_VALIDATION_CACHE_MAX_ITEMS:
        oldest_key = next(iter(_TOKEN_VALIDATION_CACHE))
        _TOKEN_VALIDATION_CACHE.pop(oldest_key, None)

    _TOKEN_VALIDATION_CACHE[token] = (monotonic() + _TOKEN_VALIDATION_CACHE_TTL_SECONDS, dict(payload))


def _decode_token_payload(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError:
        return None

    subject = payload.get("sub") or payload.get("subject")
    if not subject:
        return None

    permissions = payload.get("permissions")
    if not isinstance(permissions, list):
        permissions = []

    return {
        "username": str(subject),
        "role": str(payload.get("role") or "user"),
        "permissions": permissions,
        "user_id": str(payload.get("user_id") or ""),
        "name": str(payload.get("name") or subject),
        "email": str(payload.get("email") or ""),
    }


def _resolve_live_payload(token: str, fallback_payload: dict | None) -> dict:
    cached_payload = _get_cached_token_payload(token)
    if cached_payload is not None:
        return cached_payload

    auth_service_url = settings.auth_service_url.strip().rstrip("/")
    fallback_payload = fallback_payload or {}

    if not auth_service_url:
        if not fallback_payload:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido o expirado")
        _set_cached_token_payload(token, fallback_payload)
        return fallback_payload

    try:
        response = auth_validation_client.get(
            f"{auth_service_url}/v1/auth/validate",
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as exc:
        if fallback_payload:
            return fallback_payload
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
        if fallback_payload and response.status_code >= 500:
            return fallback_payload
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo validar la sesion actual",
        )

    body = response.json()
    if not isinstance(body, dict):
        if not fallback_payload:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido o expirado")
        return fallback_payload

    live_permissions = body.get("permissions")
    if not isinstance(live_permissions, list):
        live_permissions = fallback_payload.get("permissions") or []

    resolved_payload = {
        "username": str(body.get("subject") or body.get("sub") or fallback_payload.get("username", "")),
        "role": str(body.get("role") or fallback_payload.get("role") or "user"),
        "permissions": [str(p).strip() for p in live_permissions if str(p).strip()],
        "user_id": str(body.get("user_id") or fallback_payload.get("user_id") or ""),
        "name": str(body.get("name") or fallback_payload.get("name") or fallback_payload.get("username", "")),
        "email": str(body.get("email") or fallback_payload.get("email") or ""),
    }
    _set_cached_token_payload(token, resolved_payload)
    return resolved_payload


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falta token Bearer")

    fallback_payload = _decode_token_payload(credentials.credentials)
    return _resolve_live_payload(credentials.credentials, fallback_payload)


def validate_token(token: str) -> dict:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Falta token Bearer")

    fallback_payload = _decode_token_payload(token)
    return _resolve_live_payload(token, fallback_payload)


def ensure_any_permission(current_user: dict, required_permissions: set[str], detail: str) -> None:
    permissions = set(current_user.get("permissions") or [])
    if current_user.get("role") == "admin" or "*" in permissions or permissions.intersection(required_permissions):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
