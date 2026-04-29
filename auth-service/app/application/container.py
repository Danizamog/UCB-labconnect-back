from app.application.use_cases.login_user import LoginUser
from app.application.use_cases.login_with_google import LoginWithGoogle
from app.application.use_cases.register_user import RegisterUser
from app.application.use_cases.validate_token import ValidateToken
from app.core.config import settings
from app.domain.entities.user import User
from app.infrastructure.google.google_identity import GoogleIdentityTokenVerifier
from app.infrastructure.repositories.in_memory_user_repository import InMemoryUserRepository
from app.infrastructure.repositories.pocketbase_user_repository import PocketBaseUserRepository

DEFAULT_ADMIN_PERMISSIONS = ["*"]


def _build_user_repository() -> InMemoryUserRepository | PocketBaseUserRepository:
    if settings.pocketbase_url:
        return PocketBaseUserRepository(
            base_url=settings.pocketbase_url,
            users_collection=settings.pocketbase_users_collection,
            auth_identity=settings.pocketbase_auth_identity,
            auth_password=settings.pocketbase_auth_password,
            auth_collection=settings.pocketbase_auth_collection,
            roles_collection=settings.pocketbase_roles_collection,
            timeout_seconds=settings.pocketbase_timeout_seconds,
        )
    return InMemoryUserRepository()


user_repository = _build_user_repository()

default_admin_username = settings.default_admin_username.strip().lower()
if default_admin_username:
    existing_admin = user_repository.get_by_username(default_admin_username)
    admin_credentials_ok = user_repository.authenticate(default_admin_username, settings.default_admin_password)

    if (existing_admin and not existing_admin.is_active) or not existing_admin or not admin_credentials_ok:
        user_repository.save_with_password(
            User(
                id=existing_admin.id if existing_admin else None,
                username=default_admin_username,
                name=(existing_admin.name if existing_admin and existing_admin.name else "Administrador"),
                role="admin",
                profile_type=existing_admin.profile_type if existing_admin else "staff",
                phone=existing_admin.phone if existing_admin else None,
                academic_page=existing_admin.academic_page if existing_admin else None,
                faculty=existing_admin.faculty if existing_admin else None,
                career=existing_admin.career if existing_admin else None,
                student_code=existing_admin.student_code if existing_admin else None,
                campus=existing_admin.campus if existing_admin else None,
                bio=existing_admin.bio if existing_admin else None,
                is_active=True,
                permissions=DEFAULT_ADMIN_PERMISSIONS,
            ),
            settings.default_admin_password,
        )

register_user_use_case = RegisterUser(repository=user_repository)
login_user_use_case = LoginUser(repository=user_repository)
login_with_google_use_case = LoginWithGoogle(
    repository=user_repository,
    verifier=GoogleIdentityTokenVerifier(settings.google_client_id),
)
validate_token_use_case = ValidateToken()
