from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "LabConnect Auth Service"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8001

    postgres_db: str = "labconnect"
    postgres_user: str = "labconnect_user"
    postgres_password: str = "labconnect_pass"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    database_url: str
    redis_url: str

    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 120
    google_client_id: str
    allowed_google_domain: str = "ucb.edu.bo"
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()