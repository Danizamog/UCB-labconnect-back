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
        self.auth_service_url = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8101")
        self.inventory_service_url = os.getenv("INVENTORY_SERVICE_URL", "http://127.0.0.1:8003")
        self.secret_key = os.getenv("SECRET_KEY", "change-this-secret")
        self.algorithm = os.getenv("JWT_ALGORITHM", os.getenv("ALGORITHM", "HS256"))
        self.pocketbase_url = os.getenv("POCKETBASE_URL", "").rstrip("/")
        self.pocketbase_auth_identity = os.getenv("POCKETBASE_AUTH_IDENTITY")
        self.pocketbase_auth_password = os.getenv("POCKETBASE_AUTH_PASSWORD")
        self.pocketbase_auth_collection = os.getenv("POCKETBASE_AUTH_COLLECTION", "_superusers")
        self.pocketbase_timeout_seconds = float(os.getenv("POCKETBASE_TIMEOUT_SECONDS", "10"))
        self.pb_lab_reservation_collection = os.getenv("POCKETBASE_LAB_RESERVATION_COLLECTION", "lab_reservation")
        self.pb_lab_schedule_collection = os.getenv("POCKETBASE_LAB_SCHEDULE_COLLECTION", "lab_schedule")
        self.pb_lab_block_collection = os.getenv("POCKETBASE_LAB_BLOCK_COLLECTION", "lab_block")


settings = Settings()
