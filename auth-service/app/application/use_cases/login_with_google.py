import secrets
from datetime import datetime, timezone

from app.core.config import settings
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository
from app.infrastructure.google.google_identity import GoogleIdentityTokenVerifier
from app.infrastructure.security.token_provider import create_access_token

ACCOUNT_NOT_RECOGNIZED_MESSAGE = "Cuenta no reconocida"


def _is_in_allowed_domain(email: str, configured_domain: str) -> bool:
    normalized_email = email.strip().lower()
    if "@" not in normalized_email:
        return False

    email_domain = normalized_email.split("@", 1)[1]
    normalized_domain = configured_domain.strip().lower().lstrip("@")
    if not normalized_domain:
        return False

    return email_domain == normalized_domain


class LoginWithGoogle:
    def __init__(
        self,
        repository: UserRepository,
        verifier: GoogleIdentityTokenVerifier,
    ) -> None:
        self.repository = repository
        self.verifier = verifier

    def execute(self, credential: str) -> str:
        google_user = self.verifier.verify(credential)
        username = google_user["email"]

        if not _is_in_allowed_domain(username, settings.institutional_email_domain):
            raise ValueError(ACCOUNT_NOT_RECOGNIZED_MESSAGE)

        user = self.repository.get_by_username(username)
        if not user:
            user = self.repository.save_with_password(
                User(
                    username=username,
                    name=google_user["name"],
                    role=settings.default_sso_role_name,
                    profile_type="student",
                    auth_provider="google",
                    user_code=f"UCB-{datetime.now(timezone.utc).year}-{secrets.token_hex(4).upper()}",
                ),
                secrets.token_urlsafe(24),
            )
        elif not user.is_active or user.security_locked:
            raise ValueError(ACCOUNT_NOT_RECOGNIZED_MESSAGE)
        elif google_user["name"] and google_user["name"] != user.name:
            user = self.repository.save(
                User(
                    id=user.id,
                    username=user.username,
                    name=google_user["name"],
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
                    permissions=user.permissions,
                    auth_provider="google",
                    session_version=user.session_version,
                    security_locked=user.security_locked,
                    user_code=user.user_code,
                    failed_login_attempts=user.failed_login_attempts,
                    locked_at=user.locked_at,
                    password_expires_at=None,
                    must_change_password=False,
                )
            )

        if user.auth_provider != "google":
            user.auth_provider = "google"
            user = self.repository.save(user)
            user = self.repository.change_password(user, secrets.token_urlsafe(32))

        return create_access_token(
            subject=user.username,
            extra_claims={
                "role": user.role or "user",
                "user_id": user.id,
                "name": google_user["name"],
                "email": google_user["email"],
                "picture": google_user["picture"],
                "auth_provider": "institutional_sso",
                "identity_provider": settings.institutional_sso_provider or "google_oidc",
                "google_sub": google_user["google_sub"],
                "permissions": sorted(set(user.permissions)),
                "session_version": user.session_version,
            },
        )
