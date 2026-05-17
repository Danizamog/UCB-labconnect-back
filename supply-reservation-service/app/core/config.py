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


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value or not value.strip():
        raise RuntimeError(
            f"La variable de entorno {name} es obligatoria y no esta definida. "
            "Configurala antes de iniciar el servicio."
        )
    return value.strip()


class Settings:
    def __init__(self) -> None:
        self.app_name = os.getenv("SUPPLY_RESERVATION_APP_NAME", "LabConnect Supply Reservation Service")
        self.app_host = os.getenv("SUPPLY_RESERVATION_APP_HOST", "0.0.0.0")
        self.app_port = int(os.getenv("SUPPLY_RESERVATION_APP_PORT", "8006"))
        self.auth_service_url = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8101")
        self.secret_key = _require_env("SECRET_KEY")
        self.algorithm = os.getenv("JWT_ALGORITHM", os.getenv("ALGORITHM", "HS256"))
        self.jwt_issuer = os.getenv("JWT_ISSUER", "labconnect-auth").strip() or "labconnect-auth"
        self.jwt_audience = os.getenv("JWT_AUDIENCE", "labconnect").strip() or "labconnect"
        self.token_cache_ttl_seconds = float(os.getenv("TOKEN_CACHE_TTL_SECONDS", "30"))
        self.token_cache_max_entries = int(os.getenv("TOKEN_CACHE_MAX_ENTRIES", "5000"))
        self.pocketbase_url = os.getenv("POCKETBASE_URL", "").rstrip("/")
        self.pocketbase_auth_identity = os.getenv("POCKETBASE_AUTH_IDENTITY")
        self.pocketbase_auth_password = os.getenv("POCKETBASE_AUTH_PASSWORD")
        self.pocketbase_auth_collection = os.getenv("POCKETBASE_AUTH_COLLECTION", "_superusers")
        self.pocketbase_timeout_seconds = float(os.getenv("POCKETBASE_TIMEOUT_SECONDS", "10"))
        self.pb_stock_items_collection = os.getenv("POCKETBASE_INVENTORY_STOCK_ITEMS_COLLECTION", "stock_item")
        self.pb_supply_reservations_collection = os.getenv(
            "POCKETBASE_SUPPLY_RESERVATIONS_COLLECTION",
            "supply_reservation",
        )


settings = Settings()
