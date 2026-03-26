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
        self.app_name = os.getenv("INVENTORY_APP_NAME", "LabConnect Inventory Service")
        self.app_env = os.getenv("APP_ENV", "development")
        self.app_host = os.getenv("INVENTORY_APP_HOST", "0.0.0.0")
        self.app_port = int(os.getenv("INVENTORY_APP_PORT", "8003"))
        self.database_url = os.getenv("INVENTORY_DATABASE_URL", "sqlite:///./inventory.db")
        self.auth_service_url = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8101")
        self.secret_key = os.getenv("SECRET_KEY", "change-this-secret")
        self.algorithm = os.getenv("JWT_ALGORITHM", os.getenv("ALGORITHM", "HS256"))
        self.pocketbase_url = os.getenv("POCKETBASE_URL", "").rstrip("/")
        self.pocketbase_auth_token = os.getenv("POCKETBASE_AUTH_TOKEN")
        self.pocketbase_auth_identity = os.getenv("POCKETBASE_AUTH_IDENTITY")
        self.pocketbase_auth_password = os.getenv("POCKETBASE_AUTH_PASSWORD")
        self.pocketbase_auth_collection = os.getenv("POCKETBASE_AUTH_COLLECTION", "_superusers")
        self.pocketbase_timeout_seconds = float(os.getenv("POCKETBASE_TIMEOUT_SECONDS", "10"))
        self.pb_assets_collection = os.getenv("POCKETBASE_INVENTORY_ASSETS_COLLECTION", "inventory_assets_v2")
        self.pb_stock_items_collection = os.getenv("POCKETBASE_INVENTORY_STOCK_ITEMS_COLLECTION", "inventory_stock_items_v2")
        self.pb_stock_movements_collection = os.getenv(
            "POCKETBASE_INVENTORY_STOCK_MOVEMENTS_COLLECTION",
            "inventory_stock_movements_v2",
        )
        self.pb_loan_records_collection = os.getenv(
            "POCKETBASE_INVENTORY_LOAN_RECORDS_COLLECTION",
            "inventory_loan_records_v2",
        )
        self.pb_asset_status_logs_collection = os.getenv(
            "POCKETBASE_INVENTORY_ASSET_STATUS_LOGS_COLLECTION",
            "inventory_asset_status_logs_v2",
        )


settings = Settings()
