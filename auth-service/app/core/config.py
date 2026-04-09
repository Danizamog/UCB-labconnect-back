import os
from pathlib import Path


def _load_env_file() -> None:
    backend_root = Path(__file__).resolve().parents[3]
    env_path = backend_root / ".env"

    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()


class Settings:
    secret_key: str = os.getenv("SECRET_KEY", "change-this-secret")
    algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    token_expire_minutes: int = int(os.getenv("TOKEN_EXPIRE_MINUTES", "60"))
    default_admin_username: str = os.getenv("DEFAULT_ADMIN_USERNAME", "admin@ucb.edu.bo")
    default_admin_password: str = os.getenv("DEFAULT_ADMIN_PASSWORD", "admin123")
    institutional_email_domain: str = os.getenv("INSTITUTIONAL_EMAIL_DOMAIN", "@ucb.edu.bo").lower()
    institutional_sso_provider: str = os.getenv("INSTITUTIONAL_SSO_PROVIDER", "google_oidc" if os.getenv("GOOGLE_CLIENT_ID", "").strip() else "").strip()
    institutional_sso_button_label: str = os.getenv("INSTITUTIONAL_SSO_BUTTON_LABEL", "Continuar con cuenta institucional")
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    pocketbase_url: str = os.getenv("POCKETBASE_URL", "").strip()
    pocketbase_users_collection: str = os.getenv("POCKETBASE_USERS_COLLECTION", "users").strip() or "users"
    pocketbase_auth_identity: str = os.getenv("POCKETBASE_AUTH_IDENTITY", "").strip()
    pocketbase_auth_password: str = os.getenv("POCKETBASE_AUTH_PASSWORD", "").strip()
    pocketbase_auth_collection: str = os.getenv("POCKETBASE_AUTH_COLLECTION", "_superusers").strip() or "_superusers"
    pocketbase_timeout_seconds: float = float(os.getenv("POCKETBASE_TIMEOUT_SECONDS", "10"))
    data_mode: str = os.getenv("DATA_MODE", "pocketbase").strip().lower() or "pocketbase"
    postgres_url: str = os.getenv("POSTGRES_URL", "").strip()
    local_data_namespace: str = os.getenv("LOCAL_DATA_NAMESPACE", "labconnect").strip() or "labconnect"


settings = Settings()
