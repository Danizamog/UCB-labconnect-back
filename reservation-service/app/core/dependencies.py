import hashlib
from threading import Lock
from time import monotonic

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

_TOKEN_CACHE_LOCK = Lock()
_TOKEN_VALIDATION_CACHE: dict[str, tuple[float, dict]] = {}


def _token_cache_key(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_cached_token_payload(token: str) -> dict | None:
    key = _token_cache_key(token)
    with _TOKEN_CACHE_LOCK:
        cached = _TOKEN_VALIDATION_CACHE.get(key)
        if not cached:
            return None
        expires_at, payload = cached
        if expires_at <= monotonic():
            _TOKEN_VALIDATION_CACHE.pop(key, None)
            return None
        return dict(payload)


def _set_cached_token_payload(token: str, payload: dict) -> None:
    key = _token_cache_key(token)
    with _TOKEN_CACHE_LOCK:
        if len(_TOKEN_VALIDATION_CACHE) >= settings.token_cache_max_entries:
            _TOKEN_VALIDATION_CACHE.pop(next(iter(_TOKEN_VALIDATION_CACHE)), None)
        _TOKEN_VALIDATION_CACHE[key] = (
            monotonic() + settings.token_cache_ttl_seconds,
            dict(payload),
        )


def _invalidate_cached_token_payload(token: str) -> None:
    key = _token_cache_key(token)
    with _TOKEN_CACHE_LOCK:
        _TOKEN_VALIDATION_CACHE.pop(key, None)


def _decode_token_payload(token: str) -> dict | None:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require_exp": True, "require_iat": True, "require_nbf": True},
        )
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
            _set_cached_token_payload(token, fallback_payload)
            return fallback_payload
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo validar la sesion actual",
        ) from exc

    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        _invalidate_cached_token_payload(token)
        detail = "Token invalido o expirado"
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = body.get("detail") or detail
        except ValueError:
            pass
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)

    if response.status_code >= 400:
        if fallback_payload:
            _set_cached_token_payload(token, fallback_payload)
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


def is_admin_role(current_user: dict) -> bool:
    role = str(current_user.get("role") or "").strip().lower()
    return role in {"admin", "administrador"}


def ensure_any_permission(current_user: dict, required_permissions: set[str], detail: str) -> None:
    permissions = set(current_user.get("permissions") or [])
    if is_admin_role(current_user) or "*" in permissions or permissions.intersection(required_permissions):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
