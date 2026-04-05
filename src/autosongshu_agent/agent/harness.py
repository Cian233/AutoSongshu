from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable
from typing import Any

from agentscope.message import Msg

from ..config import AppConfig
from ..memory.models import CostTracker
from ..runtime import PentestRuntime
from .builder import _AgentBuilderMixin
from .utils import (
    _StreamLoopGuard,
    _build_loop_guard_recovery_prompt,
    _build_stream_event,
)


class BaseAgentHarness(_AgentBuilderMixin):
    """
    Base class for running AgentScope agents with loop guard,
    streaming, cost tracking, and interrupt capabilities.
    """

    def __init__(
        self,
        config: AppConfig,
        artifact_session_name: str | None = None,
        sandbox_user_id: str | None = None,
        permission_interceptor: Any | None = None,
    ) -> None:
        self.config = config
        self.runtime = PentestRuntime(
            config,
            artifact_session_name=artifact_session_name,
            sandbox_user_id=sandbox_user_id,
        )
        self.cost_tracker = CostTracker()
        self._interrupt_lock = threading.RLock()
        self._active_loop: asyncio.AbstractEventLoop | None = None
        self._interrupt_requested = False
        self.permission_interceptor = permission_interceptor
        self.agent = self._build_agent()

    async def run_agent_turn(
        self,
        content: str,
        *,
        use_loop_guard: bool,
        loop_guard: _StreamLoopGuard,
        allow_loop_guard_recovery: bool = True,
    ) -> Msg:
        if use_loop_guard:
            loop_guard.reset()

        response_task = asyncio.create_task(
            self.agent(
                Msg(
                    name="operator",
                    role="user",
                    content=content,
                ),
            ),
        )

        with self._interrupt_lock:
            interrupt_requested = self._interrupt_requested

        if interrupt_requested:
            await asyncio.sleep(0)
            await self.agent.interrupt()

        response = await response_task

        if hasattr(response, "metadata") and isinstance(response.metadata, dict):
            usage = response.metadata.get("usage", {})
            if isinstance(usage, dict):
                prompt_tokens = (
                    usage.get("prompt_tokens") or usage.get("input_tokens") or 0
                )
                completion_tokens = (
                    usage.get("completion_tokens") or usage.get("output_tokens") or 0
                )
                self.cost_tracker.add_usage(
                    input_tokens=int(prompt_tokens),
                    output_tokens=int(completion_tokens),
                    label="agent_turn",
                )

        if use_loop_guard:
            loop_reason = loop_guard.consume_triggered_reason()
            if loop_reason and allow_loop_guard_recovery:
                return await self.run_agent_turn(
                    _build_loop_guard_recovery_prompt(loop_reason),
                    use_loop_guard=use_loop_guard,
                    loop_guard=loop_guard,
                    allow_loop_guard_recovery=False,
                )
        return response

    async def stream_agent_messages(
        self,
        queue: asyncio.Queue,
        stop_event: asyncio.Event,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
        loop_guard: _StreamLoopGuard | None = None,
    ) -> None:
        while True:
            if stop_event.is_set() and queue.empty():
                return
            try:
                msg, last, _speech = await asyncio.wait_for(queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            event = _build_stream_event(msg, last)
            if loop_guard is not None and loop_guard.observe(event):
                with contextlib.suppress(Exception):
                    await self.agent.interrupt()
            if stream_callback is not None:
                with contextlib.suppress(Exception):
                    stream_callback(event)

    def interrupt(self) -> bool:
        with self._interrupt_lock:
            self._interrupt_requested = True
            loop = self._active_loop

        if loop is None or loop.is_closed():
            return False
        try:
            asyncio.run_coroutine_threadsafe(self.agent.interrupt(), loop)
        except RuntimeError:
            return False
        return True

    def close(self) -> None:
        self.runtime.close()
