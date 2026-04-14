from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from ..memory import LayeredConversationMemory
from ..message_blocks import (
    finalize_completed_assistant_content,
    message_text,
    normalize_message_content,
)
from ..utils import now_iso


_SANDBOX_SCRIPT_MEMORY_TOOLS = frozenset(
    {
        "sandbox_write_file",
        "sandbox_edit_file",
        "sandbox_multiedit_file",
        "sandbox_run_python",
    }
)


def _normalize_sandbox_script_path(candidate: Any) -> str:
    value = str(candidate or "").strip().replace("\\", "/")
    if not value or value == ".":
        return ""
    return value


def extract_recent_sandbox_script_paths(
    messages: list["ChatMessage"], limit: int = 6
) -> list[str]:
    seen: set[str] = set()
    recent_paths: list[str] = []
    assistant_messages = [
        message
        for message in messages
        if message.role == "assistant" and message.status == "completed"
    ]

    for message in reversed(assistant_messages[-24:]):
        parts = normalize_message_content(message.content, role="assistant")
        for part in reversed(parts):
            if str(part.get("type") or "").strip().lower() != "tool_call":
                continue

            name = str(part.get("name") or "").strip().lower()
            if name not in _SANDBOX_SCRIPT_MEMORY_TOOLS:
                continue

            arguments = part.get("arguments")
            if not isinstance(arguments, dict):
                continue

            raw_path = (
                arguments.get("script_path")
                if name == "sandbox_run_python"
                else arguments.get("path")
            )
            path = _normalize_sandbox_script_path(raw_path)
            if not path.lower().endswith(".py"):
                continue

            key = path.lower()
            if key in seen:
                continue
            seen.add(key)
            recent_paths.append(path)
            if len(recent_paths) >= limit:
                return recent_paths

    return recent_paths


def message_payload_size(message: "ChatMessage") -> int:
    role = str(getattr(message, "role", "assistant"))
    content = normalize_message_content(
        getattr(message, "content", []) or [], role=role
    )
    serialized = json.dumps(content, ensure_ascii=False, sort_keys=True, default=str)
    return len(serialized) + len(getattr(message, "text_content", lambda: "")() or "")


def should_force_stream_flush(event: dict[str, Any]) -> bool:
    if bool(event.get("last")):
        return True

    for block in event.get("blocks") or []:
        if str(block.get("type") or "").strip().lower() in {
            "tool_use",
            "tool_call",
            "tool_result",
        }:
            return True

    return False


def normalize_openai_base_url(raw_url: str | None) -> str:
    value = str(raw_url or "").strip().rstrip("/")
    return value or "https://api.openai.com/v1"


def assistant_response_text(raw_content: Any) -> str:
    if isinstance(raw_content, str):
        return raw_content.strip()
    if isinstance(raw_content, list):
        parts: list[str] = []
        for item in raw_content:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    parts.append(text)
                continue
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("content") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(raw_content, dict):
        for key in ("text", "content", "output_text"):
            value = raw_content.get(key)
            if value:
                return assistant_response_text(value)
    return str(raw_content or "").strip()


