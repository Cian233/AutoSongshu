from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ..config import load_project_env
from ..memory import LayeredConversationMemory
from ..message_blocks import (
    assistant_content_from_blocks,
    message_text,
    normalize_message_content,
)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _json_loads(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _normalize_message_status(raw_status: str | None) -> str:
    status = str(raw_status or "").strip().lower()
    mapping = {
        "pending": "in_progress",
        "queued": "in_progress",
        "complete": "completed",
        "completed": "completed",
        "success": "completed",
        "error": "failed",
        "failed": "failed",
        "running": "in_progress",
        "in_progress": "in_progress",
    }
    return mapping.get(status, "completed")


def _legacy_message_to_content(payload: dict[str, Any]) -> list[dict[str, Any]]:
    role = str(payload.get("role") or "assistant").strip().lower()
    content_text = str(payload.get("content") or "")
    blocks = payload.get("blocks") or []

    if role == "user":
        return normalize_message_content(
            [{"type": "input_text", "text": content_text}], role="user"
        )

    return assistant_content_from_blocks(blocks, fallback_text=content_text)


class Base(DeclarativeBase):
    pass


class ChatConversationRow(Base):
    __tablename__ = "chat_conversations"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    config_path: Mapped[str] = mapped_column(Text)
    engagement_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    authorization: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    allowed_hosts_json: Mapped[str] = mapped_column(Text, default="[]")
    allow_subdomains: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    engagement_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_dirs_json: Mapped[str] = mapped_column(Text, default="[]")
    knowledge_base_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    artifact_dir: Mapped[str | None] = mapped_column(Text, nullable=True)
    memory_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class ChatMessageRow(Base):
    __tablename__ = "chat_messages"

    message_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    order_index: Mapped[int] = mapped_column(Integer)
    content_json: Mapped[str] = mapped_column(Text, default="[]")
    text_content: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class ChatSessionStore:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        load_project_env(self.project_root)
        self.lock = threading.RLock()
        self.database_url = self._resolve_database_url()
        self.engine = self._create_engine()
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        self._ensure_schema()
        self._migrate_legacy_payload_sessions_if_needed()

    def _ensure_schema(self) -> None:
        inspector = inspect(self.engine)
        if inspector.has_table("chat_conversations"):
            columns = {
                column["name"] for column in inspector.get_columns("chat_conversations")
            }
            if "memory_json" not in columns:
                with self.engine.begin() as connection:
                    connection.execute(
                        text(
                            "ALTER TABLE chat_conversations ADD COLUMN memory_json TEXT DEFAULT '{}'"
                        )
                    )
            if "knowledge_base_ids_json" not in columns:
                with self.engine.begin() as connection:
                    connection.execute(
                        text(
                            "ALTER TABLE chat_conversations ADD COLUMN knowledge_base_ids_json TEXT DEFAULT '[]'"
                        )
                    )

    def _resolve_database_url(self) -> str:
        raw_url = (
            os.getenv("AUTOSONGSHU_CHAT_DATABASE_URL")
            or os.getenv("AUTOSONGSHU_DATABASE_URL")
            or f"sqlite:///{(self.project_root / 'data' / 'autosongshu.db').resolve().as_posix()}"
        )
        url = make_url(raw_url)
        if (
            url.drivername.startswith("sqlite")
            and url.database
            and url.database != ":memory:"
        ):
            database_path = Path(url.database)
            if not database_path.is_absolute():
                database_path = (self.project_root / database_path).resolve()
            database_path.parent.mkdir(parents=True, exist_ok=True)
            url = url.set(database=str(database_path))
            return url.render_as_string(hide_password=False)
        return raw_url

    def _create_engine(self) -> Engine:
        connect_args: dict[str, object] = {}
        if self.database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        return create_engine(self.database_url, connect_args=connect_args)

    def _serialize_session_row(
        self, row: ChatConversationRow, messages: list[ChatMessageRow]
    ) -> dict[str, Any]:
        return {
            "id": row.session_id,
            "title": row.title,
            "status": row.status,
            "config_path": row.config_path,
            "engagement_name": row.engagement_name,
            "authorization": row.authorization,
            "start_url": row.start_url,
            "allowed_hosts": _json_loads(row.allowed_hosts_json, []),
            "allow_subdomains": row.allow_subdomains,
            "engagement_notes": row.engagement_notes,
            "skill_dirs": _json_loads(row.skill_dirs_json, []),
            "knowledge_base_ids": _json_loads(row.knowledge_base_ids_json, []),
            "artifact_dir": row.artifact_dir,
            "memory": LayeredConversationMemory.model_validate(
                _json_loads(row.memory_json, {})
            ).model_dump(),
            "error": row.error,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "messages": [self._serialize_message_row(item) for item in messages],
        }

    def _serialize_message_row(self, row: ChatMessageRow) -> dict[str, Any]:
        content = normalize_message_content(
            _json_loads(row.content_json, []), role=row.role
        )
        return {
            "id": row.message_id,
            "role": row.role,
            "status": row.status,
            "content": content,
            "error": row.error,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "order_index": row.order_index,
        }

    def _list_message_rows(
        self, session: Session, session_id: str
    ) -> list[ChatMessageRow]:
        return list(
            session.scalars(
                select(ChatMessageRow)
                .where(ChatMessageRow.session_id == session_id)
                .order_by(
                    ChatMessageRow.order_index.asc(), ChatMessageRow.created_at.asc()
                ),
            ).all()
        )

    def list_session_payloads(self) -> list[dict[str, Any]]:
        with self.lock, self.session_factory() as session:
            rows = session.scalars(
                select(ChatConversationRow).order_by(
                    ChatConversationRow.updated_at.desc()
                )
            ).all()
            payloads = [
                self._serialize_session_row(
                    row, self._list_message_rows(session, row.session_id)
                )
                for row in rows
            ]
        return payloads

    def get_session_payload(self, session_id: str) -> dict[str, Any] | None:
        with self.lock, self.session_factory() as session:
            row = session.get(ChatConversationRow, session_id)
            if row is None:
                return None
            return self._serialize_session_row(
                row, self._list_message_rows(session, session_id)
            )

    def upsert_session(self, payload: dict[str, Any]) -> None:
        session_id = str(payload.get("id") or payload.get("session_id") or "").strip()
        if not session_id:
            raise ValueError("Missing session id.")

        with self.lock, self.session_factory() as session:
            row = session.get(ChatConversationRow, session_id)
            if row is None:
                row = ChatConversationRow(
                    session_id=session_id,
                    title=str(payload.get("title") or session_id),
                    status=str(payload.get("status") or "idle"),
                    config_path=str(payload.get("config_path") or ""),
                    memory_json=_json_dumps(payload.get("memory") or {}),
                    created_at=str(payload.get("created_at") or ""),
                    updated_at=str(payload.get("updated_at") or ""),
                )
                session.add(row)

            row.title = str(payload.get("title") or row.title)
            row.status = str(payload.get("status") or row.status)
            row.config_path = str(payload.get("config_path") or row.config_path)
            row.engagement_name = payload.get("engagement_name")
            row.authorization = payload.get("authorization")
            row.start_url = payload.get("start_url")
            row.allowed_hosts_json = _json_dumps(
                list(payload.get("allowed_hosts") or [])
            )
            row.allow_subdomains = payload.get("allow_subdomains")
            row.engagement_notes = payload.get("engagement_notes")
            row.skill_dirs_json = _json_dumps(list(payload.get("skill_dirs") or []))
            row.knowledge_base_ids_json = _json_dumps(
                list(payload.get("knowledge_base_ids") or [])
            )
            row.artifact_dir = payload.get("artifact_dir")
            row.memory_json = _json_dumps(
                LayeredConversationMemory.model_validate(
                    payload.get("memory") or {}
                ).model_dump()
            )
            row.error = payload.get("error")
            row.created_at = str(payload.get("created_at") or row.created_at)
            row.updated_at = str(payload.get("updated_at") or row.updated_at)
            session.commit()

    def upsert_message(self, session_id: str, payload: dict[str, Any]) -> None:
        message_id = str(payload.get("id") or "").strip()
        if not message_id:
            raise ValueError("Missing message id.")

        role = str(payload.get("role") or "assistant")
        content = normalize_message_content(
            deepcopy(payload.get("content") or []), role=role
        )
        with self.lock, self.session_factory() as session:
            row = session.get(ChatMessageRow, message_id)
            if row is None:
                next_index = (
                    session.scalar(
                        select(ChatMessageRow.order_index)
                        .where(ChatMessageRow.session_id == session_id)
                        .order_by(ChatMessageRow.order_index.desc())
                        .limit(1),
                    )
                    or 0
                ) + 1
                row = ChatMessageRow(
                    message_id=message_id,
                    session_id=session_id,
                    role=role,
                    status=_normalize_message_status(
                        str(payload.get("status") or "completed")
                    ),
                    order_index=int(payload.get("order_index") or next_index),
                    created_at=str(payload.get("created_at") or ""),
                    updated_at=str(payload.get("updated_at") or ""),
                )
                session.add(row)

            row.session_id = session_id
            row.role = role
            row.status = _normalize_message_status(
                str(payload.get("status") or row.status)
            )
            row.order_index = int(payload.get("order_index") or row.order_index)
            row.content_json = _json_dumps(content)
            row.text_content = message_text(content)
            row.error = payload.get("error")
            row.created_at = str(payload.get("created_at") or row.created_at)
            row.updated_at = str(payload.get("updated_at") or row.updated_at)
            session.commit()

    def _migrate_legacy_payload_sessions_if_needed(self) -> None:
        inspector = inspect(self.engine)
        if not inspector.has_table("chat_sessions"):
            return

        with self.lock, self.session_factory() as session:
            existing = session.scalar(select(ChatConversationRow.session_id).limit(1))
            if existing is not None:
                return

            try:
                rows = (
                    session.execute(
                        text(
                            "SELECT session_id, payload_json FROM chat_sessions ORDER BY updated_at DESC"
                        ),
                    )
                    .mappings()
                    .all()
                )
            except Exception:
                return

            for row in rows:
                payload = _json_loads(str(row.get("payload_json") or ""), None)
                if not isinstance(payload, dict):
                    continue
                migrated = self._build_legacy_session_payload(payload)
                if migrated is None:
                    continue
                self._upsert_session_with_handle(session, migrated)
                for message in migrated["messages"]:
                    self._upsert_message_with_handle(session, migrated["id"], message)

            session.commit()

    def _build_legacy_session_payload(
        self, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            return None

        messages: list[dict[str, Any]] = []
        for index, raw_message in enumerate(payload.get("messages") or [], start=1):
            if not isinstance(raw_message, dict):
                continue
            messages.append(
                {
                    "id": str(raw_message.get("id") or uuid4().hex),
                    "role": str(raw_message.get("role") or "assistant"),
                    "status": _normalize_message_status(
                        str(raw_message.get("state") or "completed")
                    ),
                    "content": _legacy_message_to_content(raw_message),
                    "error": None,
                    "created_at": str(
                        raw_message.get("created_at") or payload.get("created_at") or ""
                    ),
                    "updated_at": str(
                        raw_message.get("created_at") or payload.get("updated_at") or ""
                    ),
                    "order_index": index,
                },
            )

        return {
            "id": session_id,
            "title": str(payload.get("title") or session_id),
            "status": str(payload.get("status") or "idle"),
            "config_path": str(payload.get("config_path") or ""),
            "engagement_name": payload.get("engagement_name"),
            "authorization": payload.get("authorization"),
            "start_url": payload.get("start_url"),
            "allowed_hosts": list(payload.get("allowed_hosts") or []),
            "allow_subdomains": payload.get("allow_subdomains"),
            "engagement_notes": payload.get("engagement_notes"),
            "skill_dirs": list(payload.get("skill_dirs") or []),
            "knowledge_base_ids": list(payload.get("knowledge_base_ids") or []),
            "artifact_dir": payload.get("artifact_dir"),
            "memory": LayeredConversationMemory().model_dump(),
            "error": payload.get("error"),
            "created_at": str(payload.get("created_at") or ""),
            "updated_at": str(payload.get("updated_at") or ""),
            "messages": messages,
        }

    def _upsert_session_with_handle(
        self, session: Session, payload: dict[str, Any]
    ) -> None:
        row = session.get(ChatConversationRow, payload["id"])
        if row is None:
            row = ChatConversationRow(
                session_id=payload["id"],
                title=str(payload.get("title") or payload["id"]),
                status=str(payload.get("status") or "idle"),
                config_path=str(payload.get("config_path") or ""),
                memory_json=_json_dumps(payload.get("memory") or {}),
                created_at=str(payload.get("created_at") or ""),
                updated_at=str(payload.get("updated_at") or ""),
            )
            session.add(row)

        row.title = str(payload.get("title") or row.title)
        row.status = str(payload.get("status") or row.status)
        row.config_path = str(payload.get("config_path") or row.config_path)
        row.engagement_name = payload.get("engagement_name")
        row.authorization = payload.get("authorization")
        row.start_url = payload.get("start_url")
        row.allowed_hosts_json = _json_dumps(list(payload.get("allowed_hosts") or []))
        row.allow_subdomains = payload.get("allow_subdomains")
        row.engagement_notes = payload.get("engagement_notes")
        row.skill_dirs_json = _json_dumps(list(payload.get("skill_dirs") or []))
        row.knowledge_base_ids_json = _json_dumps(
            list(payload.get("knowledge_base_ids") or [])
        )
        row.artifact_dir = payload.get("artifact_dir")
        row.memory_json = _json_dumps(
            LayeredConversationMemory.model_validate(
                payload.get("memory") or {}
            ).model_dump()
        )
        row.error = payload.get("error")
        row.created_at = str(payload.get("created_at") or row.created_at)
        row.updated_at = str(payload.get("updated_at") or row.updated_at)

    def _upsert_message_with_handle(
        self, session: Session, session_id: str, payload: dict[str, Any]
    ) -> None:
        row = session.get(ChatMessageRow, payload["id"])
        role = str(payload.get("role") or "assistant")
        content = normalize_message_content(
            deepcopy(payload.get("content") or []), role=role
        )
        if row is None:
            row = ChatMessageRow(
                message_id=payload["id"],
                session_id=session_id,
                role=role,
                status=_normalize_message_status(
                    str(payload.get("status") or "completed")
                ),
                order_index=int(payload.get("order_index") or 0),
                created_at=str(payload.get("created_at") or ""),
                updated_at=str(payload.get("updated_at") or ""),
            )
            session.add(row)

        row.session_id = session_id
        row.role = role
        row.status = _normalize_message_status(str(payload.get("status") or row.status))
        row.order_index = int(payload.get("order_index") or row.order_index)
        row.content_json = _json_dumps(content)
        row.text_content = message_text(content)
        row.error = payload.get("error")
        row.created_at = str(payload.get("created_at") or row.created_at)
        row.updated_at = str(payload.get("updated_at") or row.updated_at)

    def close(self) -> None:
        self.engine.dispose()


__all__ = ["ChatSessionStore", "ChatConversationRow", "ChatMessageRow"]
