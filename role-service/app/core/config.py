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
    secret_key: str
    algorithm: str
    auth_service_url: str
    pocketbase_url: str | None
    pocketbase_role_collection: str
    pocketbase_users_collection: str
    pocketbase_auth_token: str | None
    pocketbase_auth_identity: str | None
    pocketbase_auth_password: str | None
    pocketbase_auth_collection: str
    pocketbase_timeout_seconds: float

    def __init__(self) -> None:
        self.secret_key = os.getenv("SECRET_KEY", "change-me")
        self.algorithm = os.getenv("ALGORITHM", "HS256")
        self.auth_service_url = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8101")
        self.pocketbase_url = os.getenv("POCKETBASE_URL")
        self.pocketbase_role_collection = os.getenv("POCKETBASE_ROLE_COLLECTION", "role")
        self.pocketbase_users_collection = os.getenv("POCKETBASE_USERS_COLLECTION", "users")
        self.pocketbase_auth_token = os.getenv("POCKETBASE_AUTH_TOKEN")
        self.pocketbase_auth_identity = os.getenv("POCKETBASE_AUTH_IDENTITY")
        self.pocketbase_auth_password = os.getenv("POCKETBASE_AUTH_PASSWORD")
        self.pocketbase_auth_collection = os.getenv("POCKETBASE_AUTH_COLLECTION", "_superusers")
        self.pocketbase_timeout_seconds = float(os.getenv("POCKETBASE_TIMEOUT_SECONDS", "10"))


settings = Settings()
