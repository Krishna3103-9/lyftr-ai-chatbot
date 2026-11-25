"""LiteLLM gateway: in-memory/disk caching, key pool and automatic failover."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import litellm

from .config import KeyConfig, Settings

logger = logging.getLogger("lyftr.llm")


class AllProvidersUnavailable(Exception):
    """Raised when every key in the pool failed for a request."""


@dataclass(frozen=True)
class CompletionResult:
    reply: str
    resolution_source: str
    model: str
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int

    def as_metadata(self, latency_ms: int) -> dict[str, Any]:
        return {
            "resolution_source": self.resolution_source,
            "model": self.model,
            "latency_ms": latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "key_id": self.key_id,
            "fallback_attempts": self.fallback_attempts,
        }


class LLMService:
    """Thin wrapper around ``litellm.completion`` implementing the assignment rules.

    LiteLLM owns caching (built-in ``local``/``disk`` cache). We call it once per
    key in pool order; 429/quota/5xx (and any other provider error) advances to
    the next key. A single LiteLLM cache hit short-circuits the provider call.
    """

    def __init__(
        self,
        keys: list[KeyConfig],
        *,
        temperature: float = 0.2,
        timeout: int = 60,
        api_base: str | None = None,
        cache_type: str = "local",
        cache_ttl: int = 3600,
        cache_dir: str = "/data/llm_cache",
    ) -> None:
        self.keys = list(keys)
        self.temperature = temperature
        self.timeout = timeout
        self.api_base = api_base
        self.cache_enabled = str(cache_type).strip().lower() not in {"", "none", "off", "false"}

        if self.cache_enabled:
            kind = str(cache_type).strip().lower()
            if kind == "disk":
                litellm.cache = litellm.Cache(
                    type="disk",
                    disk_cache_dir=cache_dir,
                    default_in_memory_ttl=cache_ttl,
                )
            else:
                litellm.cache = litellm.Cache(type="local", default_in_memory_ttl=cache_ttl)
        else:
            litellm.cache = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "LLMService":
        return cls(
            settings.keys,
            temperature=settings.llm_temperature,
            timeout=settings.llm_timeout_seconds,
            api_base=settings.llm_api_base,
            cache_type=settings.litellm_cache_type,
            cache_ttl=settings.litellm_cache_ttl_seconds,
            cache_dir=settings.litellm_cache_dir,
        )

    @staticmethod
    def _simulated_status(key_id: str, simulate: dict[str, int]) -> int | None:
        if "*" in simulate:
            return simulate["*"]
        return simulate.get(key_id)

    @staticmethod
    def _extract_text(response: Any) -> str:
        choice = response.choices[0]
        content = getattr(getattr(choice, "message", None), "content", None)
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
            )
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty assistant response")
        return content.strip()

    @staticmethod
    def _extract_usage(response: Any, messages: list[dict[str, str]], reply: str) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "completion_tokens", None)
        if input_tokens is None or output_tokens is None:
            # Accurate estimates only when the provider omits usage entirely.
            try:
                input_tokens = input_tokens if input_tokens is not None else litellm.token_counter(
                    model=getattr(response, "model", "openai/gpt-3.5-turbo"), messages=messages
                )
                output_tokens = output_tokens if output_tokens is not None else litellm.token_counter(
                    model=getattr(response, "model", "openai/gpt-3.5-turbo"), text=reply
                )
            except Exception:
                input_tokens = input_tokens or 0
                output_tokens = output_tokens or 0
        return int(input_tokens), int(output_tokens)

    def complete(
        self,
        messages: list[dict[str, str]],
        simulate: dict[str, int] | None = None,
    ) -> CompletionResult:
        """Return a reply from the pool, or raise AllProvidersUnavailable."""
        simulate = simulate or {}
        failures = 0

        if not self.keys:
            raise AllProvidersUnavailable("no API keys configured")

        for key in self.keys:
            simulated = self._simulated_status(key.id, simulate)
            if simulated is not None:
                failures += 1
                logger.warning("simulated %s failure for %s (request scoped)", simulated, key.id)
                continue

            kwargs: dict[str, Any] = {
                "model": key.model,
                "messages": messages,
                "api_key": key.api_key,
                "temperature": self.temperature,
                "timeout": self.timeout,
                "caching": self.cache_enabled,
            }
            if self.api_base:
                kwargs["api_base"] = self.api_base

            try:
                response = litellm.completion(**kwargs)
                reply = self._extract_text(response)
                hidden = getattr(response, "_hidden_params", None) or {}
                cache_hit = bool(hidden.get("cache_hit", False))
                input_tokens, output_tokens = self._extract_usage(response, messages, reply)
            except Exception as exc:  # noqa: BLE001 - providers raise a wide family of errors
                failures += 1
                logger.warning("LLM call with %s failed: %s: %s", key.id, type(exc).__name__, exc)
                continue

            return CompletionResult(
                reply=reply,
                resolution_source="LLM_CACHE" if cache_hit else "LIVE_INFERENCE",
                model=key.model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                key_id=None if cache_hit else key.id,
                fallback_attempts=0 if cache_hit else failures,
            )

        raise AllProvidersUnavailable("all providers unavailable")
