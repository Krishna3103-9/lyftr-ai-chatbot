"""Pydantic request/response contracts (field names are part of the API spec)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    session_id: str
    message: str
    system_prompt: str | None = None

    @field_validator("session_id", mode="before")
    @classmethod
    def _session_id(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("session_id must be a string")
        value = value.strip()
        if not 1 <= len(value) <= 128:
            raise ValueError("session_id must be 1-128 characters")
        return value

    @field_validator("message", mode="before")
    @classmethod
    def _message(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("message must be a string")
        value = value.strip()
        if not 1 <= len(value) <= 4000:
            raise ValueError("message must be 1-4000 characters after trimming")
        return value

    @field_validator("system_prompt", mode="before")
    @classmethod
    def _system_prompt(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("system_prompt must be a string")
        value = value.strip()
        if len(value) > 8000:
            raise ValueError("system_prompt must be at most 8000 characters")
        return value


class ChatMetadata(BaseModel):
    resolution_source: str
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata


class MessageOut(BaseModel):
    role: str
    content: str
    metadata: dict[str, Any] | None = None


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[MessageOut]


class HealthResponse(BaseModel):
    status: str
    keys_configured: int
    cache_enabled: bool
