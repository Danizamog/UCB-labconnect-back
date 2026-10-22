import logging
import hashlib
import secrets
import string
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.container import (
    login_user_use_case,
    login_with_google_use_case,
    session_cache,
    user_repository,
    validate_token_use_case,
)
from app.core.config import settings
from app.core.identity import build_institutional_email_candidates, is_institutional_email, new_immutable_user_code
from app.domain.entities.user import User
from app.interfaces.http.schemas.auth import (
    GoogleLoginRequest,
    ForgotPasswordRequest,
    InstitutionalLoginRequest,
    InstitutionalSSOConfigResponse,
    ChangePasswordRequest,
    LoginRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.interfaces.http.schemas.user import (
    UserProfileCreateRequest,
    UserProfileCreatedResponse,
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
from app.infrastructure.security.token_provider import decode_token
from app.infrastructure.email.password_reset import is_password_reset_email_configured, send_password_reset_email

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
        password_changed_at=user.password_changed_at,
        user_code=user.user_code,
        security_locked=user.security_locked if include_security else False,
        failed_login_attempts=user.failed_login_attempts if include_security else 0,
        locked_at=user.locked_at if include_security else None,
        password_expires_at=user.password_expires_at if include_security else None,
        must_change_password=user.must_change_password if include_security else False,
    )


def _new_user_code() -> str:
    return new_immutable_user_code()


def _ensure_password_not_reused(user: User, password: str) -> None:
    for previous_hash in user_repository.list_password_hashes(user.id or "", PASSWORD_HISTORY_SIZE):
        try:
            if verify_password(password, previous_hash):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"No puedes reutilizar tus ultimas {PASSWORD_HISTORY_SIZE} contrasenas")
        except ValueError:
            continue


def _record_password(user: User, password: str, reason: str) -> None:
    user_repository.record_password_hash(user.id or "", hash_password(password), reason)


def _password_reset_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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

    role = user.role or "user"
    permissions = sorted(set(user.permissions))
    expires_at = None
    if user.password_expires_at:
        try:
            expires_at = datetime.fromisoformat(user.password_expires_at.replace("Z", "+00:00"))
        except ValueError:
            expires_at = None
    password_change_required = user.must_change_password or bool(expires_at and expires_at <= datetime.now(timezone.utc))

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
        "must_change_password": password_change_required,
        "password_expires_at": user.password_expires_at,
        "valid": True,
    }
    return {
        **base_session,
        "picture": payload.get("picture"),
        "auth_provider": user.auth_provider,
        "google_sub": payload.get("google_sub"),
        "exp": payload.get("exp"),
    }


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


def _require_profile_editor(payload: dict = Depends(_get_current_payload)) -> dict:
    if _has_any_permission(payload, {"gestionar_usuarios", "crear_usuarios"}):
        return payload
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No autorizado para crear o editar perfiles",
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
        token = login_user_use_case.execute(payload.username, payload.password)
    except ValueError as exc:
        _audit("auth.login.failed", actor_email=payload.username.strip().lower(), result="failed", reason="invalid_credentials")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    _audit("auth.login.succeeded", actor_email=payload.username.strip().lower())
    _record_session(token)
    return TokenResponse(access_token=token, expires_in=settings.token_expire_minutes * 60)


@auth_router.post("/password/forgot")
def request_password_reset(payload: ForgotPasswordRequest) -> dict:
    if not is_password_reset_email_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de correo para restablecer contrasenas no esta configurado",
        )

    email = payload.email.strip().lower()
    if is_institutional_email(email, settings.institutional_email_domain):
        user = user_repository.get_by_username(email)
        if user and user.is_active:
            token = secrets.token_urlsafe(32)
            token_hash = _password_reset_token_hash(token)
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
            user_repository.create_security_record(
                "password_reset_token",
                {
                    "user_id": user.id or "",
                    "token_hash": token_hash,
                    "expires_at": expires_at,
                    "used": False,
                },
            )
            if not send_password_reset_email(recipient=email, name=user.name, token=token):
                reset_record = user_repository.get_password_reset_token(token_hash)
                if reset_record and reset_record.get("id"):
                    user_repository.consume_password_reset_token(str(reset_record["id"]))

    return {"message": "Si la cuenta existe, enviaremos instrucciones para restablecer la contrasena."}


