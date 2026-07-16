from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from NEXUS_-prefixed environment variables."""

    model_config = SettingsConfigDict(env_prefix="NEXUS_", env_file=".env", extra="ignore")

    environment: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]
    database_url: str = "postgresql+psycopg://nexus:nexus@localhost:5432/nexus"
    # 64 hex chars (32 bytes); encrypts provider keys at rest. Never stored in DB.
    master_key: SecretStr | None = None
    # Bearer token gating every route except /healthz. Unset = API refuses requests.
    auth_token: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
