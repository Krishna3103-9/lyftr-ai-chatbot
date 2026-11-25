"""Environment-driven configuration and the LiteLLM key pool."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class KeyConfig:
    """One API key in the failover pool.

    ``model`` is the LiteLLM model name this key is valid for. By default every
    key uses ``llm_model``; an entry in ``LLM_API_KEYS`` may override it with the
    ``model|api_key`` syntax, which lets one pool span several providers/models.
    """

    id: str
    model: str
    api_key: str


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LiteLLM / key pool -------------------------------------------------
    llm_api_keys: str = ""
    llm_model: str = "gemini/gemini-2.0-flash"
    llm_api_base: str | None = None  # optional OpenAI-compatible endpoint
    llm_temperature: float = 0.2
    llm_timeout_seconds: int = 60
    litellm_cache_type: str = "local"  # local (in-memory) or disk; "none" disables
    litellm_cache_ttl_seconds: int = 3600
    litellm_cache_dir: str = "/data/llm_cache"

    # --- Storage / HTTP -----------------------------------------------------
    database_url: str = "sqlite:///./data/app.db"
    allowed_origins: str = "http://localhost:3000"
    enable_failure_simulation: bool = False
    default_system_prompt: str = "You are a concise, helpful assistant."
    max_history_messages: int = 40
    max_message_chars: int = 4000
    max_system_prompt_chars: int = 8000

    @field_validator("llm_api_keys", "allowed_origins", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @property
    def keys(self) -> list[KeyConfig]:
        """Parse LLM_API_KEYS into an ordered pool: key_1, key_2, ..."""
        pool: list[KeyConfig] = []
        for raw in self.llm_api_keys.split(","):
            entry = raw.strip()
            if not entry:
                continue
            if "|" in entry:
                model, api_key = (part.strip() for part in entry.split("|", 1))
            else:
                model, api_key = self.llm_model, entry
            if not api_key:
                continue
            pool.append(KeyConfig(id=f"key_{len(pool) + 1}", model=model or self.llm_model, api_key=api_key))
        return pool

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def cache_enabled(self) -> bool:
        return self.litellm_cache_type.strip().lower() not in {"", "none", "off", "false"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
