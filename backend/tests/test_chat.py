from __future__ import annotations


def send(client, session_id: str, message: str, **extra):
    return client.post("/chat", json={"session_id": session_id, "message": message, **extra})


def test_chat_metadata_and_multi_turn_history(client, fake_llm):
    first = send(client, "s-1", "What is the capital of France?")
    assert first.status_code == 200
    body = first.json()
    assert body["session_id"] == "s-1"
    assert body["reply"] == "Paris"
    meta = body["metadata"]
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["model"] == "openai/test-model"
    assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] >= 1
    assert meta["input_tokens"] == 21
    assert meta["output_tokens"] == 4
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0

    second = send(client, "s-1", "And its population?")
    assert second.status_code == 200
    # The second call must include the earlier user + assistant turns.
    assert [m["role"] for m in fake_llm.calls[1]] == ["system", "user", "assistant", "user"]

    history = client.get("/sessions/s-1/messages")
    assert history.status_code == 200
    messages = history.json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert "metadata" not in messages[0]
    assert messages[1]["metadata"]["input_tokens"] == 21
    assert messages[1]["metadata"]["output_tokens"] == 4


def test_sessions_are_isolated(client):
    send(client, "s-a", "hello from A")
    assert client.get("/sessions/s-b/messages").status_code == 404
    send(client, "s-b", "hello from B")
    a = client.get("/sessions/s-a/messages").json()["messages"]
    b = client.get("/sessions/s-b/messages").json()["messages"]
    assert a[0]["content"] == "hello from A"
    assert b[0]["content"] == "hello from B"


def test_system_prompt_is_stored_for_session(client, fake_llm):
    send(client, "s-prompt", "hi", system_prompt="Answer in French.")
    send(client, "s-prompt", "again")
    assert fake_llm.calls[0][0] == {"role": "system", "content": "Answer in French."}
    assert fake_llm.calls[1][0] == {"role": "system", "content": "Answer in French."}
    history = client.get("/sessions/s-prompt/messages").json()
    assert all("system" not in str(m).lower() or m["role"] != "system" for m in history["messages"])


def test_validation_errors_and_no_history_pollution(client):
    assert client.post("/chat", json={"session_id": "", "message": "hi"}).status_code == 422
    assert client.post("/chat", json={"session_id": "s-1", "message": "   "}).status_code == 422
    assert client.post("/chat", json={"session_id": "s-1", "message": "x" * 4001}).status_code == 422
    assert client.post("/chat", json={"message": "hi"}).status_code == 422
    bad_json = client.post(
        "/chat", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert bad_json.status_code == 422
    assert "detail" in bad_json.json()
    assert client.get("/sessions/s-1/messages").status_code == 404
