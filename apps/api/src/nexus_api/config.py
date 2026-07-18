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
    # Per-provider base URL overrides (JSON object), e.g. for local
    # OpenAI-compatible servers: {"openai": "http://localhost:11434/v1"}
    provider_base_urls: dict[str, str] = {}

    # --- Context engine (Phase 2) ---
    # Embeddings run against an OpenAI-compatible /embeddings endpoint of this
    # provider (its API key must be stored in settings). 1536 dims per schema.
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    # Cheap model used for summaries, fact distillation, and the profile.
    summary_provider: str = "anthropic"
    summary_model: str = "claude-haiku-4-5"
    # Background worker cadence and retrieval budget.
    sync_interval_seconds: int = 300
    context_token_budget: int = 2000


@lru_cache
def get_settings() -> Settings:
    return Settings()
