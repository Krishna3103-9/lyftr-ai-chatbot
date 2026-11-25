from __future__ import annotations

import litellm
import pytest

from .conftest import make_response


@pytest.fixture
def completion(monkeypatch):
    calls: list[str] = []

    def fake_completion(**kwargs):
        calls.append(kwargs["api_key"])
        return make_response("Paris")

    monkeypatch.setattr(litellm, "completion", fake_completion)
    return calls


def test_simulated_429_falls_over_to_second_key(real_client, completion):
    response = real_client.post(
        "/chat",
        json={"session_id": "s-fail", "message": "capital?"},
        headers={"X-Simulate-Failure": "key_1=429"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Paris"
    assert body["metadata"]["key_id"] == "key_2"
    assert body["metadata"]["fallback_attempts"] == 1
    assert completion == ["dummy-key-2"]


def test_simulated_500_falls_over_to_second_key(real_client, completion):
    response = real_client.post(
        "/chat",
        json={"session_id": "s-fail-500", "message": "capital?"},
        headers={"X-Simulate-Failure": "key_1=500"},
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_2"


def test_all_keys_failing_returns_clean_503(real_client, completion):
    response = real_client.post(
        "/chat",
        json={"session_id": "s-all-fail", "message": "capital?"},
        headers={"X-Simulate-Failure": "*=429"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "all providers unavailable"}
    assert completion == []
    assert real_client.get("/sessions/s-all-fail/messages").status_code == 404


def test_real_provider_error_falls_over(real_client, monkeypatch):
    calls: list[str] = []

    def flaky_completion(**kwargs):
        calls.append(kwargs["api_key"])
        if len(calls) == 1:
            raise RuntimeError("simulated 429")
        return make_response("Paris")

    monkeypatch.setattr(litellm, "completion", flaky_completion)
    response = real_client.post("/chat", json={"session_id": "s-real", "message": "capital?"})
    assert response.status_code == 200
    assert response.json()["metadata"]["key_id"] == "key_2"
    assert response.json()["metadata"]["fallback_attempts"] == 1


def test_invalid_simulation_header_is_422(real_client):
    response = real_client.post(
        "/chat",
        json={"session_id": "s-invalid", "message": "hi"},
        headers={"X-Simulate-Failure": "key_1=999"},
    )
    assert response.status_code == 422
    assert "detail" in response.json()
