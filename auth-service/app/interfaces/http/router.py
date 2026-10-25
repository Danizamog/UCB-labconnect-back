import logging
import secrets
import string
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.container import (
    login_user_use_case,
    login_with_google_use_case,
    session_cache,
    user_repository,
    validate_token_use_case,
)
from app.core.config import settings
from app.domain.entities.user import User
from app.domain.security_query import SecurityQuery
from app.domain.account_security import ACCOUNT_LOCKED_MESSAGE, AccountLockedError, LOCAL_PASSWORD_PROVIDERS, password_change_required
from app.interfaces.http.schemas.auth import (
    GoogleLoginRequest,
    InstitutionalLoginRequest,
    InstitutionalSSOConfigResponse,
    ChangePasswordRequest,
    LoginRequest,
    LoginCaptchaConfigResponse,
    TokenResponse,
)
from app.interfaces.http.schemas.user import (
    UserProfileResponse,
    UserProfileUpdateRequest,
    PasswordResetResponse,
)
from app.domain.password_policy import (
    MAX_FAILED_LOGIN_ATTEMPTS,
    PASSWORD_HISTORY_SIZE,
    PASSWORD_LIFETIME_DAYS,
    password_expires_at,
    validate_password,
)
from app.infrastructure.security.password import hash_password, verify_password
from app.infrastructure.security.recaptcha import RecaptchaRejected, RecaptchaUnavailable, is_recaptcha_configured, verify_recaptcha
from app.infrastructure.security.token_provider import create_access_token, decode_token
from app.infrastructure.security.account_locks import account_login_lock

logger = logging.getLogger(__name__)

INVALID_CREDENTIALS_MESSAGE = "Cuenta no reconocida"
SESSION_UNAVAILABLE_MESSAGE = "No se pudo validar la sesion actual"
ALLOWED_PROFILE_TYPES = {"student", "teacher", "staff", "guest", "lab_manager"}
PROFILE_MUTABLE_FIELDS = (
    "username",
    "name",
    "profile_type",
    "phone",
    "academic_page",
    "faculty",
    "career",
    "student_code",
    "campus",
    "bio",
)

router = APIRouter()
security = HTTPBearer(auto_error=False)

auth_router = APIRouter(prefix="/v1/auth", tags=["auth"])
users_router = APIRouter(prefix="/v1/users", tags=["users"])
security_router = APIRouter(prefix="/v1/security", tags=["security"])


def _audit(action: str, *, actor_email: str = "", actor_id: str = "", result: str = "success", target_type: str = "", target_id: str = "", reason: str = "") -> None:
    try:
        user_repository.create_security_record("security_audit_event", {
            "action": action,
            "actor_email": actor_email,
            "actor_id": actor_id,
            "result": result,
            "target_type": target_type,
            "target_id": target_id,
            "reason": reason,
        })
    except Exception as exc:
        logger.warning("No se pudo registrar auditoria %s: %s", action, exc)


def _record_session(token: str) -> None:
    try:
        payload = decode_token(token)
        issued_at = datetime.fromtimestamp(int(payload["iat"]), timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000Z")
        expires_at = datetime.fromtimestamp(int(payload["exp"]), timezone.utc).strftime("%Y-%m-%d %H:%M:%S.000Z")
        user_repository.create_security_record("auth_session", {
            "user_id": str(payload.get("user_id") or ""), "email": str(payload.get("email") or payload.get("sub") or ""),
            "jti": str(payload.get("jti") or ""), "status": "active", "issued_at": issued_at, "expires_at": expires_at,
        })
    except Exception as exc:
        logger.warning("No se pudo registrar la sesion: %s", exc)


def _to_user_response(user: User, *, include_security: bool = True) -> UserProfileResponse:
    return UserProfileResponse(
        id=user.id,
        username=user.username,
        name=user.name,
        role=user.role,
        profile_type=user.profile_type,
        phone=user.phone,
        academic_page=user.academic_page,
        faculty=user.faculty,
        career=user.career,
        student_code=user.student_code,
        campus=user.campus,
        bio=user.bio,
        is_active=user.is_active,
        created_at=user.created_at,
        updated_at=user.updated_at,
        auth_provider=user.auth_provider,
        google_linked=bool(user.google_sub),
        local_password_enabled=user.auth_provider in LOCAL_PASSWORD_PROVIDERS,
        password_changed_at=user.password_changed_at,
        user_code=user.user_code,
        security_locked=user.security_locked if include_security else False,
        failed_login_attempts=user.failed_login_attempts if include_security else 0,
        locked_at=user.locked_at if include_security else None,
        password_expires_at=user.password_expires_at if include_security else None,
        must_change_password=password_change_required(user) if include_security else False,
    )


def _ensure_password_not_reused(user: User, password: str) -> None:
    for previous_hash in user_repository.list_password_hashes(user.id or "", PASSWORD_HISTORY_SIZE):
        try:
            if verify_password(password, previous_hash):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"No puedes reutilizar tus ultimas {PASSWORD_HISTORY_SIZE} contrasenas")
        except ValueError:
            continue


