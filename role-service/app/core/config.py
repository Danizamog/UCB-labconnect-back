import os


class Settings:
    pocketbase_url: str | None
    pocketbase_role_collection: str
    pocketbase_users_collection: str
    pocketbase_auth_token: str | None
    pocketbase_auth_identity: str | None
    pocketbase_auth_password: str | None
    pocketbase_auth_collection: str
    pocketbase_timeout_seconds: float

    def __init__(self) -> None:
        self.pocketbase_url = os.getenv("POCKETBASE_URL")
        self.pocketbase_role_collection = os.getenv("POCKETBASE_ROLE_COLLECTION", "role")
        self.pocketbase_users_collection = os.getenv("POCKETBASE_USERS_COLLECTION", "users")
        self.pocketbase_auth_token = os.getenv("POCKETBASE_AUTH_TOKEN")
        self.pocketbase_auth_identity = os.getenv("POCKETBASE_AUTH_IDENTITY")
        self.pocketbase_auth_password = os.getenv("POCKETBASE_AUTH_PASSWORD")
        self.pocketbase_auth_collection = os.getenv("POCKETBASE_AUTH_COLLECTION", "_superusers")
        self.pocketbase_timeout_seconds = float(os.getenv("POCKETBASE_TIMEOUT_SECONDS", "10"))


settings = Settings()