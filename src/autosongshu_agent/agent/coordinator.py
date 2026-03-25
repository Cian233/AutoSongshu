from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any

from agentscope.message import Msg

from ..config import AppConfig
from ..runtime import PentestRuntime
from .builder import _AgentBuilderMixin
from .prompts import _CONTINUATION_PROMPT
from .utils import (
    _StreamLoopGuard,
    _build_loop_guard_recovery_prompt,
    _build_stream_event,
    _continue_response_until_settled,
    _extract_response_blocks,
    _prepare_user_message,
)


@dataclass
class RunResult:
    final_message: str
    artifact_dir: str


@dataclass
class ConversationReply:
    assistant_message: str
    artifact_dir: str
    blocks: list[dict[str, Any]] | None = None


@dataclass
class SkillCommand:
    requested_names: list[str] = field(default_factory=list)
    remaining_message: str = ""


class PentestCoordinator(_AgentBuilderMixin):
    def __init__(self, config: AppConfig, sandbox_user_id: str | None = None) -> None:
        self.config = config
        self.runtime = PentestRuntime(config, sandbox_user_id=sandbox_user_id)

    async def run_async(self, goal: str) -> RunResult:
        agent = self._build_agent()
        stream_queue: asyncio.Queue | None = None
        stop_event: asyncio.Event | None = None
        stream_task: asyncio.Task[None] | None = None
        loop_guard = _StreamLoopGuard()
        agent_config = getattr(getattr(self, "config", None), "agent", None)
        use_loop_guard = getattr(agent_config, "loop_guard_enabled", True)
        if hasattr(self.runtime, "tool_call_cache"):
            self.runtime.tool_call_cache.reset_turn()
        prompt = "\n".join(
            [
                f"User goal: {goal}",
                f"Start URL: {self.config.engagement.start_url}",
                "Provide a short plan, execute the assessment within the authorized scope, keep findings updated, and finish with the most important conclusions.",
                "Default to Simplified Chinese unless the user explicitly asks for another language.",
            ]
        )

        async def stream_agent_messages() -> None:
            assert stream_queue is not None
            assert stop_event is not None
            while True:
                if stop_event.is_set() and stream_queue.empty():
                    return
                try:
                    msg, last, _speech = await asyncio.wait_for(
                        stream_queue.get(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue
                if loop_guard.observe(_build_stream_event(msg, last)):
                    with contextlib.suppress(Exception):
                        await agent.interrupt()

        async def run_agent_turn(
            content: str, *, allow_loop_guard_recovery: bool = True
        ) -> Msg:
            if use_loop_guard:
                loop_guard.reset()
            response = await agent(
                Msg(
                    name="operator",
                    role="user",
                    content=content,
                ),
            )
            if use_loop_guard:
                loop_reason = loop_guard.consume_triggered_reason()
                if loop_reason and allow_loop_guard_recovery:
                    return await run_agent_turn(
                        _build_loop_guard_recovery_prompt(loop_reason),
                        allow_loop_guard_recovery=False,
                    )
            return response

        try:
            if use_loop_guard:
                stream_queue = asyncio.Queue(maxsize=200)
                stop_event = asyncio.Event()
                agent.set_msg_queue_enabled(True, queue=stream_queue)
                stream_task = asyncio.create_task(stream_agent_messages())

            response = await run_agent_turn(
                _prepare_user_message(prompt, self.skill_report)
            )
            assistant_message, blocks = _extract_response_blocks(response.content)
            assistant_message, blocks = await _continue_response_until_settled(
                run_agent_turn=run_agent_turn,
                assistant_message=assistant_message,
                blocks=blocks,
                continuation_prompt=_CONTINUATION_PROMPT,
            )
            self.runtime.persist_runtime_logs()
            return RunResult(
                final_message=assistant_message,
                artifact_dir=str(self.runtime.artifacts.session_dir),
            )
        finally:
            if stop_event is not None:
                stop_event.set()
            if stream_queue is not None:
                agent.set_msg_queue_enabled(False)
            if stream_task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await stream_task
            self.runtime.close()

    def run(self, goal: str) -> RunResult:
        return asyncio.run(self.run_async(goal))


__all__ = ["RunResult", "ConversationReply", "SkillCommand", "PentestCoordinator"]
