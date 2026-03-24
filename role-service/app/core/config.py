import os


class Settings:
    pocketbase_url: str | None
    pocketbase_collection: str
    pocketbase_auth_token: str | None
    pocketbase_timeout_seconds: float

    def __init__(self) -> None:
        self.pocketbase_url = os.getenv("POCKETBASE_URL")
        self.pocketbase_collection = os.getenv("POCKETBASE_ROLE_COLLECTION", "role")
        self.pocketbase_auth_token = os.getenv("POCKETBASE_AUTH_TOKEN")
        self.pocketbase_timeout_seconds = float(os.getenv("POCKETBASE_TIMEOUT_SECONDS", "10"))


settings = Settings()