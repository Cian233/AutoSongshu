from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from agentscope.message import Msg

from ..config import AppConfig
from ..memory import (
    LayeredConversationMemory,
    build_memory_fallback,
    now_iso as memory_now_iso,
    sync_validated_findings,
)
from .harness import BaseAgentHarness
from .coordinator import ConversationReply
from .prompts import _CONTINUATION_PROMPT
from .utils import (
    _StreamLoopGuard,
    _continue_response_until_settled,
    _extract_response_blocks,
    _prepare_user_message,
)


class PentestConversationSession(BaseAgentHarness):
    def __init__(
        self,
        config: AppConfig,
        artifact_session_name: str | None = None,
        sandbox_user_id: str | None = None,
    ) -> None:
        super().__init__(
            config,
            artifact_session_name=artifact_session_name,
            sandbox_user_id=sandbox_user_id,
        )
        self._memory_context = ""
        self.memory_model = self._build_memory_model()

    async def observe_history_async(self, messages: list[Msg]) -> None:
        if not messages:
            return
        await self.agent.observe(messages)

    def observe_history(self, messages: list[Msg]) -> None:
        if not messages:
            return
        asyncio.run(self.observe_history_async(messages))

    def rebuild_context(
        self,
        history_messages: list[Msg],
        *,
        memory: LayeredConversationMemory | None = None,
        pinned_context: str | None = None,
    ) -> None:
        self.agent = self._build_agent()
        context_sections: list[str] = []
        if pinned_context and pinned_context.strip():
            context_sections.append(pinned_context.strip())
        if memory and not memory.is_empty():
            context_sections.append(memory.render_for_model())
        self._memory_context = "\n\n".join(
            section for section in context_sections if section
        ).strip()
        context_messages: list[Msg] = []
        if self._memory_context:
            context_messages.append(
                Msg(name="memory", role="system", content=self._memory_context)
            )
        context_messages.extend(history_messages)
        self.observe_history(context_messages)

    async def refresh_memory_async(
        self,
        *,
        existing_memory: LayeredConversationMemory,
        transcript_payload: list[dict[str, Any]],
        anchor_message_id: str | None,
    ) -> LayeredConversationMemory:
        validated_findings = sync_validated_findings(self.runtime.findings.list())
        if (
            not transcript_payload
            and anchor_message_id == existing_memory.anchor_message_id
            and existing_memory.validated_findings == validated_findings
        ):
            return existing_memory
        if (
            not transcript_payload
            and anchor_message_id == existing_memory.anchor_message_id
        ):
            updated = existing_memory.model_copy(deep=True)
            updated.validated_findings = validated_findings
            updated.updated_at = memory_now_iso()
            self.runtime.artifacts.write_json("memory.json", updated.model_dump())
            self.runtime.update_session_metadata({"memory": updated.model_dump()})
            return updated
        updated = build_memory_fallback(
            existing_memory,
            transcript_payload,
            validated_findings,
            anchor_message_id,
        )

        updated.anchor_message_id = anchor_message_id or updated.anchor_message_id
        updated.updated_at = updated.updated_at or memory_now_iso()
        self.runtime.artifacts.write_json("memory.json", updated.model_dump())
        self.runtime.update_session_metadata({"memory": updated.model_dump()})
        return updated

    def refresh_memory(
        self,
        *,
        existing_memory: LayeredConversationMemory,
        transcript_payload: list[dict[str, Any]],
        anchor_message_id: str | None,
    ) -> LayeredConversationMemory:
        return asyncio.run(
            self.refresh_memory_async(
                existing_memory=existing_memory,
                transcript_payload=transcript_payload,
                anchor_message_id=anchor_message_id,
            ),
        )

    async def send_async(
        self,
        user_message: str,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> ConversationReply:
        stream_queue: asyncio.Queue | None = None
        stop_event: asyncio.Event | None = None
        stream_task: asyncio.Task[None] | None = None
        loop_guard = _StreamLoopGuard()
        agent_config = getattr(getattr(self, "config", None), "agent", None)
        use_loop_guard = getattr(agent_config, "loop_guard_enabled", True)
        loop = asyncio.get_running_loop()
        if hasattr(self.runtime, "tool_call_cache"):
            self.runtime.tool_call_cache.reset_turn()
        with self._interrupt_lock:
            self._active_loop = loop
        if stream_callback is not None or use_loop_guard:
            stream_queue = asyncio.Queue(maxsize=200)
            stop_event = asyncio.Event()
            self.agent.set_msg_queue_enabled(True, queue=stream_queue)
            stream_task = asyncio.create_task(
                self.stream_agent_messages(
                    stream_queue,
                    stop_event,
                    stream_callback,
                    loop_guard=loop_guard if use_loop_guard else None,
                ),
            )

        async def _run_agent_turn(
            content: str, *, allow_loop_guard_recovery: bool = True
        ) -> Msg:
            return await self.run_agent_turn(
                content,
                use_loop_guard=use_loop_guard,
                loop_guard=loop_guard,
                allow_loop_guard_recovery=allow_loop_guard_recovery,
            )

        try:
            response = await _run_agent_turn(
                _prepare_user_message(
                    user_message,
                    self.skill_report,
                    getattr(self, "_memory_context", ""),
                ),
            )
            assistant_message, blocks = _extract_response_blocks(response.content)
            assistant_message, blocks = await _continue_response_until_settled(
                run_agent_turn=_run_agent_turn,
                assistant_message=assistant_message,
                blocks=blocks,
                continuation_prompt=_CONTINUATION_PROMPT,
            )
            self.runtime.persist_runtime_logs()
            return ConversationReply(
                assistant_message=assistant_message,
                artifact_dir=str(self.runtime.artifacts.session_dir),
                blocks=blocks,
            )
        finally:
            if stop_event is not None:
                stop_event.set()
            if stream_queue is not None:
                self.agent.set_msg_queue_enabled(False)
            if stream_task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await stream_task
            with self._interrupt_lock:
                self._active_loop = None
                self._interrupt_requested = False

    def send(
        self,
        user_message: str,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> ConversationReply:
        return asyncio.run(
            self.send_async(user_message, stream_callback=stream_callback)
        )

__all__ = ["PentestConversationSession"]
