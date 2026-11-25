from __future__ import annotations

from types import SimpleNamespace

import litellm
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import CompletionResult, LLMService
from app.main import create_app


class FakeLLM:
    """Deterministic stand-in for LiteLLM used by API tests."""

    def __init__(self, reply: str = "Paris", source: str = "LIVE_INFERENCE") -> None:
        self.reply = reply
        self.source = source
        self.cache_enabled = True
        self.calls: list[list[dict[str, str]]] = []

    def complete(self, messages, simulate=None):
        self.calls.append(messages)
        return CompletionResult(
            reply=self.reply,
            resolution_source=self.source,
            model="openai/test-model",
            input_tokens=21,
            output_tokens=4,
            key_id="key_1",
            fallback_attempts=0,
        )


def make_response(reply: str, *, cache_hit: bool = False, usage=(21, 4), model="openai/test-model"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
        usage=SimpleNamespace(prompt_tokens=usage[0], completion_tokens=usage[1]),
        model=model,
        _hidden_params={"cache_hit": cache_hit},
    )


@pytest.fixture
def settings(tmp_path):
    return Settings(
        llm_api_keys="dummy-key-1,dummy-key-2",
        llm_model="openai/test-model",
        database_url=f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        allowed_origins="http://localhost:3000",
        enable_failure_simulation=True,
        litellm_cache_type="none",
    )


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(settings, fake_llm):
    app = create_app(settings, llm=fake_llm)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def real_client(settings, monkeypatch):
    """Client with the real LLMService; tests monkeypatch litellm.completion."""
    monkeypatch.setattr(litellm, "cache", None)
    app = create_app(settings, llm=LLMService.from_settings(settings))
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
