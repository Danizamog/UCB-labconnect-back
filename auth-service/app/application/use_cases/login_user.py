from datetime import datetime, timezone

from app.domain.repositories.user_repository import UserRepository
from app.domain.password_policy import MAX_FAILED_LOGIN_ATTEMPTS
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
            known_user = self.repository.get_by_username(normalized_username)
            if known_user and known_user.auth_provider == "local" and known_user.is_active and not known_user.security_locked:
                known_user.failed_login_attempts += 1
                if known_user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
                    known_user.security_locked = True
                    known_user.locked_at = datetime.now(timezone.utc).isoformat()
                    known_user.session_version += 1
                self.repository.save(known_user)
            raise ValueError("Cuenta no reconocida")
        if not user.is_active or user.security_locked or user.auth_provider != "local":
            raise ValueError("Cuenta no reconocida")

        if user.failed_login_attempts:
            user.failed_login_attempts = 0
            user.locked_at = None
            user = self.repository.save(user)

        role = user.role or "user"
        permissions = sorted(set(user.permissions))
        expires_at = None
        if user.password_expires_at:
            try:
                expires_at = datetime.fromisoformat(user.password_expires_at.replace("Z", "+00:00"))
            except ValueError:
                expires_at = None
        must_change_password = user.must_change_password or bool(expires_at and expires_at <= datetime.now(timezone.utc))
        return create_access_token(
            subject=user.username,
            extra_claims={
                "role": role,
                "user_id": user.id,
                "name": user.name,
                "email": user.username,
                "permissions": permissions,
                "auth_provider": "local",
                "session_version": user.session_version,
                "must_change_password": must_change_password,
                "password_expires_at": user.password_expires_at,
            },
        )
