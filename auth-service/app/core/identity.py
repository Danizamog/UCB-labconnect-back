import re
import secrets
import unicodedata
from datetime import datetime, timezone


def normalize_identity_part(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.strip().lower())
    ascii_value = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "", ascii_value)


def is_institutional_email(email: str, domain: str) -> bool:
    normalized_email = email.strip().lower()
    normalized_domain = domain.strip().lower().lstrip("@")
    if normalized_email.count("@") != 1 or any(char.isspace() for char in normalized_email):
        return False
    local_part, email_domain = normalized_email.split("@", 1)
    return bool(local_part) and email_domain == normalized_domain


def build_institutional_email_candidates(
    profile_type: str,
    first_name: str,
    paternal_surname: str,
    maternal_surname: str,
    domain: str,
) -> list[str]:
    first_names = first_name.split()
    given = normalize_identity_part(first_names[0]) if first_names else ""
    paternal = normalize_identity_part(paternal_surname)
    maternal = normalize_identity_part(maternal_surname)
    normalized_domain = domain.strip().lower().lstrip("@")

    if not given or not paternal or not maternal or not normalized_domain:
        raise ValueError("Se requieren nombres y ambos apellidos para estandarizar el correo")

    profile = profile_type.strip().lower()
    if profile == "teacher":
        local_parts = [f"{given[0]}.{paternal}.{maternal[0]}", f"{given[0]}.{paternal}"]
    else:
        local_parts = [f"{given}.{paternal}", f"{given}.{paternal}.{maternal[0]}"]

    return [f"{local_part}@{normalized_domain}" for local_part in local_parts]


def new_immutable_user_code(now: datetime | None = None) -> str:
    year = (now or datetime.now(timezone.utc)).year
    return f"UCB-{year:04d}-{secrets.token_hex(4).upper()}"