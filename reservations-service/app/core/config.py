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
    def __init__(self) -> None:
        self.app_name = os.getenv("RESERVATIONS_APP_NAME", "LabConnect Reservations Service")
        self.app_env = os.getenv("APP_ENV", "development")
        self.database_url = os.getenv("RESERVATIONS_DATABASE_URL", "sqlite:///./reservations.db")
        self.inventory_service_url = os.getenv("INVENTORY_SERVICE_URL", "http://127.0.0.1:8103")
        self.auth_service_url = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8101")
        self.secret_key = os.getenv("SECRET_KEY", "change-this-secret")
        self.algorithm = os.getenv("JWT_ALGORITHM", os.getenv("ALGORITHM", "HS256"))
        self.pocketbase_url = os.getenv("POCKETBASE_URL", "").rstrip("/")
        self.pocketbase_auth_token = os.getenv("POCKETBASE_AUTH_TOKEN")
        self.pocketbase_auth_identity = os.getenv("POCKETBASE_AUTH_IDENTITY")
        self.pocketbase_auth_password = os.getenv("POCKETBASE_AUTH_PASSWORD")
        self.pocketbase_auth_collection = os.getenv("POCKETBASE_AUTH_COLLECTION", "_superusers")
        self.pocketbase_timeout_seconds = float(os.getenv("POCKETBASE_TIMEOUT_SECONDS", "10"))
        self.pb_areas_collection = os.getenv("POCKETBASE_RESERVATIONS_AREAS_COLLECTION", "reservations_areas")
        self.pb_labs_collection = os.getenv("POCKETBASE_RESERVATIONS_LABS_COLLECTION", "reservations_laboratories")
        self.pb_class_sessions_collection = os.getenv(
            "POCKETBASE_RESERVATIONS_CLASS_SESSIONS_COLLECTION",
            "reservations_class_sessions",
        )
        self.pb_class_tutorials_collection = os.getenv(
            "POCKETBASE_RESERVATIONS_CLASS_TUTORIALS_COLLECTION",
            "reservations_class_tutorials",
        )
        self.pb_practice_requests_collection = os.getenv(
            "POCKETBASE_RESERVATIONS_PRACTICE_REQUESTS_COLLECTION",
            "reservations_practice_requests",
        )
        self.pb_practice_materials_collection = os.getenv(
            "POCKETBASE_RESERVATIONS_PRACTICE_MATERIALS_COLLECTION",
            "reservations_practice_materials",
        )
        raw_origins = os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
        )
        self.cors_allowed_origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


settings = Settings()
