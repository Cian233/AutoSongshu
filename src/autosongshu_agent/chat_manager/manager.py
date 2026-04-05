from __future__ import annotations

import contextlib
import json
import os
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

import httpx

from ..agent import PentestConversationSession
from ..authorization_store import AuthorizationDraft, AuthorizationStore
from ..config import load_config, load_project_env
from ..knowledge_store import (
    KnowledgeBaseDraft,
    KnowledgeBaseUpdateDraft,
    KnowledgeDocumentDraft,
    KnowledgeStore,
)
from ..memory import (
    LayeredConversationMemory,
    build_memory_transcript_payload,
    completed_messages_after_anchor,
)
from ..message_blocks import (
    assistant_content_from_blocks,
    finalize_completed_assistant_content,
    merge_assistant_content,
    part_to_agent_block,
)
from ..permissions import (
    InteractivePermissionInterceptor,
    ToolPermissionContext,
    build_default_permission_context,
)
from .store import ChatSessionStore
from ..utils import (
    extract_absolute_urls,
    now_iso,
    safe_host_from_url,
    truncate_text,
)
from .models import (
    ChatMessage,
    ChatSessionState,
    CreateChatSessionRequest,
    CreateKnowledgeFromSessionRequest,
    MemoryRefreshJob,
    SendMessageRequest,
    assistant_response_text,
    extract_json_payload,
    extract_recent_sandbox_script_paths,
    message_payload_size,
    normalize_openai_base_url,
    should_force_stream_flush,
)

_STREAM_EMIT_INTERVAL = max(
    0.02, float(os.getenv("AUTOSONGSHU_STREAM_EMIT_INTERVAL", "0.05"))
)


@dataclass
class _MemoryRefreshJob:
    session_id: str
    conversation: Any
    existing_memory: LayeredConversationMemory
    transcript_payload: list[dict[str, Any]]
    anchor_message_id: str
    revision: int


