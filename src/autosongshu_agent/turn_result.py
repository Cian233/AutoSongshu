"""Agent turn result with stop reason tracking.

Inspired by claw-code's TurnResult pattern - tracks why execution stopped
(completed, max_turns, max_budget, error, interrupted).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class StopReason(Enum):
    """Reason why agent execution stopped."""

    COMPLETED = auto()  # Normal completion
    MAX_TURNS_REACHED = auto()  # Hit iteration limit
    MAX_BUDGET_REACHED = auto()  # Hit token budget
    INTERRUPTED = auto()  # User interrupted
    ERROR = auto()  # Execution error
    LOOP_GUARD = auto()  # Loop guard triggered
    TIMEOUT = auto()  # Timeout

    def is_success(self) -> bool:
        """Check if this is a successful stop reason."""
        return self in (StopReason.COMPLETED,)

    def is_error(self) -> bool:
        """Check if this is an error stop reason."""
        return self in (
            StopReason.ERROR,
            StopReason.TIMEOUT,
            StopReason.LOOP_GUARD,
        )

    def description(self) -> str:
        """Human-readable description."""
        descriptions = {
            StopReason.COMPLETED: "正常完成",
            StopReason.MAX_TURNS_REACHED: "达到最大回合数",
            StopReason.MAX_BUDGET_REACHED: "达到 Token 预算上限",
            StopReason.INTERRUPTED: "用户中断",
            StopReason.ERROR: "执行错误",
            StopReason.LOOP_GUARD: "循环保护触发",
            StopReason.TIMEOUT: "执行超时",
        }
        return descriptions.get(self, "未知原因")


@dataclass(frozen=True)
class TurnResult:
    """Result of a single agent turn.

    Similar to claw-code's TurnResult - immutable with explicit stop reason.
    """

    assistant_message: str
    stop_reason: StopReason
    blocks: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    turn_number: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Whether the turn completed successfully."""
        return self.stop_reason == StopReason.COMPLETED

    @property
    def should_continue(self) -> bool:
        """Whether execution should continue to next turn."""
        return self.stop_reason in (
            StopReason.COMPLETED,
            StopReason.LOOP_GUARD,
        )

    @property
    def total_tokens(self) -> int:
        """Total tokens used in this turn."""
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "assistant_message": self.assistant_message,
            "stop_reason": self.stop_reason.name,
            "stop_reason_description": self.stop_reason.description(),
            "success": self.success,
            "should_continue": self.should_continue,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "turn_number": self.turn_number,
            "error_message": self.error_message,
            "metadata": self.metadata,
        }

    def summary(self) -> str:
        """Get one-line summary."""
        if self.success:
            return f"✓ Turn {self.turn_number} completed ({self.total_tokens} tokens)"
        if self.stop_reason == StopReason.MAX_TURNS_REACHED:
            return f"⊘ Turn {self.turn_number} stopped: max turns reached"
        if self.stop_reason == StopReason.MAX_BUDGET_REACHED:
            return f"⊘ Turn {self.turn_number} stopped: budget exceeded"
        if self.stop_reason == StopReason.INTERRUPTED:
            return f"⊘ Turn {self.turn_number} interrupted"
        if self.error_message:
            return f"✗ Turn {self.turn_number} error: {self.error_message}"
        return f"✗ Turn {self.turn_number} stopped: {self.stop_reason.description()}"


@dataclass(frozen=True)
class AgentExecutionResult:
    """Complete result of agent execution across multiple turns.

    Aggregates turn results and provides final summary.
    """

    turns: tuple[TurnResult, ...] = field(default_factory=tuple)
    final_message: str = ""
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    @property
    def turn_count(self) -> int:
        """Number of turns executed."""
        return len(self.turns)

    @property
    def total_tokens(self) -> int:
        """Total tokens across all turns."""
        return self.total_input_tokens + self.total_output_tokens

    @property
    def final_stop_reason(self) -> StopReason | None:
        """Stop reason of the last turn."""
        if not self.turns:
            return None
        return self.turns[-1].stop_reason

    @property
    def success(self) -> bool:
        """Whether execution completed successfully."""
        if not self.turns:
            return False
        return self.turns[-1].success

    @property
    def has_errors(self) -> bool:
        """Whether any turn had an error."""
        return any(t.stop_reason.is_error() for t in self.turns)

    def get_turn(self, number: int) -> TurnResult | None:
        """Get a specific turn by number."""
        for turn in self.turns:
            if turn.turn_number == number:
                return turn
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "turns": [t.to_dict() for t in self.turns],
            "turn_count": self.turn_count,
            "final_message": self.final_message,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "final_stop_reason": self.final_stop_reason.name
            if self.final_stop_reason
            else None,
            "success": self.success,
            "has_errors": self.has_errors,
        }

    def summary(self) -> str:
        """Get execution summary."""
        lines = [
            f"Execution completed in {self.turn_count} turns",
            f"Total tokens: {self.total_tokens}",
        ]
        if self.final_stop_reason:
            lines.append(f"Final state: {self.final_stop_reason.description()}")
        return "\n".join(lines)


__all__ = [
    "StopReason",
    "TurnResult",
    "AgentExecutionResult",
]
