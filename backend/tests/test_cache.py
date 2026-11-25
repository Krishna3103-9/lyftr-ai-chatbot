from __future__ import annotations

import json
import time

import litellm
import pytest

from .conftest import make_response


@pytest.fixture
def caching_client(settings, monkeypatch):
    """Real LLMService + a dict standing in for LiteLLM's built-in cache."""
    settings.litellm_cache_type = "local"
    monkeypatch.setattr(litellm, "cache", None)
    from app.llm import LLMService
    from app.main import create_app
    from fastapi.testclient import TestClient

    store: dict[tuple, tuple[str, tuple[int, int]]] = {}

    def fake_completion(**kwargs):
        key = (kwargs["model"], json.dumps(kwargs["messages"], sort_keys=True))
        hit = key in store
        if not hit:
            time.sleep(0.02)  # a live call is measurably slower than a cache hit
            store[key] = ("The capital is Paris.", (31, 6))
        reply, usage = store[key]
        return make_response(reply, cache_hit=hit, usage=usage)

    monkeypatch.setattr(litellm, "completion", fake_completion)
    app = create_app(settings, llm=LLMService.from_settings(settings))
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_cache_hit_labels_tokens_and_speed(caching_client):
    import litellm

    assert litellm.cache is not None  # LiteLLM built-in cache is enabled

    first = caching_client.post("/chat", json={"session_id": "s-1", "message": "Capital of France?"})
    assert first.status_code == 200
    live = first.json()
    assert live["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert live["metadata"]["key_id"] == "key_1"

    # Same model + full message list in a brand-new session must be a cache hit.
    second = caching_client.post("/chat", json={"session_id": "s-2", "message": "Capital of France?"})
    cached = second.json()
    assert cached["reply"] == live["reply"]
    assert cached["metadata"]["resolution_source"] == "LLM_CACHE"
    assert cached["metadata"]["key_id"] is None
    assert cached["metadata"]["fallback_attempts"] == 0
    assert cached["metadata"]["input_tokens"] == live["metadata"]["input_tokens"] == 31
    assert cached["metadata"]["output_tokens"] == live["metadata"]["output_tokens"] == 6
    assert cached["metadata"]["latency_ms"] < live["metadata"]["latency_ms"]

    different = caching_client.post("/chat", json={"session_id": "s-3", "message": "Capital of Italy?"})
    assert different.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