def extract_json_payload(raw_text: str) -> dict[str, Any] | None:
    text = str(raw_text or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


@dataclass
class ChatMessage:
    id: str
    role: str
    content: list[dict[str, Any]] = field(default_factory=list)
    status: str = "completed"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    error: str | None = None
    order_index: int = 0
    compacted: bool = False
    token_count: int = 0

    def text_content(self) -> str:
        return message_text(self.content)

    def to_dict(self) -> dict[str, Any]:
        content = normalize_message_content(self.content, role=self.role)
        if self.role == "assistant" and self.status == "completed":
            content = finalize_completed_assistant_content(content)
        result = {
            "id": self.id,
            "object": "chat.message",
            "role": self.role,
            "status": self.status,
            "content": content,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "order_index": self.order_index,
        }
        if self.compacted:
            result["compacted"] = True
        if self.token_count > 0:
            result["token_count"] = self.token_count
        return result

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatMessage":
        role = str(payload.get("role") or "assistant")
        status = str(payload.get("status") or "completed")
        content = normalize_message_content(payload.get("content") or [], role=role)
        if role == "assistant" and status == "completed":
            content = finalize_completed_assistant_content(content)
        return cls(
            id=str(payload.get("id") or uuid4().hex),
            role=role,
            content=content,
            status=status,
            error=payload.get("error"),
            created_at=str(payload.get("created_at") or now_iso()),
            updated_at=str(payload.get("updated_at") or now_iso()),
            order_index=int(payload.get("order_index") or 0),
            compacted=bool(payload.get("compacted")),
            token_count=int(payload.get("token_count") or 0),
        )


@dataclass
class ChatSessionState:
    session_id: str
    project_id: str  # Codex-style: sessions belong to projects
    title: str
    config_path: str
    engagement_name: str | None = None
    authorization: str | None = None
    start_url: str | None = None
    allowed_hosts: list[str] = field(default_factory=list)
    allow_subdomains: bool | None = None
    engagement_notes: str | None = None
    skill_dirs: list[str] = field(default_factory=list)
    knowledge_base_ids: list[str] = field(default_factory=list)
    status: str = "idle"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    artifact_dir: str | None = None
    error: str | None = None
    memory: LayeredConversationMemory = field(default_factory=LayeredConversationMemory)
    messages: list[ChatMessage] = field(default_factory=list)
    future: Any = None
    cleanup_future: Any = None
    conversation: Any = None
    interrupt_requested: bool = False
    memory_refresh_revision: int = 0
    is_compacting: bool = False
    mode: str = "auto"

    def last_message_text(self) -> str:
        for message in reversed(self.messages):
            text = message.text_content()
            if text:
                return text
        return ""

    def summary_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.session_id,
            "object": "chat.session",
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
            "last_message": self.last_message_text(),
            "start_url": self.start_url,
            "error": self.error,
            "is_compacting": self.is_compacting,
            "mode": self.mode,
            "memory_summary": self.memory.handoff.status or self.memory.summary,
            "knowledge_base_ids": list(self.knowledge_base_ids),
            "knowledge_base_count": len(self.knowledge_base_ids),
        }
        # Include token_usage so SSE session.upsert events preserve the count
        if self.conversation is not None and hasattr(self.conversation, "cost_tracker"):
            tracker = self.conversation.cost_tracker
            if hasattr(tracker, "summary_dict"):
                model_name = self._get_model_name()
                result["token_usage"] = tracker.summary_dict(model_name=model_name)
        return result

    def _get_model_name(self) -> str:
        """Extract the model name from the conversation config if available."""
        try:
            if self.conversation is not None and hasattr(self.conversation, "config"):
                cfg = self.conversation.config
                if hasattr(cfg, "model") and hasattr(cfg.model, "model_name"):
                    return str(cfg.model.model_name or "").strip()
        except Exception:
            pass
        return ""

    def detail_dict(self) -> dict[str, Any]:
        payload = self.summary_dict()
        payload.update(
            {
                "config_path": self.config_path,
                "engagement_name": self.engagement_name,
                "authorization": self.authorization,
                "allowed_hosts": list(self.allowed_hosts),
                "allow_subdomains": self.allow_subdomains,
                "engagement_notes": self.engagement_notes,
                "skill_dirs": list(self.skill_dirs),
                "knowledge_base_ids": list(self.knowledge_base_ids),
                "artifact_dir": self.artifact_dir,
                "memory": self.memory.model_dump(),
                "messages": [message.to_dict() for message in self.messages],
            },
        )
        if self.conversation is not None and hasattr(self.conversation, "cost_tracker"):
            tracker = self.conversation.cost_tracker
            if hasattr(tracker, "summary_dict"):
                model_name = self._get_model_name()
                payload["token_usage"] = tracker.summary_dict(model_name=model_name)
        return payload

    def persistence_dict(self) -> dict[str, Any]:
        return {
            "id": self.session_id,
            "title": self.title,
            "status": self.status,
            "config_path": self.config_path,
            "engagement_name": self.engagement_name,
            "authorization": self.authorization,
            "start_url": self.start_url,
            "allowed_hosts": list(self.allowed_hosts),
            "allow_subdomains": self.allow_subdomains,
            "engagement_notes": self.engagement_notes,
            "skill_dirs": list(self.skill_dirs),
            "knowledge_base_ids": list(self.knowledge_base_ids),
            "artifact_dir": self.artifact_dir,
            "error": self.error,
            "mode": self.mode,
            "memory": self.memory.model_dump(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChatSessionState":
        messages = [
            ChatMessage.from_dict(item) for item in payload.get("messages") or []
        ]
        messages.sort(key=lambda item: (item.order_index, item.created_at, item.id))
        return cls(
            session_id=str(payload.get("id") or payload.get("session_id") or ""),
            title=str(payload.get("title") or "New Chat"),
            config_path=str(payload.get("config_path") or ""),
            engagement_name=payload.get("engagement_name"),
            authorization=payload.get("authorization"),
            start_url=payload.get("start_url"),
            allowed_hosts=list(payload.get("allowed_hosts") or []),
            allow_subdomains=payload.get("allow_subdomains"),
            engagement_notes=payload.get("engagement_notes"),
            skill_dirs=list(payload.get("skill_dirs") or []),
            knowledge_base_ids=list(payload.get("knowledge_base_ids") or []),
            status=str(payload.get("status") or "idle"),
            created_at=str(payload.get("created_at") or now_iso()),
            updated_at=str(payload.get("updated_at") or now_iso()),
            artifact_dir=payload.get("artifact_dir"),
            error=payload.get("error"),
            mode=str(payload.get("mode") or "auto"),
            memory=LayeredConversationMemory.model_validate(
                payload.get("memory") or {}
            ),
            messages=messages,
        )


@dataclass
class MemoryRefreshJob:
    session_id: str
    conversation: Any
    existing_memory: LayeredConversationMemory
    transcript_payload: list[dict[str, Any]]
    anchor_message_id: str
    revision: int


class CreateChatSessionRequest(BaseModel):
    config_path: str
    message: str = Field(min_length=1)
    engagement_name: str | None = None
    authorization: str | None = None
    start_url: str | None = None
    allowed_hosts: list[str] = Field(default_factory=list)
    allow_subdomains: bool | None = None
    engagement_notes: str | None = None
    skill_dirs: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    mode: str = "auto"


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1)


class CreateKnowledgeFromSessionRequest(BaseModel):
    knowledge_base_id: str | None = None
