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
        self.auth_service_url = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8101")
        self.inventory_service_url = os.getenv("INVENTORY_SERVICE_URL", "http://127.0.0.1:8003").strip().rstrip("/")
        self.secret_key = os.getenv("SECRET_KEY", "change-this-secret")
        self.algorithm = os.getenv("JWT_ALGORITHM", os.getenv("ALGORITHM", "HS256"))
        self.data_mode = os.getenv("DATA_MODE", "pocketbase").strip().lower() or "pocketbase"
        self.local_data_namespace = os.getenv("LOCAL_DATA_NAMESPACE", "labconnect").strip() or "labconnect"
        self.postgres_url = os.getenv(
            "POSTGRES_URL",
            os.getenv("DATABASE_URL", "postgresql://labconnect:labconnect@labconnect-postgres:5432/labconnect"),
        ).strip()
        self.pocketbase_url = os.getenv("POCKETBASE_URL", "").rstrip("/")
        self.pocketbase_auth_identity = os.getenv("POCKETBASE_AUTH_IDENTITY")
        self.pocketbase_auth_password = os.getenv("POCKETBASE_AUTH_PASSWORD")
        self.pocketbase_auth_collection = os.getenv("POCKETBASE_AUTH_COLLECTION", "_superusers")
        self.pocketbase_timeout_seconds = float(os.getenv("POCKETBASE_TIMEOUT_SECONDS", "10"))
        self.pb_lab_reservation_collection = os.getenv("POCKETBASE_LAB_RESERVATION_COLLECTION", "lab_reservation")
        self.pb_lab_schedule_collection = os.getenv("POCKETBASE_LAB_SCHEDULE_COLLECTION", "lab_schedule")
        self.pb_lab_block_collection = os.getenv("POCKETBASE_LAB_BLOCK_COLLECTION", "lab_block")
        self.pb_laboratory_collection = os.getenv("POCKETBASE_LABORATORY_COLLECTION", "laboratory")
        self.pb_tutorial_session_collection = os.getenv("POCKETBASE_TUTORIAL_SESSION_COLLECTION", "tutorial_session")
        self.pb_tutorial_enrollment_collection = os.getenv("POCKETBASE_TUTORIAL_ENROLLMENT_COLLECTION", "tutorial_enrollment")
        self.pb_penalty_collection = os.getenv("POCKETBASE_PENALTY_COLLECTION", "user_penalty")
        self.pb_lab_access_sessions_collection = os.getenv(
            "POCKETBASE_LAB_ACCESS_SESSIONS_COLLECTION",
            "lab_access_sessions_v2",
        )
        self.smtp_host = os.getenv("SMTP_HOST", "").strip()
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_username = os.getenv("SMTP_USERNAME", "").strip()
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.smtp_sender = os.getenv("SMTP_SENDER", self.smtp_username).strip()
        self.smtp_use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}
        self.smtp_use_ssl = os.getenv("SMTP_USE_SSL", "false").strip().lower() in {"1", "true", "yes"}
        self.smtp_timeout_seconds = float(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))
        self.tutorial_sessions_storage_path = os.getenv(
            "TUTORIAL_SESSIONS_STORAGE_PATH",
            str((Path(__file__).resolve().parents[3] / "data" / "tutorial_sessions.json")),
        ).strip()


settings = Settings()
