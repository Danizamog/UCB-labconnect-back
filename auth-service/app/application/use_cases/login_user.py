from datetime import datetime, timezone

from app.domain.account_security import AccountLockedError, LOCAL_PASSWORD_PROVIDERS, password_change_required
from app.domain.repositories.user_repository import UserRepository
from app.domain.password_policy import MAX_FAILED_LOGIN_ATTEMPTS
from app.infrastructure.security.token_provider import create_access_token
from app.infrastructure.security.account_locks import account_login_lock

class LoginUser:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    def execute(self, username: str, password: str) -> str:
        normalized = username.lower().strip()
        if not normalized:
            raise ValueError("Cuenta no reconocida")
        with account_login_lock(normalized):
            user = self.repository.get_by_username(normalized)
            if user and user.security_locked:
                raise AccountLockedError()
            if not user or not user.is_active or user.auth_provider not in LOCAL_PASSWORD_PROVIDERS:
                raise ValueError("Cuenta no reconocida")

            authenticated = self.repository.authenticate(normalized, password)
            if not authenticated:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
                    user.security_locked = True
                    user.locked_at = datetime.now(timezone.utc).isoformat()
                    user.session_version += 1
                self.repository.save(user)
                if user.security_locked:
                    self.repository.revoke_security_sessions(user.id or "", "three_failed_logins")
                    raise AccountLockedError()
                raise ValueError("Cuenta no reconocida")

            if user.failed_login_attempts:
                user.failed_login_attempts = 0
                user.locked_at = None
                user = self.repository.save(user)

            return create_access_token(
                subject=user.username,
                extra_claims={
                    "role": user.role or "user", "user_id": user.id, "name": user.name,
                    "email": user.username, "permissions": sorted(set(user.permissions)),
                    "auth_provider": user.auth_provider, "auth_method": "password",
                    "google_linked": bool(user.google_sub), "local_password_enabled": True,
                    "session_version": user.session_version,
                    "must_change_password": password_change_required(user),
                    "password_expires_at": user.password_expires_at,
                },
            )
