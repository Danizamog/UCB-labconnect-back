import os


class Settings:
    secret_key: str = os.getenv("SECRET_KEY", "change-this-secret")
    algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")
    token_expire_minutes: int = int(os.getenv("TOKEN_EXPIRE_MINUTES", "60"))


settings = Settings()
