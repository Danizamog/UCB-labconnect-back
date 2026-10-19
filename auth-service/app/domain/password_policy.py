import re
from datetime import datetime, timedelta, timezone


MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
PASSWORD_LIFETIME_DAYS = 90
PASSWORD_HISTORY_SIZE = 5
MAX_FAILED_LOGIN_ATTEMPTS = 3


def validate_password(password: str) -> None:
    if not isinstance(password, str):
        raise ValueError("La contrasena es obligatoria")
    if len(password) < MIN_PASSWORD_LENGTH or len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError("La contrasena debe tener entre 12 y 128 caracteres")
    if any(ord(character) < 32 or ord(character) == 127 for character in password):
        raise ValueError("La contrasena no puede contener caracteres de control")
    if not re.search(r"[A-Z]", password):
        raise ValueError("La contrasena debe incluir al menos una letra mayuscula")
    if not re.search(r"[a-z]", password):
        raise ValueError("La contrasena debe incluir al menos una letra minuscula")
    if not re.search(r"\d", password):
        raise ValueError("La contrasena debe incluir al menos un numero")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValueError("La contrasena debe incluir al menos un simbolo")


def password_expires_at(changed_at: datetime | None = None) -> str:
    base = changed_at or datetime.now(timezone.utc)
    return (base + timedelta(days=PASSWORD_LIFETIME_DAYS)).isoformat()
