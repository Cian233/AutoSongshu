from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any

from agentscope.message import Msg

from ..config import AppConfig
from .harness import BaseAgentHarness
from .long_term_memory import LongTermMemory
from .prompts import _CONTINUATION_PROMPT
from .step_model import AgentStep, StepState, TaskState, TokenUsage
from .trajectory import TrajectoryRecorder
from .utils import (
    _StreamLoopGuard,
    _continue_response_until_settled,
    _extract_response_blocks,
    _prepare_user_message,
)

logger = logging.getLogger(__name__)


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
        self._trajectory = TrajectoryRecorder(self.runtime.artifacts.path("trajectories"))
        self._current_step: int = 0
        self._task_state: TaskState = TaskState.RUNNING
        self._long_term_memory: LongTermMemory | None = None
        self._historical_context: str = ""
        self._init_long_term_memory()

    def _init_long_term_memory(self) -> None:
        try:
            self._long_term_memory = LongTermMemory()
            logger.info(
                "Long-term memory initialized with %d experiences",
                self._long_term_memory.get_experience_count(),
            )
        except Exception as e:
            logger.warning("Failed to initialize long-term memory: %s", e)
            self._long_term_memory = None

    def _load_historical_experiences(self, target_url: str) -> str:
        if self._long_term_memory is None:
            return ""

        try:
            experiences = self._long_term_memory.retrieve_relevant_experience(
                target=target_url,
                limit=3,
            )
            if not experiences:
                logger.info("No relevant historical experiences found for target: %s", target_url)
                return ""

            context = self._long_term_memory.render_experiences_for_prompt(experiences)
            logger.info(
                "Loaded %d relevant historical experiences for target: %s",
                len(experiences),
                target_url,
            )
            return context
        except Exception as e:
            logger.warning("Failed to load historical experiences: %s", e)
            return ""

    async def run_async(self, goal: str) -> RunResult:
        stream_queue: asyncio.Queue | None = None
        stop_event: asyncio.Event | None = None
        stream_task: asyncio.Task[None] | None = None
        loop_guard = _StreamLoopGuard()
        agent_config = getattr(getattr(self, "config", None), "agent", None)
        use_loop_guard = getattr(agent_config, "loop_guard_enabled", True)
        if hasattr(self.runtime, "tool_call_cache"):
            self.runtime.tool_call_cache.reset_turn()
        self._trajectory.start_session(session_id=self.runtime.artifacts.session_dir.name)

        self._historical_context = self._load_historical_experiences(
            self.config.engagement.start_url
        )

        if getattr(agent_config, "mode", "auto") == "semi-auto":
            prompt = "\n".join(
                [
                    f"User goal: {goal}",
                    f"Start URL: {self.config.engagement.start_url}",
                    "",
                    "## Execution Guidelines (Semi-Auto Mode)",
                    "",
                    "You are in SEMI-AUTO mode. You have autonomy to gather context and analyze, but must pause before any mutations:",
                    "",
                    "1. **Reconnaissance (autonomous)**: Use `knowledge_search`, `browser_navigate`, `http_request` (GET) freely to gather context.",
                    "2. **Analysis (autonomous)**: Analyze findings, identify potential vulnerabilities, and form hypotheses.",
                    "3. **Planning (requires approval)**: Present a clear, step-by-step plan for exploitation/verification.",
                    "4. **Execution (requires approval)**: Wait for user approval before using any mutation tools (sandbox_run_python, sandbox_write_file, http_post, etc.).",
                    "",
                    "Default to Simplified Chinese unless the user explicitly asks for another language.",
                ]
            )
        else:
            prompt = "\n".join(
                [
                    f"User goal: {goal}",
                    f"Start URL: {self.config.engagement.start_url}",
                    "",
                    "## Execution Guidelines (Dynamic Planning Mode)",
                    "",
                    "You have full autonomy to decide the best course of action. There is NO fixed plan-then-execute sequence. Instead:",
                    "",
                    "1. **Gather context first**: Use `knowledge_search` to check historical experiences, then perform preliminary probing on the target.",
                    "2. **Reason iteratively**: After each observation, decide whether to gather more context, perform analysis, or take action.",
                    "3. **Adapt dynamically**: If initial assumptions are wrong, adjust your approach without waiting for user input.",
                    "4. **Record findings continuously**: Update findings as you discover them, not just at the end.",
                    "5. **Know when to stop**: When you have sufficient evidence to draw conclusions, summarize findings and stop.",
                    "",
                    "Default to Simplified Chinese unless the user explicitly asks for another language.",
                ]
            )

        if self._historical_context:
            prompt = "\n".join(
                [
                    prompt,
                    "",
                    "## Historical Penetration Testing Experiences",
                    "",
                    "The following are relevant experiences from previous penetration testing sessions. Use these to inform your approach and avoid repeating failed strategies:",
                    "",
                    self._historical_context,
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
            self._task_state = TaskState.COMPLETED
            self._trajectory.end_session(state=self._task_state)
            self._save_to_long_term_memory()
            model_name = str(getattr(self.config, "model", None) and getattr(self.config.model, "model_name", "") or "")
            return RunResult(
                final_message=assistant_message,
                artifact_dir=str(self.runtime.artifacts.session_dir),
                usage=self.cost_tracker.summary_dict(model_name=model_name),
            )
        finally:
            if self._task_state == TaskState.RUNNING:
                self._task_state = TaskState.ERROR
                self._trajectory.end_session(state=self._task_state)
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

    def _save_to_long_term_memory(self) -> None:
        if self._long_term_memory is None:
            return

        try:
            findings = []
            if hasattr(self.runtime, "findings"):
                for finding in self.runtime.findings.list():
                    findings.append(finding.model_dump())

            successful_strategies = []
            failed_approaches = []
            lessons_learned = ""

            trajectory_summary = self._trajectory.summary()
            if trajectory_summary.get("succeeded", 0) > 0:
                successful_strategies.append(
                    f"Completed {trajectory_summary['succeeded']} successful steps"
                )
            if trajectory_summary.get("failed", 0) > 0:
                failed_approaches.append(
                    f"Encountered {trajectory_summary['failed']} failed steps"
                )

            vulnerability_types = list(
                set(f.get("cwe", "") or f.get("title", "") for f in findings if f)
            )
            vulnerability_types = [v for v in vulnerability_types if v]

            target_info = {
                "target_url": self.config.engagement.start_url,
                "target_type": "web_app",
                "tech_stack": [],
                "vulnerability_types": vulnerability_types,
            }

            strategies = {
                "successful": successful_strategies,
                "failed": failed_approaches,
                "lessons_learned": lessons_learned,
            }

            session_id = self.runtime.artifacts.session_dir.name
            self._long_term_memory.store_experience(
                session_id=session_id,
                findings=findings,
                strategies=strategies,
                target_info=target_info,
            )
            logger.info("Saved session experience to long-term memory: %s", session_id)
        except Exception as e:
            logger.warning("Failed to save experience to long-term memory: %s", e)

    @property
    def trajectory_summary(self) -> dict[str, Any]:
        """Return the current trajectory recording summary."""
        return self._trajectory.summary()


__all__ = ["RunResult", "ConversationReply", "SkillCommand", "PentestCoordinator"]