def _record_password(user: User, password: str, reason: str) -> None:
    user_repository.record_password_hash(user.id or "", hash_password(password), reason)


def _generate_temporary_password() -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%&*+-_?"
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(20))
        try:
            validate_password(candidate)
            return candidate
        except ValueError:
            continue


def _normalize_profile_type(profile_type: str | None) -> str | None:
    if profile_type is None:
        return None
    normalized = profile_type.strip().lower()
    if not normalized:
        return None
    if normalized not in ALLOWED_PROFILE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tipo de perfil invalido",
        )
    return normalized


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _get_current_payload(
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

    resolved = _build_live_session_payload(payload)
    if int(payload.get("session_version") or 1) != int(resolved.get("session_version") or 1):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesion revocada")
    return resolved


def _build_live_session_payload(payload: dict) -> dict:
    subject = str(payload.get("sub") or "").strip().lower()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
        )

    try:
        user = user_repository.get_by_username(subject)
    except (ValueError, httpx.HTTPError) as exc:
        # Fallo de infraestructura (PocketBase caido / no se pudo autenticar el admin):
        # NO es una sesion invalida. Devolvemos 503 para no expulsar al usuario con un 401.
        logger.warning("No se pudo validar la sesion contra PocketBase: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=SESSION_UNAVAILABLE_MESSAGE,
        ) from exc

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_CREDENTIALS_MESSAGE,
        )
    if user.security_locked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=ACCOUNT_LOCKED_MESSAGE)

    role = user.role or "user"
    permissions = sorted(set(user.permissions))
    base_session = {
        "sub": user.username,
        "subject": user.username,
        "user_id": user.id,
        "role": role,
        "name": user.name,
        "email": user.username,
        "permissions": permissions,
        "auth_provider": user.auth_provider,
        "session_version": user.session_version,
        "must_change_password": password_change_required(user),
        "password_expires_at": user.password_expires_at,
        "valid": True,
        "local_password_enabled": user.auth_provider in LOCAL_PASSWORD_PROVIDERS,
        "google_linked": bool(user.google_sub),
        "auth_method": payload.get("auth_method", "password"),
        "auth_time": payload.get("auth_time", 0),
        "can_reset_password_with_google": _can_reset_with_google(user, payload),
    }
    return {
        **base_session,
        "picture": payload.get("picture"),
        "google_sub": payload.get("google_sub"),
        "exp": payload.get("exp"),
    }


def _can_reset_with_google(user: User, payload: dict) -> bool:
    try:
        authenticated_at = int(payload.get("auth_time") or 0)
    except (TypeError, ValueError):
        return False
    now = int(datetime.now(timezone.utc).timestamp())
    return bool(
        payload.get("auth_method") == "google"
        and user.google_sub
        and secrets.compare_digest(user.google_sub, str(payload.get("google_sub") or ""))
        and now - 300 <= authenticated_at <= now + 5
    )


@contextmanager
def _account_write(user_id: str):
    user = user_repository.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    with account_login_lock(user.username):
        fresh = user_repository.get_by_id(user_id)
        if not fresh:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        yield fresh


def _has_any_permission(payload: dict, required_permissions: set[str]) -> bool:
    if payload.get("must_change_password"):
        return False
    permissions = payload.get("permissions") if isinstance(payload.get("permissions"), list) else []
    return bool(required_permissions.intersection(permissions))


