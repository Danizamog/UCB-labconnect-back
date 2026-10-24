import secrets
from dataclasses import replace
from datetime import datetime, timezone

from app.core.config import settings
from app.domain.account_security import AccountLockedError, password_change_required
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository
from app.infrastructure.google.google_identity import GoogleIdentityTokenVerifier
from app.infrastructure.security.token_provider import create_access_token
from app.infrastructure.security.account_locks import account_login_lock

ACCOUNT_NOT_RECOGNIZED_MESSAGE = "Cuenta no reconocida"


def _is_in_allowed_domain(email: str, configured_domain: str) -> bool:
    normalized_email = email.strip().lower()
    return normalized_email.count("@") == 1 and normalized_email.split("@", 1)[1] == configured_domain.strip().lower().lstrip("@")


class LoginWithGoogle:
    def __init__(self, repository: UserRepository, verifier: GoogleIdentityTokenVerifier) -> None:
        self.repository = repository
        self.verifier = verifier

    def execute(self, credential: str) -> str:
        identity = self.verifier.verify(credential)
        username = identity["email"].strip().lower()
        google_sub = str(identity.get("google_sub") or "").strip()
        if not google_sub or not _is_in_allowed_domain(username, settings.institutional_email_domain):
            raise ValueError(ACCOUNT_NOT_RECOGNIZED_MESSAGE)

        with account_login_lock(username):
            return self._login_identity(identity, username, google_sub)

    def _login_identity(self, identity: dict, username: str, google_sub: str) -> str:
        user = self.repository.get_by_username(username)
        linked = self.repository.get_by_google_sub(google_sub)
        if linked and (not user or linked.id != user.id):
            raise ValueError(ACCOUNT_NOT_RECOGNIZED_MESSAGE)
        if user and user.security_locked:
            raise AccountLockedError()
        if user and not user.is_active:
            raise ValueError(ACCOUNT_NOT_RECOGNIZED_MESSAGE)
        if user and user.google_sub and user.google_sub != google_sub:
            raise ValueError(ACCOUNT_NOT_RECOGNIZED_MESSAGE)

        if not user:
            user = self.repository.save_with_password(
                User(
                    username=username, name=identity["name"], role=settings.default_sso_role_name,
                    profile_type="student", auth_provider="google", google_sub=google_sub,
                    must_change_password=True,
                    user_code=f"UCB-{datetime.now(timezone.utc).year}-{secrets.token_hex(4).upper()}",
                ),
                secrets.token_urlsafe(48),
            )
        else:
            first_link = not user.google_sub
            provider = "hybrid" if user.auth_provider in {"local", "hybrid"} else "google"
            # Actualizar el perfil nunca reemplaza una contrasena existente.
            updated = replace(
                user, name=identity.get("name") or user.name, google_sub=google_sub,
                auth_provider=provider, must_change_password=user.must_change_password or first_link,
            )
            user = self.repository.save(updated)

        return create_access_token(
            subject=user.username,
            extra_claims={
                "role": user.role or "user", "user_id": user.id, "name": user.name,
                "email": user.username, "picture": identity.get("picture"),
                "auth_provider": user.auth_provider, "auth_method": "google",
                "auth_time": int(datetime.now(timezone.utc).timestamp()),
                "google_sub": google_sub, "permissions": sorted(set(user.permissions)),
                "session_version": user.session_version,
                "must_change_password": password_change_required(user),
                "google_linked": True, "local_password_enabled": user.auth_provider == "hybrid",
                "password_expires_at": user.password_expires_at,
            },
        )
