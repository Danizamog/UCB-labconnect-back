from datetime import datetime, timezone

from app.domain.entities.user import User

ACCOUNT_LOCKED_MESSAGE = (
    "Tu cuenta fue bloqueada por tres intentos fallidos. El acceso con Google y con "
    "contrasena esta bloqueado. Contacta al Administrador de Accesos para desbloquearla."
)
LOCAL_PASSWORD_PROVIDERS = {"local", "hybrid"}


class AccountLockedError(ValueError):
    def __init__(self):
        super().__init__(ACCOUNT_LOCKED_MESSAGE)


def password_change_required(user: User) -> bool:
    if user.auth_provider == "google" or user.must_change_password:
        return True
    if user.password_expires_at:
        try:
            expiry = datetime.fromisoformat(user.password_expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            return expiry <= datetime.now(timezone.utc)
        except ValueError:
            return True
    return False