def _require_profile_manager(payload: dict = Depends(_get_current_payload)) -> dict:
    if _has_any_permission(payload, {"gestionar_usuarios", "modificar_usuarios", "dar_baja_usuarios", "desbloquear_usuarios"}):
        return payload
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No autorizado para gestionar perfiles",
    )


_USER_DIRECTORY_PERMISSIONS = {
    "consultar_usuarios",
    "consultar_directorio_operativo",
    "gestionar_inventario",
    "gestionar_estado_equipos",
    "gestionar_mantenimiento",
    "gestionar_prestamos",
    "gestionar_stock",
    "gestionar_reactivos_quimicos",
    "gestionar_reservas_materiales",
}


def _require_user_directory_reader(payload: dict = Depends(_get_current_payload)) -> dict:
    if _has_any_permission(payload, _USER_DIRECTORY_PERMISSIONS):
        return payload
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No autorizado para consultar el directorio de usuarios",
    )


def _ensure_reactivation_permission(payload: dict) -> None:
    if _has_any_permission(payload, {"gestionar_estado_cuentas", "desbloquear_usuarios", "dar_baja_usuarios"}):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No autorizado para activar o desactivar cuentas",
    )


def _ensure_profile_update_permissions(
    current_user: dict,
    existing_user: User,
    payload: UserProfileUpdateRequest,
) -> None:
    if _has_any_permission(current_user, {"gestionar_usuarios", "modificar_usuarios"}):
        if payload.is_active is not None and payload.is_active != existing_user.is_active:
            _ensure_reactivation_permission(current_user)
        return

    requested_profile_changes = any(getattr(payload, field_name) is not None for field_name in PROFILE_MUTABLE_FIELDS)
    if requested_profile_changes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No autorizado para editar datos del perfil",
        )

    if payload.is_active is not None and payload.is_active != existing_user.is_active:
        _ensure_reactivation_permission(current_user)
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No se detectaron cambios permitidos para este rol",
    )


@auth_router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    try:
        verify_recaptcha(payload.captcha_token)
    except RecaptchaRejected:
        _audit("auth.captcha.failed", result="failed", reason="challenge_rejected")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Completa nuevamente la verificacion de seguridad.") from None
    except RecaptchaUnavailable:
        _audit("auth.captcha.unavailable", result="failed", reason="verification_unavailable")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="La verificacion de seguridad no esta disponible. Intenta mas tarde.") from None
    try:
        token = login_user_use_case.execute(payload.username, payload.password)
    except AccountLockedError:
        session_cache.invalidate(payload.username.strip().lower())
        _audit("auth.account.locked", actor_email=payload.username.strip().lower(), result="failed", reason="three_failed_logins")
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=ACCOUNT_LOCKED_MESSAGE) from None
    except ValueError as exc:
        session_cache.invalidate(payload.username.strip().lower())
        _audit("auth.login.failed", actor_email=payload.username.strip().lower(), result="failed", reason="invalid_credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    _audit("auth.login.succeeded", actor_email=payload.username.strip().lower())
    _record_session(token)
    return TokenResponse(access_token=token, expires_in=settings.token_expire_minutes * 60)


@auth_router.get("/captcha/config", response_model=LoginCaptchaConfigResponse)
def get_login_captcha_config(response: Response) -> LoginCaptchaConfigResponse:
    configured = is_recaptcha_configured()
    response.headers["Cache-Control"] = "no-store"
    return LoginCaptchaConfigResponse(
        enabled=settings.recaptcha_enabled,
        configured=configured,
        site_key=settings.recaptcha_site_key if settings.recaptcha_enabled and configured else None,
    )


@auth_router.get("/institutional/config", response_model=InstitutionalSSOConfigResponse)
def get_institutional_sso_config() -> InstitutionalSSOConfigResponse:
    provider = settings.institutional_sso_provider or None
    enabled = bool(provider and settings.google_client_id.strip())
    client_id = settings.google_client_id.strip() if enabled else None

    return InstitutionalSSOConfigResponse(
        enabled=enabled,
        provider=provider,
        client_id=client_id,
        button_label=settings.institutional_sso_button_label.strip() or "Continuar con cuenta institucional",
    )


def _google_login(credential: str) -> TokenResponse:
    try:
        token = login_with_google_use_case.execute(credential)
    except AccountLockedError:
        _audit("auth.sso_login.blocked", result="failed", reason="account_locked")
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail=ACCOUNT_LOCKED_MESSAGE) from None
    except ValueError as exc:
        detail = str(exc)
        code = status.HTTP_503_SERVICE_UNAVAILABLE if "configurado" in detail else status.HTTP_401_UNAUTHORIZED
        raise HTTPException(status_code=code, detail=detail) from exc
    claims = decode_token(token)
    session_cache.invalidate(str(claims.get("sub") or ""))
    _audit("auth.sso_login.succeeded", actor_email=str(claims.get("sub") or ""))
    _record_session(token)
    return TokenResponse(access_token=token, expires_in=settings.token_expire_minutes * 60)


