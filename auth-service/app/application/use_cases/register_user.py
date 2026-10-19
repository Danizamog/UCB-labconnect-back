import secrets
from datetime import datetime, timezone

from app.core.config import settings
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository
from app.domain.password_policy import password_expires_at, validate_password
from app.infrastructure.security.password import hash_password


class RegisterUser:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def execute(self, username: str, password: str) -> User:
        validate_password(password)
        normalized_username = username.lower().strip()
        if not normalized_username.endswith(settings.institutional_email_domain):
            raise ValueError("Credenciales incorrectas")

        if self.repository.get_by_username(normalized_username):
            raise ValueError("El usuario ya existe")

        user = User(
            username=normalized_username,
            name=normalized_username.split("@")[0],
            auth_provider="local",
            user_code=f"UCB-{datetime.now(timezone.utc).year}-{secrets.token_hex(4).upper()}",
            password_changed_at=datetime.now(timezone.utc).isoformat(),
            password_expires_at=password_expires_at(),
        )
        saved = self.repository.save_with_password(user, password)
        self.repository.record_password_hash(saved.id or "", hash_password(password), "account_created")
        return saved