@auth_router.post("/password/reset")
def reset_password(payload: ResetPasswordRequest) -> dict:
    if payload.new_password != payload.new_password_confirm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La confirmacion no coincide")
    try:
        validate_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    reset_record = user_repository.get_password_reset_token(_password_reset_token_hash(payload.token))
    if not reset_record or reset_record.get("used"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El enlace no es valido o ya fue utilizado")
    try:
        expires_at = datetime.fromisoformat(str(reset_record.get("expires_at", "")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El enlace no es valido o ya fue utilizado") from exc
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El enlace ha expirado. Solicita uno nuevo.")

    user = user_repository.get_by_id(str(reset_record.get("user_id") or ""))
    if not user or not user.is_active or not user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El enlace no es valido o ya fue utilizado")

    _ensure_password_not_reused(user, payload.new_password)
    user_repository.consume_password_reset_token(str(reset_record.get("id") or ""))
    user.auth_provider = "local"
    user.password_changed_at = datetime.now(timezone.utc).isoformat()
    user.password_expires_at = password_expires_at()
    user.must_change_password = False
    user.failed_login_attempts = 0
    user.security_locked = False
    user.locked_at = None
    user.session_version += 1
    user_repository.change_password(user, payload.new_password)
    _record_password(user, payload.new_password, "password_reset")
    user_repository.consume_password_reset_tokens(user.id)
    user_repository.revoke_security_sessions(user.id, "password_reset")
    session_cache.invalidate(user.username)
    _audit("auth.password.reset_by_email", actor_email=user.username, actor_id=user.id)
    return {"message": "La contrasena se restablecio correctamente. Ya puedes iniciar sesion."}


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


@auth_router.post("/institutional", response_model=TokenResponse)
def login_with_institutional_sso(payload: InstitutionalLoginRequest) -> TokenResponse:
    try:
        token = login_with_google_use_case.execute(payload.credential)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE if "configurado" in detail else status.HTTP_401_UNAUTHORIZED
        raise HTTPException(status_code=status_code, detail=detail) from exc

    _audit("auth.sso_login.succeeded")
    _record_session(token)
    return TokenResponse(access_token=token, expires_in=settings.token_expire_minutes * 60)


@auth_router.post("/google", response_model=TokenResponse)
def login_with_google(payload: GoogleLoginRequest) -> TokenResponse:
    try:
        token = login_with_google_use_case.execute(payload.credential)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE if "configurado" in detail else status.HTTP_401_UNAUTHORIZED
        raise HTTPException(status_code=status_code, detail=detail) from exc

    _audit("auth.sso_login.succeeded")
    _record_session(token)
    return TokenResponse(access_token=token, expires_in=settings.token_expire_minutes * 60)


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


@auth_router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_own_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(_get_current_payload),
) -> None:
    if body.new_password != body.new_password_confirm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La confirmacion no coincide")
    try:
        validate_password(body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if body.current_password == body.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La nueva contrasena debe ser diferente")

    user = user_repository.get_by_id(str(current_user.get("user_id") or ""))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    if user.auth_provider != "local":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La credencial se administra con Google")
    if not user_repository.authenticate(user.username, body.current_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La contrasena actual no es correcta")

    _ensure_password_not_reused(user, body.new_password)

    user.password_changed_at = datetime.now(timezone.utc).isoformat()
    user.password_expires_at = password_expires_at()
    user.must_change_password = False
    user.failed_login_attempts = 0
    user.security_locked = False
    user.locked_at = None
    user.session_version += 1
    user_repository.change_password(user, body.new_password)
    _record_password(user, body.new_password, "self_change")
    user_repository.revoke_security_sessions(user.id or "", "password_changed")
    session_cache.invalidate(user.username)
    _audit("auth.password.changed", actor_email=user.username, actor_id=user.id or "", target_type="user", target_id=user.id or "")


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


@security_router.get("/audit-events")
def list_audit_events(page: int = 1, per_page: int = 100, _: dict = Depends(_require_security_permission("consultar_auditoria_seguridad"))) -> list[dict]:
    return user_repository.list_security_records("security_audit_event", page, per_page)


@security_router.get("/auth-events")
def list_auth_events(page: int = 1, per_page: int = 100, _: dict = Depends(_require_security_permission("consultar_eventos_autenticacion"))) -> list[dict]:
    records = user_repository.list_security_records("security_audit_event", page, min(per_page * 3, 200))
    return [record for record in records if str(record.get("action") or "").startswith("auth.")][:per_page]


@security_router.get("/sessions")
def list_sessions(page: int = 1, per_page: int = 100, _: dict = Depends(_require_security_permission("consultar_sesiones_usuarios"))) -> list[dict]:
    return user_repository.list_security_records("auth_session", page, per_page)


@security_router.get("/incidents")
def list_incidents(page: int = 1, per_page: int = 100, _: dict = Depends(_require_security_permission("consultar_incidentes_seguridad"))) -> list[dict]:
    return user_repository.list_security_records("security_incident", page, per_page)


@security_router.get("/access-reviews")
def list_access_reviews(page: int = 1, per_page: int = 100, _: dict = Depends(_require_security_permission("revisar_accesos_rbac"))) -> list[dict]:
    return user_repository.list_security_records("access_review", page, per_page)


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
    return _to_user_response(user)


@users_router.get("/{user_id}", response_model=UserProfileResponse)
def get_user(user_id: str, current_user: dict = Depends(_require_user_directory_reader)) -> UserProfileResponse:
    user = user_repository.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    include_security = _has_any_permission(current_user, {"consultar_usuarios", "desbloquear_usuarios", "reiniciar_credenciales"})
    return _to_user_response(user, include_security=include_security)


@users_router.post("/", response_model=UserProfileCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_user_profile(
    payload: UserProfileCreateRequest,
    response: Response,
    current_user: dict = Depends(_require_profile_editor),
) -> UserProfileCreatedResponse:
    profile_type = _normalize_profile_type(payload.profile_type)
    has_identity_parts = any((payload.first_name, payload.paternal_surname, payload.maternal_surname))
    if profile_type in {"student", "teacher"}:
        if not all((payload.first_name, payload.paternal_surname, payload.maternal_surname)):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Se requieren nombres y ambos apellidos para estandarizar el correo")
        try:
            candidates = build_institutional_email_candidates(
                profile_type,
                payload.first_name or "",
                payload.paternal_surname or "",
                payload.maternal_surname or "",
                settings.institutional_email_domain,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        normalized_username = next(
            (candidate for candidate in candidates if not user_repository.get_by_username(candidate)),
            "",
        )
        if not normalized_username:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Los formatos institucionales de correo ya están ocupados")
    else:
        if has_identity_parts:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La estandarizacion de correo solo aplica a estudiantes y docentes")
        normalized_username = (payload.username or "").strip().lower()
    if not is_institutional_email(normalized_username, settings.institutional_email_domain):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten correos institucionales UCB",
        )
    if user_repository.get_by_username(normalized_username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El usuario ya existe")

    temporary_password = _generate_temporary_password()
    user = user_repository.save_with_password(
        User(
            username=normalized_username,
            name=payload.name.strip(),
            profile_type=profile_type,
            phone=_normalize_optional_text(payload.phone),
            academic_page=_normalize_optional_text(payload.academic_page),
            faculty=_normalize_optional_text(payload.faculty),
            career=_normalize_optional_text(payload.career),
            student_code=_normalize_optional_text(payload.student_code),
            campus=_normalize_optional_text(payload.campus),
            bio=_normalize_optional_text(payload.bio),
            is_active=payload.is_active,
            auth_provider="local",
            user_code=_new_user_code(),
            password_changed_at=datetime.now(timezone.utc).isoformat(),
            password_expires_at=password_expires_at(),
            must_change_password=True,
        ),
        temporary_password,
    )
    _record_password(user, temporary_password, "account_created")
    session_cache.invalidate(user.username)
    _audit("user.created", actor_email=current_user.get("username", ""), actor_id=current_user.get("user_id", ""), target_type="user", target_id=user.id or "")
    response.headers["Cache-Control"] = "no-store"
    return UserProfileCreatedResponse(**_to_user_response(user, include_security=True).model_dump(), temporary_password=temporary_password)


@users_router.put("/{user_id}", response_model=UserProfileResponse)
def update_user_profile(
    user_id: str,
    payload: UserProfileUpdateRequest,
    current_user: dict = Depends(_require_profile_manager),
) -> UserProfileResponse:
    existing_user = user_repository.get_by_id(user_id)
    if not existing_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    _ensure_profile_update_permissions(current_user, existing_user, payload)

    requested_profile_type = payload.profile_type.strip().lower() if payload.profile_type else existing_user.profile_type
    if existing_user.profile_type in {"student", "teacher"} or requested_profile_type in {"student", "teacher"}:
        if payload.username is not None and payload.username.strip().lower() != existing_user.username:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El correo estandarizado de estudiantes y docentes es inmutable")
        if requested_profile_type != existing_user.profile_type:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No se puede cambiar el tipo de identidad de una cuenta existente")

    new_username = existing_user.username
    if payload.username is not None:
        normalized_username = payload.username.strip().lower()
        if not is_institutional_email(normalized_username, settings.institutional_email_domain):
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
def reset_user_password(user_id: str, current_user: dict = Depends(_get_current_payload)) -> PasswordResetResponse:
    if not _has_any_permission(current_user, {"reiniciar_credenciales"}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado para reiniciar credenciales")
    user = user_repository.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    if user.auth_provider != "local":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="La credencial de esta cuenta se administra con Google")
    if user.id == current_user.get("user_id"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Usa Mi cuenta para cambiar tu propia contrasena")
    temporary_password = _generate_temporary_password()
    _ensure_password_not_reused(user, temporary_password)
    user.password_changed_at = datetime.now(timezone.utc).isoformat()
    user.password_expires_at = password_expires_at()
    user.must_change_password = True
    user.failed_login_attempts = 0
    user.security_locked = False
    user.locked_at = None
    user.session_version += 1
    user_repository.change_password(user, temporary_password)
    _record_password(user, temporary_password, "administrative_reset")
    user_repository.revoke_security_sessions(user.id or "", "administrative_password_reset")
    session_cache.invalidate(user.username)
    _audit("auth.password.reset", actor_email=current_user.get("username", ""), actor_id=current_user.get("user_id", ""), target_type="user", target_id=user.id or "")
    return PasswordResetResponse(temporary_password=temporary_password)


@users_router.post("/{user_id}/unlock", response_model=UserProfileResponse)
def unlock_user(user_id: str, current_user: dict = Depends(_get_current_payload)) -> UserProfileResponse:
    if not _has_any_permission(current_user, {"desbloquear_usuarios"}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado para desbloquear usuarios")
    user = user_repository.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
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
    user = user_repository.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
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
