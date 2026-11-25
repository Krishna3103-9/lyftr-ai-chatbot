"""The three endpoints defined by the assignment contract."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from . import db as db_module
from .config import Settings
from .llm import AllProvidersUnavailable, LLMService
from .schemas import ChatMetadata, ChatRequest, ChatResponse, HealthResponse, HistoryResponse, MessageOut

logger = logging.getLogger("lyftr.api")
router = APIRouter()

SIMULATION_HEADER = "X-Simulate-Failure"
SIMULATION_STATUSES = {"429", "500", "502", "503"}


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_llm(request: Request) -> LLMService:
    return request.app.state.llm


def get_db(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.db_factory()
    try:
        yield session
    finally:
        session.close()


def parse_simulation_header(value: str | None, enabled: bool) -> dict[str, int]:
    """Parse ``key_1=429,key_2=500`` / ``*=429`` into {key_id: status}."""
    if not enabled or not value or not value.strip():
        return {}
    result: dict[str, int] = {}
    for part in value.split(","):
        part = part.strip()
        if not part or "=" not in part:
            raise HTTPException(status_code=422, detail=f"invalid {SIMULATION_HEADER} header")
        key_id, code = (piece.strip() for piece in part.split("=", 1))
        if key_id != "*" and not re.fullmatch(r"key_\d+", key_id):
            raise HTTPException(status_code=422, detail=f"invalid key id in {SIMULATION_HEADER} header")
        if code not in SIMULATION_STATUSES:
            raise HTTPException(status_code=422, detail=f"invalid status in {SIMULATION_HEADER} header")
        result[key_id] = int(code)
    return result


def _build_messages(default_prompt: str, stored_prompt: str | None, request_prompt: str | None,
                    history: list, new_message: str) -> list[dict[str, str]]:
    if request_prompt is not None:
        system_prompt = request_prompt
    elif stored_prompt is not None:
        system_prompt = stored_prompt
    else:
        system_prompt = default_prompt

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.extend({"role": row.role, "content": row.content} for row in history)
    messages.append({"role": "user", "content": new_message})
    return messages, system_prompt


@router.get("/health", response_model=HealthResponse)
def health(request: Request, sql: Session = Depends(get_db)) -> HealthResponse:
    settings: Settings = request.app.state.settings
    llm: LLMService = request.app.state.llm
    if not db_module.db_reachable(request.app.state.engine):
        raise HTTPException(status_code=503, detail="database unavailable")
    return HealthResponse(
        status="ok",
        keys_configured=len(settings.keys),
        cache_enabled=bool(llm.cache_enabled),
    )


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    request: Request,
    sql: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    llm: LLMService = Depends(get_llm),
) -> ChatResponse:
    started = time.perf_counter()
    simulate = parse_simulation_header(
        request.headers.get(SIMULATION_HEADER), settings.enable_failure_simulation
    )

    existing = sql.get(db_module.ChatSession, payload.session_id)
    stored_prompt = existing.system_prompt if existing is not None else None
    history = db_module.get_history(sql, payload.session_id, settings.max_history_messages)
    messages, system_prompt = _build_messages(
        settings.default_system_prompt, stored_prompt, payload.system_prompt, history, payload.message
    )

    try:
        result = llm.complete(messages, simulate=simulate)
    except AllProvidersUnavailable:
        # Failed requests never touch session history.
        raise HTTPException(status_code=503, detail="all providers unavailable") from None

    latency_ms = max(1, int((time.perf_counter() - started) * 1000))
    metadata = result.as_metadata(latency_ms)
    created_at = db_module.utc_now()

    try:
        if existing is None:
            sql.add(db_module.ChatSession(
                session_id=payload.session_id,
                system_prompt=system_prompt,
                created_at=created_at,
            ))
        elif payload.system_prompt is not None and payload.system_prompt != stored_prompt:
            existing.system_prompt = payload.system_prompt

        sql.add(db_module.Message(
            session_id=payload.session_id,
            role="user",
            content=payload.message,
            metadata=None,
            created_at=created_at,
        ))
        sql.add(db_module.Message(
            session_id=payload.session_id,
            role="assistant",
            content=result.reply,
            metadata_json=json.dumps(metadata),
            created_at=created_at,
        ))
        sql.commit()
    except Exception:
        sql.rollback()
        logger.exception("failed to persist chat for session %s", payload.session_id)
        raise HTTPException(status_code=500, detail="could not save message") from None

    return ChatResponse(session_id=payload.session_id, reply=result.reply, metadata=ChatMetadata(**metadata))


@router.get("/sessions/{session_id}/messages", response_model=HistoryResponse,
            response_model_exclude_none=True)
def get_messages(session_id: str, sql: Session = Depends(get_db)) -> HistoryResponse:
    if not db_module.session_exists(sql, session_id):
        raise HTTPException(status_code=404, detail="session not found")
    rows = db_module.get_history(sql, session_id)
    messages: list[MessageOut] = []
    for row in rows:
        item = MessageOut(role=row.role, content=row.content)
        if row.role == "assistant" and row.metadata_json:
            try:
                item.metadata = json.loads(row.metadata_json)
            except (TypeError, ValueError):
                item.metadata = None
        messages.append(item)
    return HistoryResponse(session_id=session_id, messages=messages)
