from app.application.use_cases.login_user import LoginUser
from app.application.use_cases.login_with_google import LoginWithGoogle
from app.application.use_cases.register_user import RegisterUser
from app.application.use_cases.validate_token import ValidateToken
from app.core.config import settings
from app.infrastructure.google.google_identity import GoogleIdentityTokenVerifier
from app.infrastructure.repositories.in_memory_user_repository import InMemoryUserRepository
from app.infrastructure.repositories.pocketbase_user_repository import PocketBaseUserRepository


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

register_user_use_case = RegisterUser(repository=user_repository)
login_user_use_case = LoginUser(repository=user_repository)
login_with_google_use_case = LoginWithGoogle(
    repository=user_repository,
    verifier=GoogleIdentityTokenVerifier(settings.google_client_id),
)
validate_token_use_case = ValidateToken()
