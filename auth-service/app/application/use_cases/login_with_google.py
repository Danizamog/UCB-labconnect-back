from app.core.config import settings
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
        username = google_user["email"].strip().lower()

        if not _is_in_allowed_domain(username, settings.institutional_email_domain):
            raise ValueError(ACCOUNT_NOT_RECOGNIZED_MESSAGE)

        user = self.repository.get_by_username(username)
        if not user:
            raise ValueError(ACCOUNT_NOT_RECOGNIZED_MESSAGE)
        elif not user.is_active or user.security_locked:
            raise ValueError(ACCOUNT_NOT_RECOGNIZED_MESSAGE)
        elif google_user["name"] and google_user["name"] != user.name:
            user.name = google_user["name"]
            user = self.repository.save(user)

        return create_access_token(
            subject=user.username,
            extra_claims={
                "role": user.role or "user",
                "user_id": user.id,
                "name": google_user["name"],
                "email": username,
                "picture": google_user["picture"],
                "auth_provider": "institutional_sso",
                "identity_provider": settings.institutional_sso_provider or "google_oidc",
                "google_sub": google_user["google_sub"],
                "permissions": sorted(set(user.permissions)),
                "session_version": user.session_version,
            },
        )
