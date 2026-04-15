from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from agentscope.message import Msg

from ..config import AppConfig
from ..memory.models import CostTracker
from ..runtime import PentestRuntime
from .builder import _AgentBuilderMixin
from .error_healing import ErrorHealingMixin, ErrorRecoveryContext
from .utils import (
    _StreamLoopGuard,
    _build_loop_guard_recovery_prompt,
    _build_stream_event,
)

logger = logging.getLogger(__name__)


class BaseAgentHarness(ErrorHealingMixin, _AgentBuilderMixin):
    """
    Base class for running AgentScope agents with loop guard,
    streaming, cost tracking, and interrupt capabilities.
    """

    def __init__(
        self,
        config: AppConfig,
        artifact_session_name: str | None = None,
        artifact_project_dir: str | None = None,
        sandbox_user_id: str | None = None,
        permission_interceptor: Any | None = None,
    ) -> None:
        # Initialize ErrorHealingMixin first (MRO: ErrorHealingMixin -> _AgentBuilderMixin)
        ErrorHealingMixin.__init__(self)
        self.config = config
        self.runtime = PentestRuntime(
            config,
            artifact_session_name=artifact_session_name,
            artifact_project_dir=artifact_project_dir,
            sandbox_user_id=sandbox_user_id,
        )
        self.cost_tracker = CostTracker()
        self._interrupt_lock = threading.RLock()
        self._active_loop: asyncio.AbstractEventLoop | None = None
        self._interrupt_requested = False
        self.permission_interceptor = permission_interceptor
        self.agent = self._build_agent()
        # Link builder to runtime so spawn_agent tool can find it
        self.runtime._agent_builder = self

    async def run_agent_turn(
        self,
        content: str,
        *,
        use_loop_guard: bool,
        loop_guard: _StreamLoopGuard,
        allow_loop_guard_recovery: bool = True,
    ) -> Msg:
        try:
            return await self._run_agent_turn_impl(
                content,
                use_loop_guard=use_loop_guard,
                loop_guard=loop_guard,
                allow_loop_guard_recovery=allow_loop_guard_recovery,
            )
        except asyncio.TimeoutError:
            timeout_sec = self.config.agent.turn_timeout_sec
            logger.warning(
                "Agent turn timed out after %d seconds. Triggering error recovery.",
                timeout_sec,
            )
            success, result = await self._handle_agent_error_async(
                error=TimeoutError(f"Agent turn timed out after {timeout_sec}s"),
                original_task=content,
            )
            if success and isinstance(result, dict):
                simplified_task = result.get("simplified_task", content)
                return await self._run_agent_turn_impl(
                    simplified_task,
                    use_loop_guard=use_loop_guard,
                    loop_guard=loop_guard,
                    allow_loop_guard_recovery=allow_loop_guard_recovery,
                )
            raise TimeoutError(
                f"Agent turn timed out after {timeout_sec}s and recovery failed. "
                f"Consider increasing agent.turn_timeout_sec in config."
            )
        except Exception as exc:
            success, result = await self._handle_agent_error_async(
                error=exc,
                original_task=content,
            )
            if success and isinstance(result, dict):
                simplified_task = result.get("simplified_task", content)
                return await self._run_agent_turn_impl(
                    simplified_task,
                    use_loop_guard=use_loop_guard,
                    loop_guard=loop_guard,
                    allow_loop_guard_recovery=allow_loop_guard_recovery,
                )
            raise

    async def _run_agent_turn_impl(
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

        # Apply turn timeout (inspired by OpenCode's withTimeout strategy)
        turn_timeout = self.config.agent.turn_timeout_sec
        try:
            response = await asyncio.wait_for(response_task, timeout=turn_timeout)
        except asyncio.TimeoutError:
            # Cancel the running task
            response_task.cancel()
            try:
                await response_task
            except asyncio.CancelledError:
                pass
            raise

        with self._interrupt_lock:
            interrupt_requested = self._interrupt_requested

        if interrupt_requested:
            await asyncio.sleep(0)
            await self.agent.interrupt()

        # Apply turn timeout (inspired by OpenCode's withTimeout strategy)
        turn_timeout = self.config.agent.turn_timeout_sec
        try:
            response = await asyncio.wait_for(response_task, timeout=turn_timeout)
        except asyncio.TimeoutError:
            # Cancel the running task
            response_task.cancel()
            try:
                await response_task
            except asyncio.CancelledError:
                pass
            raise

        if hasattr(response, "metadata") and isinstance(response.metadata, dict):
            usage = response.metadata.get("usage", {})
            if isinstance(usage, dict):
                prompt_tokens = (
                    usage.get("prompt_tokens") or usage.get("input_tokens") or 0
                )
                completion_tokens = (
                    usage.get("completion_tokens") or usage.get("output_tokens") or 0
                )
                cache_creation = (
                    usage.get("cache_creation_input_tokens")
                    or usage.get("cached_tokens")
                    or 0
                )
                cache_read = (
                    usage.get("cache_read_input_tokens")
                    or usage.get("prompt_tokens_details", {}).get("cached_tokens")
                    or 0
                )
                self.cost_tracker.add_usage(
                    input_tokens=int(prompt_tokens),
                    output_tokens=int(completion_tokens),
                    label="agent_turn",
                    cache_creation_input_tokens=int(cache_creation),
                    cache_read_input_tokens=int(cache_read),
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

    async def _handle_agent_error_async(
        self,
        error: Exception,
        original_task: str,
        attempt_count: int = 0,
    ) -> tuple[bool, Any]:
        self.error_recovery_stats.last_error_type = type(error).__name__

        if attempt_count >= self.error_healing_config.max_recovery_attempts:
            logger.error(
                "Error recovery exhausted after %d attempts for task: %s. "
                "Error: %s",
                attempt_count,
                original_task,
                error,
            )
            return False, None

        context = ErrorRecoveryContext(
            error=error,
            original_task=original_task,
            attempt_count=attempt_count,
            strategies_tried=[],
        )

        strategies: list[tuple[str, bool]] = [
            ("model_switching", self.error_healing_config.enable_model_switching),
            ("task_simplification", self.error_healing_config.enable_task_simplification),
            ("delegation", self.error_healing_config.enable_delegation),
            ("plan_mode_fallback", self.error_healing_config.enable_plan_mode_fallback),
        ]

        for strategy_name, enabled in strategies:
            if not enabled:
                continue

            if strategy_name in context.strategies_tried:
                continue

            context.strategies_tried.append(strategy_name)
            start_time = time.monotonic()

            logger.info(
                "Attempting error recovery strategy '%s' (attempt %d/%d) for task: %s",
                strategy_name,
                attempt_count + 1,
                self.error_healing_config.max_recovery_attempts,
                original_task,
            )

            try:
                if strategy_name == "model_switching":
                    success, result = self._retry_with_different_model(error, context)
                elif strategy_name == "task_simplification":
                    success, result = self._simplify_task_and_retry(error, context)
                elif strategy_name == "delegation":
                    success, result = self._delegate_to_specialized_agent(error, context)
                elif strategy_name == "plan_mode_fallback":
                    success, result = self._fallback_to_plan_mode(error, context)
                else:
                    success, result = False, None
            except Exception as recovery_exc:
                logger.warning(
                    "Recovery strategy '%s' failed with exception: %s",
                    strategy_name,
                    recovery_exc,
                )
                success, result = False, None

            duration_ms = (time.monotonic() - start_time) * 1000
            self.error_recovery_stats.record_attempt(
                strategy=strategy_name,
                success=success,
                duration_ms=duration_ms,
            )

            if success:
                logger.info(
                    "Error recovery succeeded with strategy '%s' after %.0fms",
                    strategy_name,
                    duration_ms,
                )
                return True, result

            logger.warning(
                "Recovery strategy '%s' failed (attempt %d). Trying next strategy.",
                strategy_name,
                attempt_count + 1,
            )

        return await self._handle_agent_error_async(
            error=error,
            original_task=original_task,
            attempt_count=attempt_count + 1,
        )

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
            if loop_guard is not None:
                loop_reason = loop_guard.observe(event)
                if loop_reason:
                    logger.info(
                        "Loop guard detected a repeated branch; deferring recovery to the next turn without hard interrupt: %s",
                        loop_reason,
                    )
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