@auth_router.post("/institutional", response_model=TokenResponse)
def login_with_institutional_sso(payload: InstitutionalLoginRequest) -> TokenResponse:
    return _google_login(payload.credential)


@auth_router.post("/google", response_model=TokenResponse)
def login_with_google(payload: GoogleLoginRequest) -> TokenResponse:
    return _google_login(payload.credential)


@auth_router.get("/validate")
def validate_token(
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

    resolved_payload = _build_live_session_payload(payload)
    if int(payload.get("session_version") or 1) != int(resolved_payload.get("session_version") or 1):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesion revocada")
    return {
        **resolved_payload,
        "expires_at": payload.get("exp"),
    }


@auth_router.post("/change-password", response_model=TokenResponse | None)
def change_own_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(_get_current_payload),
) -> TokenResponse | Response:
    if body.new_password != body.new_password_confirm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La confirmacion no coincide")
    try:
        validate_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if body.current_password == body.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La nueva contrasena debe ser diferente")

    with _account_write(str(current_user.get("user_id") or "")) as user:
        if user.security_locked or not user.is_active or user.session_version != current_user.get("session_version"):
            raise HTTPException(status_code=401, detail="La sesion ya no esta disponible. Inicia sesion nuevamente.")
        google_verified = _can_reset_with_google(user, current_user)
        initial_google_setup = google_verified and user.auth_provider == "google"
        if not google_verified:
            if user.auth_provider not in LOCAL_PASSWORD_PROVIDERS or not body.current_password:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verifica nuevamente tu identidad con Google o introduce tu contrasena actual.")
            if not user_repository.authenticate(user.username, body.current_password):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contrasena actual no es correcta")

        if user.auth_provider in LOCAL_PASSWORD_PROVIDERS and user_repository.authenticate(user.username, body.new_password):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No puedes reutilizar tu contrasena actual.")
        _ensure_password_not_reused(user, body.new_password)

        changed_at = datetime.now(timezone.utc)
        user.password_changed_at = changed_at.isoformat()
        user.password_expires_at = password_expires_at(changed_at)
        user.must_change_password = False
        if user.google_sub:
            user.auth_provider = "hybrid"
        user.failed_login_attempts = 0
        user.security_locked = False
        user.locked_at = None
        user.session_version += 1
        user_repository.change_password(user, body.new_password)
        _record_password(user, body.new_password, "self_change")
        user_repository.revoke_security_sessions(user.id or "", "password_changed")
        session_cache.invalidate(user.username)
        _audit("auth.password.changed", actor_email=user.username, actor_id=user.id or "", target_type="user", target_id=user.id or "")
        if initial_google_setup:
            # Revocar el token restringido y emitir una sesion nueva tras el alta de clave.
            token = create_access_token(subject=user.username, extra_claims={
                "user_id": user.id, "role": user.role or "user", "name": user.name,
                "email": user.username, "permissions": sorted(set(user.permissions)),
                "auth_provider": user.auth_provider, "auth_method": "google",
                "auth_time": current_user.get("auth_time"), "google_sub": user.google_sub,
                "google_linked": True, "local_password_enabled": True,
                "session_version": user.session_version, "must_change_password": False,
                "password_expires_at": user.password_expires_at,
            })
            _record_session(token)
            return TokenResponse(access_token=token, expires_in=settings.token_expire_minutes * 60)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@auth_router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def revoke_own_sessions(current_user: dict = Depends(_get_current_payload)) -> None:
    user = user_repository.get_by_id(str(current_user.get("user_id") or ""))
    if user:
        user.session_version += 1
        user_repository.save(user)
        user_repository.revoke_security_sessions(user.id or "", "user_logout")
        session_cache.invalidate(user.username)
        _audit("auth.session.revoked", actor_email=user.username, actor_id=user.id or "", target_type="user", target_id=user.id or "")


