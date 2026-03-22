from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LabConnect Inventory Service"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8003

    postgres_db: str = "labconnect"
    postgres_user: str = "labconnect_user"
    postgres_password: str = "labconnect_pass"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    database_url: str = "sqlite:///./inventory.db"

    secret_key: str = "super_secret_key_change_this"
    algorithm: str = "HS256"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()