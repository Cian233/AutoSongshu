"""Unified context orchestrator that coordinates message-level compaction
and tool-output offloading under a single token budget.

Previously, ``memory/context_window.py`` and ``agent/context_manager.py``
operated independently, each tracking its own token usage.  This module
unifies them so that the total context window (system prompt + memory +
conversation messages + tool outputs) stays within the model's limits.

Inspired by Trae's unified context management approach where all context
sources share a single budget and are prioritized holistically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from .context_window import ContextWindowConfig, ContextWindowManager
from .compaction import CompactionStrategy

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """Configuration for the unified context orchestrator."""

    # Total token budget for the model's context window
    total_tokens: int = 128000
    # Tokens reserved for system prompt and fixed overhead
    system_prompt_tokens: int = 4000
    # Tokens reserved for memory layers (summary, findings, etc.)
    memory_tokens: int = 4000
    # Tokens reserved for tool output offloading threshold
    tool_output_threshold_chars: int = 8000
    # Compaction strategy
    compaction_strategy: CompactionStrategy = CompactionStrategy.HYBRID
    # Minimum turns between incremental compaction checks
    incremental_check_interval: int = 3
    # Last compaction turn tracker (for incremental mode)
    _last_compaction_turn: int = 0
    # Whether incremental compaction is enabled
    incremental_compaction: bool = True


@dataclass
class ContextSnapshot:
    """A point-in-time snapshot of context usage across all sources."""

    total_budget: int = 0
    system_prompt_tokens: int = 0
    memory_tokens: int = 0
    message_tokens: int = 0
    tool_output_tokens: int = 0
    available_tokens: int = 0
    usage_ratio: float = 0.0
    needs_compaction: bool = False
    needs_offload: bool = False
    messages_count: int = 0
    compacted_count: int = 0


class ContextOrchestrator:
    """Coordinates all context management under a unified token budget.

    Usage::

        orchestrator = ContextOrchestrator(
            config=OrchestratorConfig(total_tokens=128000),
            window_manager=my_context_window,
        )
        snapshot = orchestrator.snapshot()
        if snapshot.needs_compaction:
            orchestrator.compact()
    """

    def __init__(
        self,
        config: OrchestratorConfig | None = None,
        window_manager: ContextWindowManager | None = None,
    ) -> None:
        self.config = config or OrchestratorConfig()
        self._window = window_manager
        self._turn_count: int = 0
        self._compaction_count: int = 0
        self._offload_count: int = 0

    @property
    def turn_count(self) -> int:
        return self._turn_count

    @property
    def compaction_count(self) -> int:
        return self._compaction_count

    @property
    def offload_count(self) -> int:
        return self._offload_count

    def set_window_manager(self, manager: ContextWindowManager) -> None:
        """Attach a ContextWindowManager for message-level compaction."""
        self._window = manager

    def snapshot(self) -> ContextSnapshot:
        """Take a point-in-time snapshot of context usage.

        Estimates tokens from all sources and determines whether
        compaction or offloading is needed.
        """
        cfg = self.config

        # Get message-level token usage from window manager
        msg_tokens = 0
        msg_count = 0
        compacted = 0
        if self._window is not None:
            budget_tracker = getattr(self._window, "_budget_tracker", None)
            if budget_tracker is not None:
                msg_tokens = getattr(budget_tracker, "active_tokens", 0)
            transcript = getattr(self._window, "_transcript", None)
            if transcript is not None:
                msg_count = len(getattr(transcript, "active", []))
                compacted = len(getattr(transcript, "compacted", []))

        used = cfg.system_prompt_tokens + cfg.memory_tokens + msg_tokens
        effective_budget = cfg.total_tokens - cfg.system_prompt_tokens - cfg.memory_tokens
        available = max(0, cfg.total_tokens - used)
        ratio = used / cfg.total_tokens if cfg.total_tokens > 0 else 0.0

        return ContextSnapshot(
            total_budget=cfg.total_tokens,
            system_prompt_tokens=cfg.system_prompt_tokens,
            memory_tokens=cfg.memory_tokens,
            message_tokens=msg_tokens,
            available_tokens=available,
            usage_ratio=round(ratio, 4),
            needs_compaction=ratio >= 0.75,
            needs_offload=ratio >= 0.60,
            messages_count=msg_count,
            compacted_count=compacted,
        )

    def record_turn(self) -> None:
        """Record that a new conversational turn has occurred."""
        self._turn_count += 1

    def should_check_compaction(self) -> bool:
        """Determine whether to run a compaction check (incremental mode).

        In incremental mode, compaction checks only run every N turns
        instead of every turn, reducing overhead.
        """
        if not self.config.incremental_compaction:
            return True
        turns_since = self._turn_count - self.config._last_compaction_turn
        return turns_since >= self.config.incremental_check_interval

    def compact(self, *, model_client: Any = None) -> bool:
        """Run compaction if needed.

        Returns True if compaction was performed, False otherwise.
        """
        snap = self.snapshot()
        if not snap.needs_compaction:
            return False

        if not self.should_check_compaction():
            logger.debug("Skipping compaction check (incremental interval not reached)")
            return False

        if self._window is not None:
            # Try importance-based compaction first
            compact_fn = getattr(self._window, "compact_with_importance", None)
            if compact_fn is not None and self.config.compaction_strategy in (
                CompactionStrategy.HYBRID,
                CompactionStrategy.LLM_DRIVEN,
            ):
                try:
                    compact_fn(model_client=model_client)
                    self._compaction_count += 1
                    self.config._last_compaction_turn = self._turn_count
                    logger.info(
                        "Importance-based compaction completed (turn %d, count %d)",
                        self._turn_count, self._compaction_count,
                    )
                    return True
                except Exception as exc:
                    logger.warning("Importance-based compaction failed: %s", exc)

            # Fallback to standard compaction
            try:
                self._window.compact_if_needed()
                self._compaction_count += 1
                self.config._last_compaction_turn = self._turn_count
                logger.info(
                    "Standard compaction completed (turn %d, count %d)",
                    self._turn_count, self._compaction_count,
                )
                return True
            except Exception as exc:
                logger.error("Compaction failed: %s", exc)

        return False

    def status(self) -> dict[str, Any]:
        """Return a status summary for monitoring / API responses."""
        snap = self.snapshot()
        return {
            "turn_count": self._turn_count,
            "compaction_count": self._compaction_count,
            "offload_count": self._offload_count,
            "compaction_strategy": self.config.compaction_strategy.value,
            "incremental_compaction": self.config.incremental_compaction,
            "context": {
                "total_budget": snap.total_budget,
                "system_prompt_tokens": snap.system_prompt_tokens,
                "memory_tokens": snap.memory_tokens,
                "message_tokens": snap.message_tokens,
                "available_tokens": snap.available_tokens,
                "usage_ratio": snap.usage_ratio,
                "messages_count": snap.messages_count,
                "compacted_count": snap.compacted_count,
            },
        }


__all__ = [
    "OrchestratorConfig",
    "ContextSnapshot",
    "ContextOrchestrator",
]