def _require_security_permission(permission: str):
    def dependency(payload: dict = Depends(_get_current_payload)) -> dict:
        if _has_any_permission(payload, {permission}):
            return payload
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado para consultar seguridad")
    return dependency


def _security_options(page: int = Query(1, ge=1), per_page: int = Query(100, ge=1, le=200),
                      query: str = Query("", max_length=150), status_filter: str = Query("", alias="status", max_length=30),
                      date_from: date | None = None, date_to: date | None = None,
                      snapshot_at: datetime | None = None, paginated: bool = False):
    try:
        return SecurityQuery(page=page, per_page=per_page, query=query.strip(), status=status_filter,
                             date_from=date_from, date_to=date_to, snapshot_at=snapshot_at), paginated
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _security_page(collection, options, *, auth_only=False):
    query, paginated = options
    query.auth_only = auth_only
    try:
        result = user_repository.page_security_records(collection, query)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="No se pudo consultar la evidencia. Conserva la ultima consulta y vuelve a intentar.") from exc
    return result if paginated else result["items"]


@security_router.get("/summary")
def security_summary(current_user: dict = Depends(_get_current_payload)):
    definitions = [
        ("auth", "consultar_eventos_autenticacion", "security_audit_event", "unsuccessful"),
        ("sessions", "consultar_sesiones_usuarios", "auth_session", "active"),
        ("incidents", "consultar_incidentes_seguridad", "security_incident", "unresolved"),
    ]
    allowed = [item for item in definitions if item[1] in (current_user.get("permissions") or [])]
    if not allowed:
        raise HTTPException(status_code=403, detail="No autorizado para consultar estos indicadores")
    now = datetime.now(timezone.utc)
    result = {"counts": {}, "errors": [], "asOf": now.isoformat()}
    for key, _, collection, state in allowed:
        try:
            query = SecurityQuery(per_page=1, status=state, snapshot_at=now,
                                  since=now - timedelta(hours=24) if key == "auth" else None, auth_only=key == "auth")
            result["counts"][key] = user_repository.page_security_records(collection, query)["totalItems"]
        except (ValueError, RuntimeError, httpx.HTTPError):
            result["errors"].append({"key": key, "message": "No se pudo consultar este indicador"})
    return result


@security_router.get("/audit-events")
def list_audit_events(options=Depends(_security_options), _: dict = Depends(_require_security_permission("consultar_auditoria_seguridad"))):
    return _security_page("security_audit_event", options)


@security_router.get("/auth-events")
def list_auth_events(options=Depends(_security_options), _: dict = Depends(_require_security_permission("consultar_eventos_autenticacion"))):
    return _security_page("security_audit_event", options, auth_only=True)


@security_router.get("/sessions")
def list_sessions(options=Depends(_security_options), _: dict = Depends(_require_security_permission("consultar_sesiones_usuarios"))):
    return _security_page("auth_session", options)


@security_router.get("/incidents")
def list_incidents(options=Depends(_security_options), _: dict = Depends(_require_security_permission("consultar_incidentes_seguridad"))):
    return _security_page("security_incident", options)


@security_router.get("/access-reviews")
def list_access_reviews(options=Depends(_security_options), _: dict = Depends(_require_security_permission("revisar_accesos_rbac"))):
    return _security_page("access_review", options)


@security_router.get("/reports/export")
def export_security_report(_: dict = Depends(_require_security_permission("exportar_reportes_seguridad"))) -> dict:
    return {
        "audit_events": user_repository.list_security_records("security_audit_event", 1, 200),
        "sessions": user_repository.list_security_records("auth_session", 1, 200),
        "incidents": user_repository.list_security_records("security_incident", 1, 200),
        "access_reviews": user_repository.list_security_records("access_review", 1, 200),
    }


