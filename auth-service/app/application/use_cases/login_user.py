from app.core.config import settings
from app.domain.repositories.user_repository import UserRepository
from app.infrastructure.security.token_provider import create_access_token


class LoginUser:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def execute(self, username: str, password: str) -> str:
        normalized_username = username.lower().strip()
        if not normalized_username:
            raise ValueError("Cuenta no reconocida")

        user = self.repository.authenticate(normalized_username, password)
        if not user:
            raise ValueError("Cuenta no reconocida")
        if not user.is_active:
            raise ValueError("Cuenta no reconocida")

        is_default_admin = normalized_username == settings.default_admin_username.strip().lower()
        use_default_admin_fallback = is_default_admin and not user.role and not user.permissions
        role = user.role or (
            "admin" if use_default_admin_fallback else "user"
        )
        permissions = ["*"] if use_default_admin_fallback else sorted(set(user.permissions))
        return create_access_token(
            subject=user.username,
            extra_claims={
                "role": role,
                "user_id": user.id,
                "name": user.name,
                "email": user.username,
                "permissions": permissions,
            },
        )
