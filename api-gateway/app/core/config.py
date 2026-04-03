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
    auth_service_url: str = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8101")
    inventory_service_url: str = os.getenv(
        "INVENTORY_SERVICE_URL", "http://127.0.0.1:8103"
    )
    role_service_url: str = os.getenv("ROLE_SERVICE_URL", "http://127.0.0.1:8104")
    reservations_service_url: str = os.getenv("RESERVATIONS_SERVICE_URL", "http://127.0.0.1:8005")
    supply_reservation_service_url: str = os.getenv("SUPPLY_RESERVATION_SERVICE_URL", "http://127.0.0.1:8006")
    cors_allowed_origins: list[str]

    def __init__(self) -> None:
        raw_origins = os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
        )
        self.cors_allowed_origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


settings = Settings()