@users_router.get("/", response_model=list[UserProfileResponse])
def list_users(
    page: int = 1,
    per_page: int = 100,
    current_user: dict = Depends(_require_user_directory_reader),
) -> list[UserProfileResponse]:
    safe_per_page = max(1, min(per_page, 500))
    safe_page = max(1, page)
    users, _total = user_repository.list_paginated(safe_page, safe_per_page)
    include_security = _has_any_permission(current_user, {"consultar_usuarios", "desbloquear_usuarios", "reiniciar_credenciales"})
    return [_to_user_response(user, include_security=include_security) for user in users]


@users_router.get("/me", response_model=UserProfileResponse)
def get_my_profile(current_user: dict = Depends(_get_current_payload)) -> UserProfileResponse:
    user = user_repository.get_by_id(str(current_user.get("user_id") or ""))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    response = _to_user_response(user)
    response.can_reset_password_with_google = _can_reset_with_google(user, current_user)
    if response.can_reset_password_with_google:
        response.google_verification_expires_at = int(current_user["auth_time"]) + 300
    response.auth_method = current_user.get("auth_method")
    return response


@users_router.get("/{user_id}", response_model=UserProfileResponse)
def get_user(user_id: str, current_user: dict = Depends(_require_user_directory_reader)) -> UserProfileResponse:
    user = user_repository.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    include_security = _has_any_permission(current_user, {"consultar_usuarios", "desbloquear_usuarios", "reiniciar_credenciales"})
    return _to_user_response(user, include_security=include_security)


@users_router.put("/{user_id}", response_model=UserProfileResponse)
def update_user_profile(
    user_id: str,
    payload: UserProfileUpdateRequest,
    current_user: dict = Depends(_require_profile_manager),
) -> UserProfileResponse:
    with _account_write(user_id) as existing_user:
        _ensure_profile_update_permissions(current_user, existing_user, payload)

        new_username = existing_user.username
        if payload.username is not None:
            normalized_username = payload.username.strip().lower()
            if existing_user.google_sub and normalized_username != existing_user.username:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El correo vinculado a Google no se modifica desde la administracion.")
            if not normalized_username.endswith(settings.institutional_email_domain):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Solo se permiten correos institucionales UCB",
                )
            user_with_same_username = user_repository.get_by_username(normalized_username)
            if user_with_same_username and user_with_same_username.id != existing_user.id:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El usuario ya existe")
            new_username = normalized_username

        user_to_save = User(
            id=existing_user.id,
            username=new_username,
            hashed_password=existing_user.hashed_password,
            permissions=list(existing_user.permissions),
            created_at=existing_user.created_at,
            updated_at=existing_user.updated_at,
            name=payload.name.strip() if payload.name is not None else existing_user.name,
            role=existing_user.role,
            profile_type=(
                _normalize_profile_type(payload.profile_type)
                if payload.profile_type is not None
                else existing_user.profile_type
            ),
            phone=_normalize_optional_text(payload.phone) if payload.phone is not None else existing_user.phone,
            academic_page=(
                _normalize_optional_text(payload.academic_page)
                if payload.academic_page is not None
                else existing_user.academic_page
            ),
            faculty=_normalize_optional_text(payload.faculty) if payload.faculty is not None else existing_user.faculty,
            career=_normalize_optional_text(payload.career) if payload.career is not None else existing_user.career,
            student_code=(
                _normalize_optional_text(payload.student_code)
                if payload.student_code is not None
                else existing_user.student_code
            ),
            campus=_normalize_optional_text(payload.campus) if payload.campus is not None else existing_user.campus,
            bio=_normalize_optional_text(payload.bio) if payload.bio is not None else existing_user.bio,
            is_active=payload.is_active if payload.is_active is not None else existing_user.is_active,
            auth_provider=existing_user.auth_provider,
            google_sub=existing_user.google_sub,
            password_changed_at=existing_user.password_changed_at,
            session_version=existing_user.session_version,
            security_locked=existing_user.security_locked,
            user_code=existing_user.user_code,
            failed_login_attempts=existing_user.failed_login_attempts,
            locked_at=existing_user.locked_at,
            password_expires_at=existing_user.password_expires_at,
            must_change_password=existing_user.must_change_password,
        )

        try:
            saved_user = user_repository.save(user_to_save)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        session_cache.invalidate(existing_user.username)
        if saved_user.username != existing_user.username:
            session_cache.invalidate(saved_user.username)
        return _to_user_response(saved_user)


