import os


class Settings:
    auth_service_url: str = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8001")
    inventory_service_url: str = os.getenv(
        "INVENTORY_SERVICE_URL", "http://inventory-service:8003"
    )
    role_service_url: str = os.getenv("ROLE_SERVICE_URL", "http://role-service:8004")
    cors_allowed_origins: list[str]

    def __init__(self) -> None:
        raw_origins = os.getenv(
            "CORS_ALLOWED_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173",
        )
        self.cors_allowed_origins = [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


settings = Settings()
