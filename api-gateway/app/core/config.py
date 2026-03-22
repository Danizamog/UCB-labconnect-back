import os


class Settings:
    auth_service_url: str = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8001")
    inventory_service_url: str = os.getenv(
        "INVENTORY_SERVICE_URL", "http://inventory-service:8003"
    )


settings = Settings()