@users_router.get("/policy/password")
def get_password_policy(_: dict = Depends(_get_current_payload)) -> dict:
    return {
        "minimum_length": 12,
        "maximum_length": 128,
        "requires_uppercase": True,
        "requires_lowercase": True,
        "requires_number": True,
        "requires_symbol": True,
        "lifetime_days": PASSWORD_LIFETIME_DAYS,
        "history_size": PASSWORD_HISTORY_SIZE,
        "lockout_attempts": MAX_FAILED_LOGIN_ATTEMPTS,
        "storage": "Hash unidireccional de PocketBase; historial con PBKDF2-SHA256 y sal unica",
        "password_manager": "Las claves temporales se muestran una vez y deben resguardarse en el gestor institucional autorizado",
    }


@users_router.post("/{user_id}/reset-password", response_model=PasswordResetResponse)
def reset_user_password(user_id: str, response: Response, current_user: dict = Depends(_get_current_payload)) -> PasswordResetResponse:
    if not _has_any_permission(current_user, {"reiniciar_credenciales"}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado para reiniciar credenciales")
    with _account_write(user_id) as user:
        if user.id == current_user.get("user_id"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Usa Mi cuenta para cambiar tu propia contrasena")
        temporary_password = _generate_temporary_password()
        _ensure_password_not_reused(user, temporary_password)
        changed_at = datetime.now(timezone.utc)
        user.password_changed_at = changed_at.isoformat()
        user.password_expires_at = password_expires_at(changed_at)
        user.must_change_password = True
        if user.google_sub or user.auth_provider == "google":
            user.auth_provider = "hybrid"
        user.failed_login_attempts = 0
        user.security_locked = False
        user.locked_at = None
        user.session_version += 1
        user_repository.change_password(user, temporary_password)
        _record_password(user, temporary_password, "administrative_reset")
        user_repository.revoke_security_sessions(user.id or "", "administrative_password_reset")
        session_cache.invalidate(user.username)
        _audit("auth.password.reset", actor_email=current_user.get("username", ""), actor_id=current_user.get("user_id", ""), target_type="user", target_id=user.id or "")
        response.headers["Cache-Control"] = "no-store"
        return PasswordResetResponse(temporary_password=temporary_password)


@users_router.post("/{user_id}/unlock", response_model=UserProfileResponse)
def unlock_user(user_id: str, current_user: dict = Depends(_get_current_payload)) -> UserProfileResponse:
    if not _has_any_permission(current_user, {"desbloquear_usuarios"}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado para desbloquear usuarios")
    with _account_write(user_id) as user:
        user.security_locked = False
        user.failed_login_attempts = 0
        user.locked_at = None
        saved = user_repository.save(user)
        session_cache.invalidate(user.username)
        _audit("auth.account.unlocked", actor_email=current_user.get("username", ""), actor_id=current_user.get("user_id", ""), target_type="user", target_id=user.id or "")
        return _to_user_response(saved)


@users_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_user(user_id: str, current_user: dict = Depends(_get_current_payload)) -> None:
    if not _has_any_permission(current_user, {"dar_baja_usuarios"}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado para dar de baja usuarios")
    with _account_write(user_id) as user:
        if user.id == current_user.get("user_id"):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No puedes dar de baja tu propia cuenta")
        user.is_active = False
        user.session_version += 1
        user_repository.save(user)
        user_repository.revoke_security_sessions(user.id or "", "account_deactivated")
        session_cache.invalidate(user.username)
        _audit("user.deactivated", actor_email=current_user.get("username", ""), actor_id=current_user.get("user_id", ""), target_type="user", target_id=user.id or "")


router.include_router(auth_router)
router.include_router(users_router)
router.include_router(security_router)
