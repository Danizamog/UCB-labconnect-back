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
        self.app_name = os.getenv("RESERVATION_APP_NAME", "LabConnect Reservation Service")
        self.app_host = os.getenv("RESERVATION_APP_HOST", "0.0.0.0")
        self.app_port = int(os.getenv("RESERVATION_APP_PORT", "8005"))
        self.app_timezone = os.getenv("APP_TIMEZONE", "America/La_Paz").strip() or "America/La_Paz"
        backend_root = Path(__file__).resolve().parents[3]
        self.auth_service_url = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8101")
        self.secret_key = os.getenv("SECRET_KEY", "change-this-secret")
        self.algorithm = os.getenv("JWT_ALGORITHM", os.getenv("ALGORITHM", "HS256"))
        self.pocketbase_url = os.getenv("POCKETBASE_URL", "").rstrip("/")
        self.pocketbase_auth_identity = os.getenv("POCKETBASE_AUTH_IDENTITY")
        self.pocketbase_auth_password = os.getenv("POCKETBASE_AUTH_PASSWORD")
        self.pocketbase_auth_collection = os.getenv("POCKETBASE_AUTH_COLLECTION", "_superusers")
        self.pocketbase_timeout_seconds = float(os.getenv("POCKETBASE_TIMEOUT_SECONDS", "10"))
        self.pb_users_collection = os.getenv("POCKETBASE_USERS_COLLECTION", "users").strip() or "users"
        self.pb_lab_reservation_collection = os.getenv("POCKETBASE_LAB_RESERVATION_COLLECTION", "lab_reservation")
        self.pb_lab_schedule_collection = os.getenv("POCKETBASE_LAB_SCHEDULE_COLLECTION", "lab_schedule")
        self.pb_lab_block_collection = os.getenv("POCKETBASE_LAB_BLOCK_COLLECTION", "lab_block")
        self.pb_lab_access_sessions_collection = os.getenv(
            "POCKETBASE_LAB_ACCESS_SESSIONS_COLLECTION",
            "lab_access_sessions_v2",
        )
        self.tutorial_sessions_storage_path = (
            os.getenv(
                "TUTORIAL_SESSIONS_STORAGE_PATH",
                str(backend_root / "data" / "tutorial_sessions.json"),
            ).strip()
            or str(backend_root / "data" / "tutorial_sessions.json")
        )
        self.smtp_host = os.getenv("SMTP_HOST", "").strip()
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_username = os.getenv("SMTP_USERNAME", "").strip()
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.smtp_sender = os.getenv("SMTP_SENDER", self.smtp_username).strip()
        self.smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}
        self.smtp_use_ssl = os.getenv("SMTP_USE_SSL", "false").strip().lower() in {"1", "true", "yes"}
        self.smtp_timeout_seconds = float(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))


settings = Settings()
