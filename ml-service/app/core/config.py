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
        self.app_name = os.getenv("ML_APP_NAME", "LabConnect ML Service")
        self.app_env = os.getenv("APP_ENV", "development")
        self.app_host = os.getenv("ML_APP_HOST", "0.0.0.0")
        self.app_port = int(os.getenv("ML_APP_PORT", "8007"))

        # Auth / RBAC (identical contract to the other services).
        self.auth_service_url = os.getenv("AUTH_SERVICE_URL", "http://127.0.0.1:8001")
        self.secret_key = _require_env("SECRET_KEY")
        self.algorithm = os.getenv("JWT_ALGORITHM", os.getenv("ALGORITHM", "HS256"))
        self.jwt_issuer = os.getenv("JWT_ISSUER", "labconnect-auth").strip() or "labconnect-auth"
        self.jwt_audience = os.getenv("JWT_AUDIENCE", "labconnect").strip() or "labconnect"
        self.token_cache_ttl_seconds = float(os.getenv("TOKEN_CACHE_TTL_SECONDS", "30"))
        self.token_cache_max_entries = int(os.getenv("TOKEN_CACHE_MAX_ENTRIES", "5000"))

        # PocketBase (admin client; reads collections locked with listRule null).
        self.pocketbase_url = os.getenv("POCKETBASE_URL", "").rstrip("/")
        self.pocketbase_auth_identity = os.getenv("POCKETBASE_AUTH_IDENTITY")
        self.pocketbase_auth_password = os.getenv("POCKETBASE_AUTH_PASSWORD")
        self.pocketbase_auth_collection = os.getenv("POCKETBASE_AUTH_COLLECTION", "_superusers")
        self.pocketbase_timeout_seconds = float(os.getenv("POCKETBASE_TIMEOUT_SECONDS", "10"))

        # Source collections (defaults match the live services).
        self.pb_lab_reservation_collection = os.getenv("POCKETBASE_LAB_RESERVATION_COLLECTION", "lab_reservation")
        self.pb_laboratory_collection = os.getenv("POCKETBASE_LABORATORY_COLLECTION", "laboratory")
        self.pb_stock_items_collection = os.getenv("POCKETBASE_INVENTORY_STOCK_ITEMS_COLLECTION", "stock_item")
        self.pb_supply_reservations_collection = os.getenv(
            "POCKETBASE_SUPPLY_RESERVATIONS_COLLECTION",
            "supply_reservation",
        )
        # Vista SQL (agregacion en SQLite) que acelera el panorama de insumos.
        # Su ventana de 60 dias esta fija dentro del SQL de la vista.
        self.pb_supply_demand_view = os.getenv("POCKETBASE_SUPPLY_DEMAND_VIEW", "vista_supply_demand_60d")

        # Forecast tuning.
        self.history_days = int(os.getenv("ML_HISTORY_DAYS", "120"))
        self.forecast_days = int(os.getenv("ML_FORECAST_DAYS", "14"))
        self.model_cache_ttl_seconds = float(os.getenv("ML_MODEL_CACHE_TTL_SECONDS", "900"))
        # Debe coincidir con la ventana embebida en la vista SQL (60 dias).
        self.overview_window_days = int(os.getenv("ML_OVERVIEW_WINDOW_DAYS", "60"))

        # Fase 2: caché persistente de predicciones + refresco en segundo plano.
        self.cache_collection = os.getenv("ML_CACHE_COLLECTION", "prediction_cache")
        # ~25 h: con un refresco diario en la madrugada, lo guardado sigue "fresco" todo el dia.
        self.cache_max_age_seconds = float(os.getenv("ML_CACHE_MAX_AGE_SECONDS", "90000"))
        # Cron diario en la madrugada (hora local). Sin depender de tzdata: se usa un offset.
        self.refresh_hour = int(os.getenv("ML_REFRESH_HOUR", "3"))
        self.refresh_minute = int(os.getenv("ML_REFRESH_MINUTE", "0"))
        self.refresh_tz_offset_hours = float(os.getenv("ML_REFRESH_TZ_OFFSET_HOURS", "-4"))  # Bolivia UTC-4
        # Por escalabilidad, el cron solo precalcula panorama + laboratorios (pocos). El detalle
        # de insumos (muchos) se calcula on-demand y se cachea al primer clic. Activable si se desea.
        self.precompute_supplies = os.getenv("ML_PRECOMPUTE_SUPPLIES", "false").strip().lower() in {
            "1",
            "true",
            "yes",
        }


settings = Settings()
