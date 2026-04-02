from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any

from agentscope.message import Msg

from ..config import AppConfig
from .harness import BaseAgentHarness
from .prompts import _CONTINUATION_PROMPT
from .utils import (
    _StreamLoopGuard,
    _continue_response_until_settled,
    _extract_response_blocks,
    _prepare_user_message,
)


@dataclass
class RunResult:
    final_message: str
    artifact_dir: str
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class ConversationReply:
    assistant_message: str
    artifact_dir: str
    blocks: list[dict[str, Any]] | None = None


@dataclass
class SkillCommand:
    requested_names: list[str] = field(default_factory=list)
    remaining_message: str = ""


class PentestCoordinator(BaseAgentHarness):
    def __init__(self, config: AppConfig, sandbox_user_id: str | None = None) -> None:
        super().__init__(config, sandbox_user_id=sandbox_user_id)

    async def run_async(self, goal: str) -> RunResult:
        stream_queue: asyncio.Queue | None = None
        stop_event: asyncio.Event | None = None
        stream_task: asyncio.Task[None] | None = None
        loop_guard = _StreamLoopGuard()
        agent_config = getattr(getattr(self, "config", None), "agent", None)
        use_loop_guard = getattr(agent_config, "loop_guard_enabled", True)
        if hasattr(self.runtime, "tool_call_cache"):
            self.runtime.tool_call_cache.reset_turn()
        if getattr(agent_config, "mode", "auto") == "semi-auto":
            prompt = "\n".join(
                [
                    f"User goal: {goal}",
                    f"Start URL: {self.config.engagement.start_url}",
                    "You are currently in SEMI-AUTO mode.",
                    "Before providing a plan, you MUST perform necessary reconnaissance (e.g., use `knowledge_search` to check historical experiences, or perform preliminary probing/exploration on the target) to gather context.",
                    "After sufficient reconnaissance, provide a clear, step-by-step plan.",
                    "Wait for the user to approve the plan before proceeding with any sandbox mutations or executions.",
                    "Do NOT use any execution tools (e.g., sandbox_run_python, sandbox_write_file) until explicitly approved.",
                    "Default to Simplified Chinese unless the user explicitly asks for another language.",
                ]
            )
        else:
            prompt = "\n".join(
                [
                    f"User goal: {goal}",
                    f"Start URL: {self.config.engagement.start_url}",
                    "Before providing a plan, you MUST perform necessary reconnaissance (e.g., use `knowledge_search` to check historical experiences, or perform preliminary probing/exploration on the target) to gather context.",
                    "After sufficient reconnaissance, provide a clear, step-by-step plan.",
                    "Then, execute the assessment within the authorized scope according to your plan, keep findings updated, and finish with the most important conclusions.",
                    "Default to Simplified Chinese unless the user explicitly asks for another language.",
                ]
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
            if use_loop_guard:
                stream_queue = asyncio.Queue(maxsize=200)
                stop_event = asyncio.Event()
                self.agent.set_msg_queue_enabled(True, queue=stream_queue)
                stream_task = asyncio.create_task(
                    self.stream_agent_messages(
                        stream_queue,
                        stop_event,
                        loop_guard=loop_guard,
                    )
                )

            response = await _run_agent_turn(
                _prepare_user_message(prompt, self.skill_report)
            )
            assistant_message, blocks = _extract_response_blocks(response.content)
            assistant_message, blocks = await _continue_response_until_settled(
                run_agent_turn=_run_agent_turn,
                assistant_message=assistant_message,
                blocks=blocks,
                continuation_prompt=_CONTINUATION_PROMPT,
            )
            self.runtime.persist_runtime_logs()
            return RunResult(
                final_message=assistant_message,
                artifact_dir=str(self.runtime.artifacts.session_dir),
                usage={
                    "input_tokens": self.cost_tracker.input_tokens,
                    "output_tokens": self.cost_tracker.output_tokens,
                    "total_tokens": self.cost_tracker.input_tokens + self.cost_tracker.output_tokens,
                },
            )
        finally:
            if stop_event is not None:
                stop_event.set()
            if stream_queue is not None:
                self.agent.set_msg_queue_enabled(False)
            if stream_task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await stream_task
            self.close()

    def run(self, goal: str) -> RunResult:
        return asyncio.run(self.run_async(goal))


__all__ = ["RunResult", "ConversationReply", "SkillCommand", "PentestCoordinator"]
