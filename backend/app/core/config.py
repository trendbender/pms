from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings. All secrets come from environment variables only."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: str = "development"
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://pms:pms@localhost:5432/pms"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Auth
    jwt_secret: str = "change_me"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 14

    # CORS
    cors_origins: str = "http://localhost:3000"

    # Bootstrap owner + workspace (used by the seed command)
    bootstrap_owner_email: str = "owner@example.com"
    bootstrap_owner_password: str = "owner_dev_password_change_me"
    bootstrap_owner_name: str = "Owner"
    bootstrap_workspace_name: str = "Main Workspace"

    # Storage (later sprints)
    storage_endpoint: str = ""
    storage_access_key: str = ""
    storage_secret_key: str = ""
    storage_bucket: str = ""

    # Local attachment storage (MVP — no object storage yet). Files live on a
    # mounted volume; downloads are streamed through the API with auth checks.
    attachments_dir: str = "/data/attachments"
    max_attachment_mb: int = 15

    # SMTP (later sprints)
    smtp_host: str = ""
    smtp_user: str = ""
    smtp_password: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
