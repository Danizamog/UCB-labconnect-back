from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.container import (
    login_with_google_use_case,
    user_repository,
    validate_token_use_case,
)
from app.core.config import settings
from app.domain.entities.user import User
from app.interfaces.http.schemas.auth import (
    GoogleLoginRequest,
    InstitutionalLoginRequest,
    InstitutionalSSOConfigResponse,
    TokenResponse,
)
from app.interfaces.http.schemas.user import (
    UserProfileCreateRequest,
    UserProfileResponse,
    UserProfileUpdateRequest,
)

INVALID_CREDENTIALS_MESSAGE = "Cuenta no reconocida"
GOOGLE_ONLY_AUTH_MESSAGE = "Solo se permite el inicio de sesion con Google institucional"
ALLOWED_PROFILE_TYPES = {"student", "teacher", "staff", "guest", "lab_manager"}
PROFILE_MUTABLE_FIELDS = (
    "username",
    "password",
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


def _to_user_response(user: User) -> UserProfileResponse:
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
    )


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

    return _build_live_session_payload(payload)


def _build_live_session_payload(payload: dict) -> dict:
    subject = str(payload.get("sub") or "").strip().lower()
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalido o expirado",
        )

    user = user_repository.get_by_username(subject)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=INVALID_CREDENTIALS_MESSAGE,
        )

    is_default_admin = subject == settings.default_admin_username.strip().lower()
    use_default_admin_fallback = is_default_admin and not user.role and not user.permissions
    role = user.role or ("admin" if use_default_admin_fallback else "user")
    permissions = ["*"] if use_default_admin_fallback else sorted(set(user.permissions))

    return {
        "sub": user.username,
        "subject": user.username,
        "user_id": user.id,
        "role": role,
        "name": user.name,
        "permissions": permissions,
        "picture": payload.get("picture"),
        "auth_provider": payload.get("auth_provider"),
        "google_sub": payload.get("google_sub"),
        "exp": payload.get("exp"),
        "valid": True,
    }


def _has_any_permission(payload: dict, required_permissions: set[str]) -> bool:
    role = str(payload.get("role") or "user").strip().lower()
    permissions = payload.get("permissions") if isinstance(payload.get("permissions"), list) else []
    return role == "admin" or "*" in permissions or bool(required_permissions.intersection(permissions))


def _require_profile_manager(payload: dict = Depends(_get_current_payload)) -> dict:
    if _has_any_permission(payload, {"gestionar_roles_permisos", "reactivar_cuentas"}):
        return payload
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No autorizado para gestionar perfiles",
    )


def _require_profile_editor(payload: dict = Depends(_get_current_payload)) -> dict:
    if _has_any_permission(payload, {"gestionar_roles_permisos"}):
        return payload
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No autorizado para crear o editar perfiles",
    )


def _ensure_reactivation_permission(payload: dict) -> None:
    if _has_any_permission(payload, {"reactivar_cuentas"}):
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
    if _has_any_permission(current_user, {"gestionar_roles_permisos"}):
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


@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
def register() -> dict:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=GOOGLE_ONLY_AUTH_MESSAGE,
    )


@auth_router.post("/login", response_model=TokenResponse)
def login() -> TokenResponse:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=GOOGLE_ONLY_AUTH_MESSAGE,
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


@auth_router.post("/institutional", response_model=TokenResponse)
def login_with_institutional_sso(payload: InstitutionalLoginRequest) -> TokenResponse:
    try:
        token = login_with_google_use_case.execute(payload.credential)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE if "configurado" in detail else status.HTTP_401_UNAUTHORIZED
        raise HTTPException(status_code=status_code, detail=detail) from exc

    return TokenResponse(access_token=token, expires_in=settings.token_expire_minutes * 60)


@auth_router.post("/google", response_model=TokenResponse)
def login_with_google(payload: GoogleLoginRequest) -> TokenResponse:
    try:
        token = login_with_google_use_case.execute(payload.credential)
    except ValueError as exc:
        detail = str(exc)
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE if "configurado" in detail else status.HTTP_401_UNAUTHORIZED
        raise HTTPException(status_code=status_code, detail=detail) from exc

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
    return {
        **resolved_payload,
        "expires_at": payload.get("exp"),
    }


@users_router.get("/", response_model=list[UserProfileResponse])
def list_users(_: dict = Depends(_require_profile_manager)) -> list[UserProfileResponse]:
    return [_to_user_response(user) for user in user_repository.list_all()]


@users_router.get("/{user_id}", response_model=UserProfileResponse)
def get_user(user_id: str, _: dict = Depends(_require_profile_manager)) -> UserProfileResponse:
    user = user_repository.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return _to_user_response(user)


@users_router.post("/", response_model=UserProfileResponse, status_code=status.HTTP_201_CREATED)
def create_user_profile(
    payload: UserProfileCreateRequest,
    _: dict = Depends(_require_profile_editor),
) -> UserProfileResponse:
    normalized_username = payload.username.strip().lower()
    if not normalized_username.endswith(settings.institutional_email_domain):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten correos institucionales UCB",
        )
    if user_repository.get_by_username(normalized_username):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El usuario ya existe")

    user = user_repository.save_with_password(
        User(
            username=normalized_username,
            name=payload.name.strip(),
            profile_type=_normalize_profile_type(payload.profile_type),
            phone=_normalize_optional_text(payload.phone),
            academic_page=_normalize_optional_text(payload.academic_page),
            faculty=_normalize_optional_text(payload.faculty),
            career=_normalize_optional_text(payload.career),
            student_code=_normalize_optional_text(payload.student_code),
            campus=_normalize_optional_text(payload.campus),
            bio=_normalize_optional_text(payload.bio),
            is_active=payload.is_active,
        ),
        payload.password,
    )
    return _to_user_response(user)


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

    new_username = existing_user.username
    if payload.username is not None:
        normalized_username = payload.username.strip().lower()
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
    )

    try:
        if payload.password:
            saved_user = user_repository.save_with_password(user_to_save, payload.password)
        else:
            saved_user = user_repository.save(user_to_save)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _to_user_response(saved_user)


router.include_router(auth_router)
router.include_router(users_router)
