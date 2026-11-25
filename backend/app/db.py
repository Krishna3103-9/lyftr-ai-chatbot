"""SQLite schema and session helpers. No external database services."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Index, Integer, String, Text, create_engine, event, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Base(DeclarativeBase):
    pass


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_session_id_id", "session_id", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # 'user' | 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32), nullable=False)


def create_db_engine(database_url: str):
    kwargs: dict = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(database_url, **kwargs)

    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(engine) -> None:
    """Create the schema on startup, including the parent directory for file DBs."""
    url = str(engine.url)
    if url.startswith("sqlite") and ":///" in url:
        raw_path = url.split("sqlite:///", 1)[1]
        if raw_path and raw_path != ":memory:" and not raw_path.startswith("file:"):
            parent = Path(raw_path).parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)


def get_history(db: Session, session_id: str, limit: int | None = None) -> list[Message]:
    stmt = select(Message).where(Message.session_id == session_id).order_by(Message.id.asc())
    if limit is not None:
        # Keep the most recent messages while preserving chronological order.
        sub = select(Message.id).where(Message.session_id == session_id).order_by(Message.id.desc()).limit(limit).subquery()
        stmt = select(Message).where(Message.id.in_(select(sub.c.id))).order_by(Message.id.asc())
    return list(db.scalars(stmt))


def session_exists(db: Session, session_id: str) -> bool:
    if db.get(ChatSession, session_id) is not None:
        return True
    return db.scalar(select(Message.id).where(Message.session_id == session_id).limit(1)) is not None


def db_reachable(engine) -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