class ChatSessionManager:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        load_project_env(self.project_root)
        default_config_path = str(
            os.getenv("AUTOSONGSHU_DEFAULT_CONFIG_PATH") or ""
        ).strip()
        if default_config_path:
            candidate = Path(default_config_path).expanduser()
            if not candidate.is_absolute():
                candidate = (self.project_root / candidate).resolve()
            self.default_config_path = candidate
        else:
            self.default_config_path = (
                self.project_root / "configs" / "pentest.example.yaml"
            )

        default_artifact_root = str(
            os.getenv("AUTOSONGSHU_DEFAULT_ARTIFACT_ROOT")
            or os.getenv("AUTOSONGSHU_ARTIFACT_ROOT_DIR")
            or "",
        ).strip()
        if default_artifact_root:
            artifact_root = Path(default_artifact_root).expanduser()
            if not artifact_root.is_absolute():
                artifact_root = (self.project_root / artifact_root).resolve()
            self.default_artifacts_root = artifact_root
        else:
            self.default_artifacts_root = self.project_root / "artifacts"

        self.authorization_store = AuthorizationStore(project_root=self.project_root)
        self.session_store = ChatSessionStore(project_root=self.project_root)
        self.knowledge_store = KnowledgeStore(project_root=self.project_root)
        self.default_artifacts_root.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="autosongshu-chat"
        )
        self.lock = threading.RLock()
        self.chat_sessions: dict[str, ChatSessionState] = {}
        self.counter = 0
        self.listeners: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._permission_interceptor_factory: Callable[[str], Any] | None = None
        self._load_persisted_sessions()

    def set_permission_interceptor_factory(
        self, factory: Callable[[str], Any] | None
    ) -> None:
        self._permission_interceptor_factory = factory

    def _next_session_id(self) -> str:
        with self.lock:
            self.counter += 1
            return f"chat-{self.counter:04d}"

    def _resolve_config_path(self, raw_path: str) -> str:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (self.project_root / path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        return str(path)

    def _normalize_skill_dirs(self, raw_dirs: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in raw_dirs:
            path = Path(item).expanduser()
            if not path.is_absolute():
                path = (self.project_root / path).resolve()
            normalized.append(str(path))
        return normalized

    def _normalize_knowledge_base_ids(self, raw_ids: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw_ids:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        if not normalized:
            return []
        existing = self.knowledge_store.filter_existing_base_ids(normalized)
        existing_set = set(existing)
        missing = [item for item in normalized if item not in existing_set]
        if missing:
            raise ValueError(f"Knowledge base not found: {', '.join(missing)}")
        return normalized

    def _runtime_knowledge_search(
        self,
        knowledge_base_ids: list[str],
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        normalized_ids = self.knowledge_store.filter_existing_base_ids(
            knowledge_base_ids
        )
        if not normalized_ids:
            return []
        return self.knowledge_store.search_chunks(
            normalized_ids,
            query,
            limit=max(1, min(int(limit), 20)),
        )

    def _resolve_turn_knowledge_base_ids(self, linked_ids: list[str]) -> list[str]:
        normalized_linked = [
            str(item or "").strip() for item in linked_ids if str(item or "").strip()
        ]
        if normalized_linked:
            existing_linked = self.knowledge_store.filter_existing_base_ids(
                normalized_linked
            )
            if existing_linked:
                return existing_linked

        try:
            bases = self.knowledge_store.list_bases()
        except Exception:
            return []

        resolved: list[str] = []
        seen: set[str] = set()
        for base in bases:
            base_id = str((base or {}).get("id") or "").strip()
            if not base_id or base_id in seen:
                continue
            resolved.append(base_id)
            seen.add(base_id)
        return resolved

    def _truncate_title(self, message: str, length: int = 42) -> str:
        stripped = " ".join(message.split())
        if len(stripped) <= length:
            return stripped or "New Chat"
        return f"{stripped[: length - 1]}…"

    def _persist_session_state(self, session: ChatSessionState) -> None:
        self.session_store.upsert_session(session.persistence_dict())

    def _persist_message(self, session_id: str, message: ChatMessage) -> None:
        self.session_store.upsert_message(session_id, message.to_dict())

    def _find_message(self, session: ChatSessionState, message_id: str) -> ChatMessage:
        for message in session.messages:
            if message.id == message_id:
                return message
        raise KeyError(message_id)

    def _history_message_to_agent_msg(self, message: ChatMessage) -> Any:
        role = "assistant" if message.role == "assistant" else "user"
        name = "AutoSongshu" if role == "assistant" else "operator"
        if role == "user":
            from agentscope.message import Msg

            return Msg(name=name, role=role, content=message.text_content())

        blocks = [part_to_agent_block(part) for part in message.content]
        from agentscope.message import Msg

        return Msg(name=name, role=role, content=blocks or message.text_content())

    def _session_pinned_context(self, session: ChatSessionState) -> str:
        completed_user_messages = [
            message
            for message in session.messages
            if message.role == "user" and message.status == "completed"
        ]
        initial_goal = (
            completed_user_messages[0].text_content() if completed_user_messages else ""
        )
        recent_sandbox_scripts = extract_recent_sandbox_script_paths(session.messages)
        knowledge_base_name_map = self.knowledge_store.get_base_name_map(
            session.knowledge_base_ids
        )
        mentioned_urls: list[str] = []
        seen_urls: set[str] = set()

        def collect_url(candidate: str | None) -> None:
            value = str(candidate or "").strip()
            if not value or value in seen_urls:
                return
            seen_urls.add(value)
            mentioned_urls.append(value)

        for message in completed_user_messages:
            for url in extract_absolute_urls(message.text_content()):
                collect_url(url)
        collect_url(session.start_url)

        lines = [
            "Pinned session context. Keep this context across turns unless the user explicitly changes scope or target.",
        ]
        if initial_goal:
            lines.append(f"- Original user task: {truncate_text(initial_goal, 500)}")
        if mentioned_urls:
            lines.append("- Exact target URLs mentioned by the user:")
            lines.extend(f"  - {url}" for url in mentioned_urls[:8])
        if session.start_url:
            lines.append(f"- Scope start URL: {session.start_url}")
        if session.allowed_hosts:
            lines.append(f"- Allowed hosts: {', '.join(session.allowed_hosts)}")
        if session.authorization:
            lines.append(f"- Authorization: {session.authorization}")
        if session.engagement_notes:
            lines.append(
                f"- Engagement notes: {truncate_text(session.engagement_notes, 240)}"
            )
        if knowledge_base_name_map:
            ordered_names = [
                knowledge_base_name_map[item]
                for item in session.knowledge_base_ids
                if item in knowledge_base_name_map
            ]
            if ordered_names:
                lines.append(f"- Linked knowledge bases: {', '.join(ordered_names)}")
                lines.append(
                    "- Use `knowledge_search` when retrieval is needed; it is no longer forced on every turn."
                )
        if recent_sandbox_scripts:
            lines.append(
                f"- Recent sandbox Python scripts already in use: {', '.join(recent_sandbox_scripts)}"
            )
            lines.append(
                "- Prefer editing and reusing these existing scripts before creating a new sandbox file when continuing the same task."
            )
        lines.append(
            "- When the current user turn is short or only provides a delta, continue using the original task and exact target URLs above."
        )
        return "\n".join(lines)

    def _auto_compaction_char_budget(self, session: ChatSessionState) -> int:
        conversation = session.conversation
        config = getattr(conversation, "config", None)
        compaction = getattr(config, "compaction", None)
        trigger_chars = int(getattr(compaction, "trigger_chars", 18000) or 18000)
        reserved_chars = int(getattr(compaction, "reserved_chars", 4000) or 4000)
        return max(2000, trigger_chars - reserved_chars)

    def _should_prune_compacted_history(self, session: ChatSessionState) -> bool:
        conversation = session.conversation
        config = getattr(conversation, "config", None)
        compaction = getattr(config, "compaction", None)
        return bool(getattr(compaction, "prune", True))

    def _compaction_min_turns(self, session: ChatSessionState) -> int:
        conversation = session.conversation
        config = getattr(conversation, "config", None)
        compaction = getattr(config, "compaction", None)
        return max(1, int(getattr(compaction, "min_turns", 4) or 4))

    def _compaction_retain_recent_turns(self, session: ChatSessionState) -> int:
        conversation = session.conversation
        config = getattr(conversation, "config", None)
        compaction = getattr(config, "compaction", None)
        return max(0, int(getattr(compaction, "retain_recent_turns", 2) or 0))

    def _should_auto_compact_session(
        self,
        session: ChatSessionState,
        pending_messages: list[ChatMessage],
    ) -> bool:
        conversation = session.conversation
        config = getattr(conversation, "config", None)
        compaction = getattr(config, "compaction", None)
        if not bool(getattr(compaction, "auto", True)):
            return False

        assistant_turns = sum(
            1 for message in pending_messages if message.role == "assistant"
        )
        if assistant_turns < self._compaction_min_turns(session):
            return False

        pending_chars = sum(
            message_payload_size(message) for message in pending_messages
        )
        max_chars = self._auto_compaction_char_budget(session)
        estimated_tokens = pending_chars // 4 + 1
        estimated_budget = max_chars // 4 + 1
        return estimated_tokens >= estimated_budget

    def _context_history_messages(
        self,
        session: ChatSessionState,
        *,
        skip_message_ids: set[str] | None = None,
    ) -> list[ChatMessage]:
        if not self._should_prune_compacted_history(session):
            skipped = skip_message_ids or set()
            return [
                message
                for message in session.messages
                if message.status == "completed" and message.id not in skipped
            ]
        return completed_messages_after_anchor(
            session.messages,
            session.memory.anchor_message_id,
            skip_message_ids=skip_message_ids,
        )

    def _split_compaction_messages(
        self,
        session: ChatSessionState,
        pending_messages: list[ChatMessage],
    ) -> tuple[list[ChatMessage], list[ChatMessage]]:
        retain_recent_turns = self._compaction_retain_recent_turns(session)
        if retain_recent_turns <= 0:
            return pending_messages, []

        assistant_indexes = [
            index
            for index, message in enumerate(pending_messages)
            if message.role == "assistant"
        ]
        if len(assistant_indexes) <= retain_recent_turns:
            return [], pending_messages

        retain_start_index = assistant_indexes[-retain_recent_turns]
        if (
            retain_start_index > 0
            and pending_messages[retain_start_index - 1].role == "user"
        ):
            retain_start_index -= 1
        return pending_messages[:retain_start_index], pending_messages[
            retain_start_index:
        ]

    def _build_memory_refresh_job(
        self,
        session: ChatSessionState,
        conversation: PentestConversationSession,
        *,
        skip_message_ids: set[str] | None = None,
        revision: int = 0,
    ) -> _MemoryRefreshJob | None:
        pending_memory_messages = self._context_history_messages(
            session, skip_message_ids=skip_message_ids
        )
        if not pending_memory_messages:
            return None
        if not self._should_auto_compact_session(session, pending_memory_messages):
            return None
        compactable_messages, _retained_messages = self._split_compaction_messages(
            session, pending_memory_messages
        )
        assistant_messages = [
            message for message in compactable_messages if message.role == "assistant"
        ]
        anchor_message_id = (
            assistant_messages[-1].id
            if assistant_messages
            else session.memory.anchor_message_id
        )
        if not compactable_messages or not anchor_message_id:
            return None

        return _MemoryRefreshJob(
            session_id=session.session_id,
            conversation=conversation,
            existing_memory=session.memory.model_copy(deep=True),
            transcript_payload=build_memory_transcript_payload(compactable_messages),
            anchor_message_id=anchor_message_id,
            revision=revision,
        )

    def _execute_memory_refresh_job(
        self, job: _MemoryRefreshJob
    ) -> LayeredConversationMemory:
        return job.conversation.refresh_memory(
            existing_memory=job.existing_memory,
            transcript_payload=job.transcript_payload,
            anchor_message_id=job.anchor_message_id,
        )

    def _refresh_session_memory(
        self,
        session: ChatSessionState,
        conversation: PentestConversationSession,
        *,
        skip_message_ids: set[str] | None = None,
    ) -> None:
        job = self._build_memory_refresh_job(
            session,
            conversation,
            skip_message_ids=skip_message_ids,
        )
        if job is None:
            return
        updated_memory = self._execute_memory_refresh_job(job)
        session.memory = updated_memory
        self._persist_session_state(session)

    def _apply_physical_compaction(
        self,
        session: ChatSessionState,
        anchor_message_id: str,
        updated_memory: LayeredConversationMemory,
    ) -> None:
        anchor_idx = -1
        for i, msg in enumerate(session.messages):
            if msg.id == anchor_message_id:
                anchor_idx = i
                break

        if anchor_idx == -1:
            return

        messages_to_delete = [m.id for m in session.messages[: anchor_idx + 1]]

        # Create a system message containing the summary
        from ..memory.compaction import get_compact_continuation_message

        continuation_text = get_compact_continuation_message(
            updated_memory.summary,
            suppress_follow_up_questions=True,
            recent_messages_preserved=True,
        )

        system_message = ChatMessage(
            id=uuid4().hex,
            role="system",
            content=[{"type": "output_text", "text": continuation_text}],
            status="completed",
            created_at=now_iso(),
            updated_at=now_iso(),
            order_index=0,
        )

        # Keep only the messages after the anchor, prepend the system message
        session.messages = [system_message] + session.messages[anchor_idx + 1 :]

        # Update order index
        for i, msg in enumerate(session.messages):
            msg.order_index = i + 1
            self._persist_message(session.session_id, msg)

        # Delete old messages from store
        self.session_store.delete_messages(session.session_id, messages_to_delete)

    def _run_post_turn_memory_refresh(self, job: _MemoryRefreshJob) -> None:
        with contextlib.suppress(Exception):
            updated_memory = self._execute_memory_refresh_job(job)
            with self.lock:
                session = self.chat_sessions.get(job.session_id)
                if session is None:
                    return
                if session.memory_refresh_revision != job.revision:
                    return
                session.memory = updated_memory
                session.is_compacting = False

                self._apply_physical_compaction(
                    session, job.anchor_message_id, updated_memory
                )
                self._persist_session_state(session)
            self._emit_session(session)
        with self.lock:
            session = self.chat_sessions.get(job.session_id)
            if session is None:
                return
            if session.memory_refresh_revision == job.revision:
                session.cleanup_future = None
                session.is_compacting = False

    def _wait_for_pending_cleanup(self, session_id: str) -> None:
        cleanup_future: Future[Any] | None = None
        with self.lock:
            session = self.chat_sessions.get(session_id)
            if session is None:
                return
            cleanup_future = session.cleanup_future
        if cleanup_future is None:
            return
        if cleanup_future.done():
            with self.lock:
                session = self.chat_sessions.get(session_id)
                if session is not None and session.cleanup_future is cleanup_future:
                    session.cleanup_future = None
                    session.is_compacting = False
            return
        with contextlib.suppress(Exception):
            cleanup_future.result()

    def _recover_interrupted_session(self, session: ChatSessionState) -> bool:
        recovered = False
        for message in session.messages:
            if message.status != "in_progress":
                continue
            recovered = True
            message.status = "failed"
            message.updated_at = now_iso()
            message.error = "会话在服务重启前中断。"
            if not message.text_content():
                message.content = [
                    {
                        "type": "output_text",
                        "text": "上一次执行在服务重启前中断，请重新发送消息继续。",
                    }
                ]

        if recovered:
            session.status = "error"
            session.error = "上一次执行在服务重启前中断，请重新发送消息继续。"
            session.updated_at = now_iso()
        return recovered

    def _load_persisted_sessions(self) -> None:
        restored_sessions = self.session_store.list_session_payloads()
        max_counter = 0
        for payload in restored_sessions:
            try:
                session = ChatSessionState.from_dict(payload)
            except Exception:
                continue
            if not session.session_id:
                continue
            recovered = self._recover_interrupted_session(session)
            self.chat_sessions[session.session_id] = session
            try:
                max_counter = max(max_counter, int(session.session_id.split("-")[-1]))
            except Exception:
                continue
            if recovered:
                self._persist_session_state(session)
                for message in session.messages:
                    self._persist_message(session.session_id, message)
        self.counter = max_counter

    def _apply_config_overrides(
        self,
        session: ChatSessionState,
        *,
        artifact_session_name: str | None = None,
    ) -> PentestConversationSession:
        config = load_config(session.config_path)
        if session.engagement_name:
            config.engagement.name = session.engagement_name
        if session.authorization:
            config.engagement.authorization = session.authorization
        if session.start_url:
            config.engagement.start_url = session.start_url
        if session.allowed_hosts:
            config.engagement.allowed_hosts = list(session.allowed_hosts)
        elif session.start_url:
            host = safe_host_from_url(session.start_url)
            if host and host not in config.engagement.allowed_hosts:
                config.engagement.allowed_hosts.append(host)
        if session.allow_subdomains is not None:
            config.engagement.allow_subdomains = session.allow_subdomains
        if session.engagement_notes is not None:
            config.engagement.notes = session.engagement_notes
        if session.skill_dirs:
            config.skills.directories.extend(session.skill_dirs)
        config.agent.mode = session.mode
        permission_interceptor = None
        if self._permission_interceptor_factory is not None:
            permission_interceptor = self._permission_interceptor_factory(
                session.session_id
            )
        return PentestConversationSession(
            config,
            artifact_session_name=artifact_session_name,
            permission_interceptor=permission_interceptor,
        )

    def _ensure_conversation_ready(
        self,
        session: ChatSessionState,
        *,
        skip_message_ids: set[str] | None = None,
    ) -> PentestConversationSession:
        if session.conversation is None:
            artifact_session_name = (
                Path(session.artifact_dir).name if session.artifact_dir else None
            )
            session.conversation = self._apply_config_overrides(
                session,
                artifact_session_name=artifact_session_name,
            )

        conversation = session.conversation
        self._refresh_session_memory(
            session, conversation, skip_message_ids=skip_message_ids
        )
        history_messages = [
            self._history_message_to_agent_msg(message)
            for message in self._context_history_messages(
                session, skip_message_ids=skip_message_ids
            )
        ]
        conversation.rebuild_context(
            history_messages,
            memory=session.memory,
            pinned_context=self._session_pinned_context(session),
        )
        session.conversation = conversation
        session.artifact_dir = str(conversation.runtime.artifacts.session_dir)
        if session.interrupt_requested:
            conversation.interrupt()
        return conversation

    def _emit(self, event_type: str, **payload: Any) -> None:
        event = {"type": event_type, "timestamp": now_iso(), **payload}
        with self.lock:
            listeners = list(self.listeners.values())
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                continue

    def _emit_session(self, session: ChatSessionState) -> None:
        self._emit("session.upsert", session=session.summary_dict())

    def _emit_message(self, session_id: str, message: ChatMessage) -> None:
        self._emit("message.upsert", session_id=session_id, message=message.to_dict())

    def add_listener(self, listener: Callable[[dict[str, Any]], None]) -> str:
        listener_id = uuid4().hex
        with self.lock:
            self.listeners[listener_id] = listener
        return listener_id

    def remove_listener(self, listener_id: str) -> None:
        with self.lock:
            self.listeners.pop(listener_id, None)

    def list_chat_sessions(self) -> list[dict[str, Any]]:
        with self.lock:
            sessions = list(self.chat_sessions.values())
        sessions.sort(key=lambda item: item.updated_at, reverse=True)
        return [item.summary_dict() for item in sessions]

    def get_chat_session(self, session_id: str) -> dict[str, Any]:
        with self.lock:
            session = self.chat_sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            return session.detail_dict()

    def interrupt_session(self, session_id: str) -> dict[str, Any]:
        with self.lock:
            session = self.chat_sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)

            future_running = session.future is not None and not session.future.done()
            if session.status == "interrupting":
                return session.detail_dict()
            if not future_running and session.status not in {"running", "interrupting"}:
                raise RuntimeError("当前会话没有正在执行的任务。")

            session.status = "interrupting"
            session.error = None
            session.updated_at = now_iso()
            session.interrupt_requested = True
            conversation = session.conversation
            self._persist_session_state(session)
            detail = session.detail_dict()

        if conversation is not None:
            conversation.interrupt()

        self._emit_session(session)
        return detail

    def list_authorizations(self) -> list[dict[str, str | bool | list[str] | None]]:
        return self.authorization_store.list_records()

    def create_authorization(
        self, payload: AuthorizationDraft
    ) -> dict[str, str | bool | list[str] | None]:
        return self.authorization_store.create_record(payload)

    def get_default_authorization_draft(self) -> dict[str, Any]:
        return {
            "name": "web-assessment",
            "authorization": "",
            "start_url": "",
            "allowed_hosts": [],
            "allow_subdomains": True,
            "notes": "",
        }

    def list_knowledge_bases(self) -> list[dict[str, Any]]:
        return self.knowledge_store.list_bases()

    def get_knowledge_base(self, knowledge_base_id: str) -> dict[str, Any]:
        return self.knowledge_store.get_base(knowledge_base_id)

    def create_knowledge_base(self, payload: KnowledgeBaseDraft) -> dict[str, Any]:
        return self.knowledge_store.create_base(payload)

    def update_knowledge_base(
        self, knowledge_base_id: str, payload: KnowledgeBaseUpdateDraft
    ) -> dict[str, Any]:
        return self.knowledge_store.update_base(knowledge_base_id, payload)

    def delete_knowledge_base(self, knowledge_base_id: str) -> None:
        self.knowledge_store.delete_base(knowledge_base_id)

    def create_knowledge_document(
        self, knowledge_base_id: str, payload: KnowledgeDocumentDraft
    ) -> dict[str, Any]:
        return self.knowledge_store.create_document(knowledge_base_id, payload)

    def get_knowledge_document(
        self, knowledge_base_id: str, document_id: str
    ) -> dict[str, Any]:
        return self.knowledge_store.get_document(knowledge_base_id, document_id)

    def delete_knowledge_document(
        self, knowledge_base_id: str, document_id: str
    ) -> None:
        self.knowledge_store.delete_document(knowledge_base_id, document_id)

    def search_knowledge_chunks(
        self,
        *,
        knowledge_base_ids: list[str],
        query: str,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        normalized_ids = self.knowledge_store.filter_existing_base_ids(
            knowledge_base_ids
        )
        if not normalized_ids:
            return []
        return self.knowledge_store.search_chunks(
            normalized_ids, query, limit=max(1, min(int(limit), 20))
        )

    def _resolve_target_knowledge_base_id(
        self, *, requested_id: str | None, linked_ids: list[str]
    ) -> str:
        normalized_requested = str(requested_id or "").strip()
        if normalized_requested:
            existing = self.knowledge_store.filter_existing_base_ids(
                [normalized_requested]
            )
            if normalized_requested not in set(existing):
                raise KeyError(f"knowledge_base:{normalized_requested}")
            return normalized_requested

        normalized_linked = [
            str(item or "").strip() for item in linked_ids if str(item or "").strip()
        ]
        if not normalized_linked:
            raise ValueError(
                "No linked knowledge base for this chat session. Please provide knowledge_base_id."
            )

        existing_linked = self.knowledge_store.filter_existing_base_ids(
            normalized_linked
        )
        if not existing_linked:
            raise ValueError(
                "Linked knowledge bases are unavailable. Please provide a valid knowledge_base_id."
            )
        return existing_linked[0]

    def _build_session_knowledge_transcript(
        self, messages: list[ChatMessage], *, max_chars: int = 18000
    ) -> str:
        lines: list[str] = []
        for message in messages:
            if message.status != "completed" or message.role not in {
                "user",
                "assistant",
            }:
                continue
            text = (
                str(message.text_content() or "")
                .strip()
                .replace("\r\n", "\n")
                .replace("\r", "\n")
            )
            if not text:
                continue
            if len(text) > 2600:
                text = f"{text[:2597]}..."
            role_name = "用户" if message.role == "user" else "助手"
            lines.append(f"{role_name}：{text}")

        if not lines:
            raise ValueError(
                "No completed conversation content found for knowledge extraction."
            )

        transcript = "\n\n".join(lines)
        if len(transcript) <= max_chars:
            return transcript

        head_limit = max(1200, int(max_chars * 0.35))
        tail_limit = max_chars - head_limit - 7
        if tail_limit <= 0:
            return transcript[:max_chars]
        return f"{transcript[:head_limit]}\n\n...\n\n{transcript[-tail_limit:]}"

    def _summarize_session_experience_with_model(
        self,
        *,
        config_path: str,
        session_id: str,
        session_title: str,
        transcript: str,
    ) -> tuple[str, str, str]:
        config = load_config(config_path)
        model_name = str(config.model.model_name or "").strip()
        if not model_name:
            raise ValueError("Model name is empty in config.")

        raw_base_url = str(config.model.base_url or "").strip()
        api_key = str(config.model.api_key or "").strip()
        if not api_key and raw_base_url:
            api_key = "EMPTY"
        if not api_key and not raw_base_url:
            raise ValueError(
                "Missing model credentials. Set AUTOSONGSHU_MODEL_API_KEY/model.api_key, "
                "or provide model.base_url for an OpenAI-compatible endpoint.",
            )

        system_prompt = "\n".join(
            [
                "你是资深漏洞复盘与知识沉淀助手。",
                "任务是把会话中的有效漏洞经验沉淀为可复用文档，重点回答：漏洞如何被引起、漏洞点在哪里。",
                '禁止臆造；对不确定信息必须标记为"待验证"。',
                "优先抽取：触发条件、脆弱点位置、证据特征、可复用检测方法与修复建议。",
                "输出要求精炼、可执行、可复用。",
            ],
        )
        user_prompt = "\n".join(
            [
                f"会话ID：{session_id}",
                f"会话标题：{session_title}",
                "",
                "请输出严格 JSON（不要代码块、不要额外解释），格式如下：",
                '{"title":"文档标题","content":"Markdown 正文"}',
                "",
                "title 规则：",
                "- 明确漏洞类型与核心场景，15-28字优先。",
                '- 避免空泛词（如"经验总结"），应可直接作为知识库索引标题。',
                "",
                "content 必须使用以下结构（保留标题层级）：",
                "## 漏洞结论",
                "- 每条包含：漏洞类型、风险等级、影响面。",
                "",
                "## 漏洞成因链路",
                '- 用"触发条件 -> 脆弱点 -> 漏洞形成 -> 影响"描述。',
                "- 若有多条链路，按可利用性从高到低排序。",
                "",
                "## 漏洞点定位",
                "- 明确定位到：页面/接口/参数/请求方法/关键配置/代码位置（若会话中有）。",
                '- 若定位信息不足，列出"待验证定位点"。',
                "",
                "## 复现与证据",
                "- 给出最小复现步骤。",
                "- 提炼关键证据：请求特征、响应特征、报错/日志线索、边界条件。",
                "",
                "## 修复与加固",
                '- 区分"立即修复"与"长期治理"。',
                "- 每项修复建议应对应一条成因或漏洞点。",
                "",
                "## 可复用检测剧本",
                "- 给出后续复测与批量排查的清单化步骤。",
                "- 明确误报排除条件与失败判据。",
                "",
                "以下是需要总结的会话记录：",
                transcript,
            ],
        )

        request_payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "top_p": min(max(float(config.model.top_p), 0.1), 1.0),
            "stream": False,
        }
        max_tokens = (
            int(config.model.max_tokens)
            if config.model.max_tokens is not None
            else 1800
        )
        request_payload["max_tokens"] = max(600, min(max_tokens, 3000))

        base_url = normalize_openai_base_url(raw_base_url)
        timeout = max(15.0, float(config.model.timeout or 120.0))

        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    f"{base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                )
                response.raise_for_status()
                response_payload = response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:400] if exc.response is not None else str(exc)
            raise RuntimeError(
                f"Knowledge summary model request failed: {detail}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Knowledge summary model request failed: {exc}"
            ) from exc

        raw_text = ""
        choices = (
            response_payload.get("choices")
            if isinstance(response_payload, dict)
            else None
        )
        if isinstance(choices, list) and choices:
            first_choice = choices[0] if isinstance(choices[0], dict) else {}
            message = (
                first_choice.get("message") if isinstance(first_choice, dict) else {}
            )
            raw_text = assistant_response_text(
                message.get("content") if isinstance(message, dict) else ""
            )
        raw_text = str(raw_text or "").strip()
        if not raw_text:
            raise RuntimeError("Knowledge summary model returned empty content.")

        parsed = extract_json_payload(raw_text)
        if parsed is not None:
            title = str(parsed.get("title") or "").strip()
            content = str(
                parsed.get("content") or parsed.get("content_markdown") or ""
            ).strip()
            if content:
                return title, content, model_name

        return "", raw_text, model_name

    def _generate_knowledge_summary_from_session(
        self,
        *,
        config_path: str,
        session_id: str,
        session_title: str,
        messages: list[ChatMessage],
    ) -> dict[str, str]:
        transcript = self._build_session_knowledge_transcript(messages)
        generated_title, generated_content, model_name = (
            self._summarize_session_experience_with_model(
                config_path=config_path,
                session_id=session_id,
                session_title=session_title,
                transcript=transcript,
            )
        )
        title = generated_title.strip()
        if not title:
            title = f"{session_title} 渗透经验沉淀"
        if len(title) > 255:
            title = title[:255]

        content = str(generated_content or "").strip()
        if not content:
            raise RuntimeError("Knowledge summary model returned empty content.")

        return {
            "title": title,
            "content": content,
            "model_name": model_name,
        }

    def create_knowledge_document_from_session(
        self,
        session_id: str,
        payload: CreateKnowledgeFromSessionRequest,
    ) -> dict[str, Any]:
        with self.lock:
            session = self.chat_sessions.get(session_id)
            if session is None:
                raise KeyError(f"chat_session:{session_id}")
            messages = list(session.messages)
            linked_ids = list(session.knowledge_base_ids)
            config_path = session.config_path
            session_title = str(
                session.title or session.session_id or session_id
            ).strip()

        target_knowledge_base_id = self._resolve_target_knowledge_base_id(
            requested_id=payload.knowledge_base_id,
            linked_ids=linked_ids,
        )
        summary = self._generate_knowledge_summary_from_session(
            config_path=config_path,
            session_id=session_id,
            session_title=session_title,
            messages=messages,
        )
        document = self.knowledge_store.create_document(
            target_knowledge_base_id,
            KnowledgeDocumentDraft(
                title=summary["title"],
                content=summary["content"],
                source_type="chat_session",
                source=f"chat_session:{session_id}",
            ),
        )
        linked_to_session = False
        session_payload: dict[str, Any] | None = None
        with self.lock:
            live_session = self.chat_sessions.get(session_id)
            if (
                live_session is not None
                and target_knowledge_base_id not in live_session.knowledge_base_ids
            ):
                live_session.knowledge_base_ids.append(target_knowledge_base_id)
                live_session.updated_at = now_iso()
                self._persist_session_state(live_session)
                session_payload = live_session.summary_dict()
                linked_to_session = True
        if session_payload is not None:
            self._emit("session.upsert", session=session_payload)

        return {
            "status": "created",
            "session_id": session_id,
            "knowledge_base_id": target_knowledge_base_id,
            "linked_to_session": linked_to_session,
            "summary_model": summary["model_name"],
            "document": document,
        }

    def create_chat_session(self, payload: CreateChatSessionRequest) -> dict[str, Any]:
        allowed_hosts = [
            item.strip().lower() for item in payload.allowed_hosts if item.strip()
        ]
        session = ChatSessionState(
            session_id=self._next_session_id(),
            title=self._truncate_title(payload.message),
            config_path=self._resolve_config_path(payload.config_path),
            engagement_name=(payload.engagement_name or "").strip() or None,
            authorization=(payload.authorization or "").strip() or None,
            start_url=(payload.start_url or "").strip() or None,
            allowed_hosts=allowed_hosts,
            allow_subdomains=payload.allow_subdomains,
            engagement_notes=(payload.engagement_notes or "").strip() or None,
            skill_dirs=self._normalize_skill_dirs(payload.skill_dirs),
            knowledge_base_ids=self._normalize_knowledge_base_ids(
                payload.knowledge_base_ids
            ),
            mode=str(payload.mode or "auto"),
        )

        with self.lock:
            self.chat_sessions[session.session_id] = session
            self._persist_session_state(session)

        self._emit_session(session)
        return self.enqueue_message(session.session_id, payload.message)

    def _handle_slash_command(self, session_id: str, content: str) -> dict[str, Any]:
        parts = content.split()
        command = parts[0].lower()

        with self.lock:
            session = self.chat_sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            if session.future is not None and not session.future.done():
                raise RuntimeError("当前会话仍在处理中，请等待上一条消息完成。")

            next_order = len(session.messages) + 1
            timestamp = now_iso()
            user_message = ChatMessage(
                id=uuid4().hex,
                role="user",
                content=[{"type": "input_text", "text": content}],
                status="completed",
                created_at=timestamp,
                updated_at=timestamp,
                order_index=next_order,
            )
            assistant_message = ChatMessage(
                id=uuid4().hex,
                role="assistant",
                content=[],
                status="completed",
                created_at=timestamp,
                updated_at=timestamp,
                order_index=next_order + 1,
            )

            if command == "/clear":
                session.messages.clear()
                session.memory = LayeredConversationMemory()
                if session.conversation is not None:
                    try:
                        session.conversation.close()
                    except Exception:
                        pass
                    session.conversation = None
                assistant_message.content = [
                    {"type": "output_text", "text": "会话历史已清空。"}
                ]
                session.messages.extend([user_message, assistant_message])

            elif command == "/stats":
                usage_text = "未找到 Token 消耗统计。"
                if session.conversation is not None and hasattr(
                    session.conversation, "cost_tracker"
                ):
                    tracker = session.conversation.cost_tracker
                    summary = tracker.summary_dict()
                    usage_text = (
                        f"**Token 消耗统计**\n"
                        f"- Input Tokens: {summary['input_tokens']}\n"
                        f"- Output Tokens: {summary['output_tokens']}\n"
                        f"- Total Tokens: {summary['total_tokens']}\n"
                        f"- Events: {summary['event_count']}"
                    )
                assistant_message.content = [
                    {"type": "output_text", "text": usage_text}
                ]
                session.messages.extend([user_message, assistant_message])

            elif command == "/compact":
                assistant_message.status = "in_progress"
                session.messages.extend([user_message, assistant_message])
                session.status = "running"
                session.future = self.executor.submit(
                    self._process_slash_compact, session_id, assistant_message.id
                )
            else:
                assistant_message.content = [
                    {"type": "output_text", "text": f"未知命令: {command}"}
                ]
                session.messages.extend([user_message, assistant_message])

            session.updated_at = timestamp
            self._persist_session_state(session)
            self._persist_message(session_id, user_message)
            self._persist_message(session_id, assistant_message)
            detail = session.detail_dict()

        self._emit_session(session)
        self._emit_message(session_id, user_message)
        self._emit_message(session_id, assistant_message)
        return detail

    def _process_slash_compact(
        self, session_id: str, assistant_message_id: str
    ) -> None:
        try:
            with self.lock:
                session = self.chat_sessions.get(session_id)
                if session is None:
                    return
                conversation = self._ensure_conversation_ready(session)
                job = self._build_memory_refresh_job(
                    session,
                    conversation,
                )

            if job is None:
                # Fallback: force refresh by tricking the logic or just returning
                # Actually, we can manually create a job ignoring conditions
                with self.lock:
                    pending_messages = self._context_history_messages(session)
                    if not pending_messages:
                        raise RuntimeError("没有可供压缩的会话历史。")
                    compactable_messages, _ = self._split_compaction_messages(
                        session, pending_messages
                    )
                    if not compactable_messages:
                        compactable_messages = pending_messages

                    assistant_messages = [
                        m for m in compactable_messages if m.role == "assistant"
                    ]
                    anchor_message_id = (
                        assistant_messages[-1].id
                        if assistant_messages
                        else session.memory.anchor_message_id
                    )
                    job = _MemoryRefreshJob(
                        session_id=session.session_id,
                        conversation=conversation,
                        existing_memory=session.memory.model_copy(deep=True),
                        transcript_payload=build_memory_transcript_payload(
                            compactable_messages
                        ),
                        anchor_message_id=anchor_message_id or "",
                        revision=session.memory_refresh_revision + 1,
                    )

            updated_memory = self._execute_memory_refresh_job(job)

            with self.lock:
                session = self.chat_sessions.get(session_id)
                if session is None:
                    return
                session.memory = updated_memory
                session.memory_refresh_revision = job.revision

                self._apply_physical_compaction(
                    session, job.anchor_message_id, updated_memory
                )

                assistant_message = self._find_message(session, assistant_message_id)
                assistant_message.content = [
                    {"type": "output_text", "text": "会话记忆已手动压缩完成。"}
                ]
                assistant_message.status = "completed"
                assistant_message.updated_at = now_iso()
                session.status = "idle"
                session.future = None
                session.updated_at = assistant_message.updated_at
                self._persist_session_state(session)
                self._persist_message(session_id, assistant_message)

            self._emit_session(session)
            self._emit_message(session_id, assistant_message)
        except Exception as exc:
            with self.lock:
                session = self.chat_sessions.get(session_id)
                if session is None:
                    return
                assistant_message = self._find_message(session, assistant_message_id)
                assistant_message.content = [
                    {"type": "output_text", "text": f"记忆压缩失败: {exc}"}
                ]
                assistant_message.status = "failed"
                assistant_message.error = str(exc)
                assistant_message.updated_at = now_iso()
                session.status = "error"
                session.error = str(exc)
                session.future = None
                session.updated_at = assistant_message.updated_at
                self._persist_session_state(session)
                self._persist_message(session_id, assistant_message)
            self._emit_session(session)
            self._emit_message(session_id, assistant_message)

    def enqueue_message(self, session_id: str, content: str) -> dict[str, Any]:
        content = str(content or "").strip()
        if not content:
            raise ValueError("Message content cannot be empty.")

        if content.startswith("/"):
            return self._handle_slash_command(session_id, content)

        with self.lock:
            session = self.chat_sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            if session.future is not None and not session.future.done():
                raise RuntimeError("当前会话仍在处理中，请等待上一条消息完成。")

            next_order = len(session.messages) + 1
            timestamp = now_iso()
            user_message = ChatMessage(
                id=uuid4().hex,
                role="user",
                content=[{"type": "input_text", "text": content}],
                status="completed",
                created_at=timestamp,
                updated_at=timestamp,
                order_index=next_order,
            )
            assistant_message = ChatMessage(
                id=uuid4().hex,
                role="assistant",
                content=[],
                status="in_progress",
                created_at=timestamp,
                updated_at=timestamp,
                order_index=next_order + 1,
            )

            session.messages.extend([user_message, assistant_message])
            session.status = "running"
            session.error = None
            session.interrupt_requested = False
            session.updated_at = timestamp
            session.future = self.executor.submit(
                self._process_turn,
                session.session_id,
                user_message.id,
                assistant_message.id,
                content,
            )

            self._persist_session_state(session)
            self._persist_message(session.session_id, user_message)
            self._persist_message(session.session_id, assistant_message)
            detail = session.detail_dict()

        self._emit_session(session)
        self._emit_message(session.session_id, user_message)
        self._emit_message(session.session_id, assistant_message)
        return detail

    def _process_turn(
        self,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
        content: str,
    ) -> None:
        self._wait_for_pending_cleanup(session_id)
        last_stream_emit_at = 0.0
        stream_emit_interval = _STREAM_EMIT_INTERVAL

        def flush_partial(force: bool = False) -> None:
            nonlocal last_stream_emit_at
            now = monotonic()
            if not force and now - last_stream_emit_at < stream_emit_interval:
                return
            last_stream_emit_at = now

            with self.lock:
                session = self.chat_sessions.get(session_id)
                if session is None:
                    return
                assistant_message = self._find_message(session, assistant_message_id)
                self._persist_session_state(session)
                self._persist_message(session_id, assistant_message)
                session_payload = session.summary_dict()
                message_payload = assistant_message.to_dict()

            self._emit("session.upsert", session=session_payload)
            self._emit("message.upsert", session_id=session_id, message=message_payload)

        def on_stream_event(event: dict[str, Any]) -> None:
            incoming = assistant_content_from_blocks(
                list(event.get("blocks") or []),
                fallback_text=str(event.get("content") or ""),
            )
            with self.lock:
                session = self.chat_sessions.get(session_id)
                if session is None:
                    return
                assistant_message = self._find_message(session, assistant_message_id)
                assistant_message.content = merge_assistant_content(
                    assistant_message.content, incoming
                )
                assistant_message.status = "in_progress"
                assistant_message.error = None
                assistant_message.updated_at = now_iso()
                session.status = (
                    "interrupting" if session.interrupt_requested else "running"
                )
                session.error = None
                session.updated_at = assistant_message.updated_at
            flush_partial(force=should_force_stream_flush(event))

        try:
            with self.lock:
                session = self.chat_sessions.get(session_id)
                if session is None:
                    return
                conversation = self._ensure_conversation_ready(
                    session,
                    skip_message_ids={user_message_id, assistant_message_id},
                )
                session.artifact_dir = str(conversation.runtime.artifacts.session_dir)
                knowledge_base_ids = list(session.knowledge_base_ids)
                self._persist_session_state(session)

            effective_knowledge_base_ids = self._resolve_turn_knowledge_base_ids(
                knowledge_base_ids
            )
            conversation.runtime.configure_knowledge_search(
                search_callback=self._runtime_knowledge_search,
                default_base_ids=effective_knowledge_base_ids,
            )
            reply = conversation.send(content, stream_callback=on_stream_event)

            with self.lock:
                session = self.chat_sessions.get(session_id)
                if session is None:
                    return
                assistant_message = self._find_message(session, assistant_message_id)
                assistant_message.content = merge_assistant_content(
                    assistant_message.content,
                    assistant_content_from_blocks(
                        list(reply.blocks or []),
                        fallback_text=reply.assistant_message,
                    ),
                )
                assistant_message.content = finalize_completed_assistant_content(
                    assistant_message.content
                )
                assistant_message.status = "completed"
                assistant_message.error = None
                assistant_message.updated_at = now_iso()
                cleanup_job: _MemoryRefreshJob | None = None
                if session.conversation is not None:
                    session.memory_refresh_revision += 1
                    cleanup_job = self._build_memory_refresh_job(
                        session,
                        session.conversation,
                        revision=session.memory_refresh_revision,
                    )
                    if cleanup_job is None:
                        session.cleanup_future = None
                        session.is_compacting = False
                    else:
                        session.cleanup_future = self.executor.submit(
                            self._run_post_turn_memory_refresh, cleanup_job
                        )
                        session.is_compacting = True
                session.error = None
                session.artifact_dir = reply.artifact_dir
                session.updated_at = assistant_message.updated_at
                session.status = "idle"
                session.interrupt_requested = False
                session.future = None
                self._persist_session_state(session)
                self._persist_message(session_id, assistant_message)

            self._emit_session(session)
            self._emit_message(session_id, assistant_message)
        except Exception as exc:
            with self.lock:
                session = self.chat_sessions.get(session_id)
                if session is None:
                    return
                assistant_message = self._find_message(session, assistant_message_id)
                if not assistant_message.content:
                    assistant_message.content = [
                        {"type": "output_text", "text": str(exc)}
                    ]
                assistant_message.content = finalize_completed_assistant_content(
                    assistant_message.content
                )
                assistant_message.status = "failed"
                assistant_message.error = str(exc)
                assistant_message.updated_at = now_iso()
                session.status = "error"
                session.error = str(exc)
                session.interrupt_requested = False
                session.future = None
                session.is_compacting = False
                session.updated_at = assistant_message.updated_at
                self._persist_session_state(session)
                self._persist_message(session_id, assistant_message)

            self._emit_session(session)
            self._emit_message(session_id, assistant_message)

    def shutdown(self) -> None:
        with self.lock:
            sessions = list(self.chat_sessions.values())
        cleanup_futures = [
            session.cleanup_future
            for session in sessions
            if session.cleanup_future is not None
        ]
        for cleanup_future in cleanup_futures:
            if cleanup_future.done():
                continue
            with contextlib.suppress(Exception):
                cleanup_future.result(timeout=2)
        for session in sessions:
            if session.conversation is not None:
                try:
                    session.conversation.close()
                except Exception:
                    continue
        self.authorization_store.close()
        self.knowledge_store.close()
        self.session_store.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
