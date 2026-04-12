"""Structured session lifecycle for the Agent Harness.

Inspired by Anthropic's "Effective Harnesses for Long-Running Agents" and
OpenAI's "Harness Engineering" best practices, each session follows a
deterministic lifecycle:

1. **Orient** — read progress notes, task list, recent git history
2. **Setup** — run init scripts, start dev servers / prerequisites
3. **Verify Baseline** — confirm existing functionality still works
4. **Select Task** — pick the highest-priority unfinished item
5. **Implement** — build / execute the feature or assessment step
6. **Test** — verify through actual UI / API, not just unit tests
7. **Update State** — mark task done, commit, write progress notes
8. **Clean Exit** — confirm the application is in a workable state
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


class SessionPhase(str, enum.Enum):
    """Each phase of the structured session lifecycle."""

    ORIENT = "orient"
    SETUP = "setup"
    VERIFY_BASELINE = "verify_baseline"
    SELECT_TASK = "select_task"
    IMPLEMENT = "implement"
    TEST = "test"
    UPDATE_STATE = "update_state"
    CLEAN_EXIT = "clean_exit"


@dataclass
class PhaseResult:
    """Outcome of a single lifecycle phase."""

    phase: SessionPhase
    success: bool = True
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


PhaseHandler = Callable[["SessionLifecycle"], PhaseResult]


class SessionLifecycle:
    """Manages the structured execution lifecycle of an agent session.

    The lifecycle is intentionally linear and deterministic.  Each phase
    must complete (or be explicitly skipped) before the next one begins.
    """

    def __init__(self) -> None:
        self._handlers: dict[SessionPhase, PhaseHandler] = {}
        self._history: list[PhaseResult] = []
        self._current_phase: SessionPhase | None = None
        self._metadata: dict[str, Any] = {}

    def register_handler(self, phase: SessionPhase, handler: PhaseHandler) -> None:
        """Attach a handler to a lifecycle phase."""
        self._handlers[phase] = handler

    @property
    def current_phase(self) -> SessionPhase | None:
        return self._current_phase

    @property
    def history(self) -> list[PhaseResult]:
        return list(self._history)

    @property
    def is_running(self) -> bool:
        return self._current_phase is not None

    def run_phase(self, phase: SessionPhase) -> PhaseResult:
        """Execute a single lifecycle phase."""
        self._current_phase = phase
        handler = self._handlers.get(phase)

        if handler is None:
            result = PhaseResult(
                phase=phase,
                success=True,
                message=f"Phase '{phase.value}' skipped (no handler registered).",
            )
            self._history.append(result)
            self._current_phase = None
            return result

        try:
            result = handler(self)
        except Exception as exc:
            logger.exception("Phase '%s' failed", phase.value)
            result = PhaseResult(
                phase=phase,
                success=False,
                message=f"Phase '{phase.value}' failed: {exc}",
            )

        self._history.append(result)
        self._current_phase = None
        return result

    def run_full_lifecycle(self) -> list[PhaseResult]:
        """Execute all phases in order, stopping on first failure."""
        results: list[PhaseResult] = []
        for phase in SessionPhase:
            result = self.run_phase(phase)
            results.append(result)
            if not result.success:
                logger.warning(
                    "Lifecycle stopped at phase '%s': %s",
                    phase.value,
                    result.message,
                )
                break
        return results

    def update_metadata(self, payload: dict[str, Any]) -> None:
        """Attach arbitrary metadata to the lifecycle (e.g. task list, progress notes)."""
        self._metadata.update(payload)

    @property
    def metadata(self) -> dict[str, Any]:
        return dict(self._metadata)

    def summary(self) -> dict[str, Any]:
        """Return a summary of the lifecycle execution."""
        return {
            "total_phases": len(SessionPhase),
            "completed_phases": len(self._history),
            "success": all(r.success for r in self._history),
            "current_phase": self._current_phase.value if self._current_phase else None,
            "phases": [
                {"phase": r.phase.value, "success": r.success, "message": r.message}
                for r in self._history
            ],
        }


__all__ = [
    "SessionPhase",
    "PhaseResult",
    "PhaseHandler",
    "SessionLifecycle",
]
