from dataclasses import dataclass
from typing import Literal

from nexus_api.config import get_settings

Protocol = Literal["anthropic", "openai", "gemini"]


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    protocol: Protocol
    base_url: str


# The gateway speaks three wire protocols; every supported provider maps onto
# one of them. OpenRouter additionally routes to many more models with one key.
_PROVIDERS: dict[str, ProviderConfig] = {
    "anthropic": ProviderConfig("anthropic", "anthropic", "https://api.anthropic.com"),
    "openai": ProviderConfig("openai", "openai", "https://api.openai.com/v1"),
    "openrouter": ProviderConfig("openrouter", "openai", "https://openrouter.ai/api/v1"),
    "deepseek": ProviderConfig("deepseek", "openai", "https://api.deepseek.com/v1"),
    "gemini": ProviderConfig("gemini", "gemini", "https://generativelanguage.googleapis.com"),
}


def get_provider(name: str) -> ProviderConfig | None:
    config = _PROVIDERS.get(name)
    if config is None:
        return None
    # Base-URL overrides (NEXUS_PROVIDER_BASE_URLS) support testing against a
    # mock server and self-hosted OpenAI-compatible endpoints (Ollama, etc.).
    override = get_settings().provider_base_urls.get(name)
    if override:
        return ProviderConfig(config.name, config.protocol, override.rstrip("/"))
    return config


def supported_providers() -> list[str]:
    return sorted(_PROVIDERS)
