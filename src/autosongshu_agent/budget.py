"""Token budget management with pre-flight checks.

Inspired by claw-code's budget-based termination pattern.
Checks token budget BEFORE expensive LLM calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BudgetConfig:
    """Configuration for token budget management."""

    max_input_tokens: int = 100000
    max_output_tokens: int = 50000
    max_total_tokens: int = 150000
    max_turns: int = 20
    warning_threshold: float = 0.8  # Warn at 80% of budget

    def check_budget(
        self,
        current_input: int,
        current_output: int,
        projected_input: int = 0,
        projected_output: int = 0,
    ) -> "BudgetCheckResult":
        """Check if projected usage is within budget."""
        total_input = current_input + projected_input
        total_output = current_output + projected_output
        total = total_input + total_output

        # Check individual limits
        if total_input > self.max_input_tokens:
            return BudgetCheckResult(
                allowed=False,
                reason=f"Input token budget exceeded: {total_input} > {self.max_input_tokens}",
                remaining_input=0,
                remaining_output=max(0, self.max_output_tokens - total_output),
            )

        if total_output > self.max_output_tokens:
            return BudgetCheckResult(
                allowed=False,
                reason=f"Output token budget exceeded: {total_output} > {self.max_output_tokens}",
                remaining_input=max(0, self.max_input_tokens - total_input),
                remaining_output=0,
            )

        if total > self.max_total_tokens:
            return BudgetCheckResult(
                allowed=False,
                reason=f"Total token budget exceeded: {total} > {self.max_total_tokens}",
                remaining_input=max(0, self.max_input_tokens - total_input),
                remaining_output=max(0, self.max_output_tokens - total_output),
            )

        # Check if approaching limit (warning threshold)
        input_ratio = (
            total_input / self.max_input_tokens if self.max_input_tokens > 0 else 0
        )
        output_ratio = (
            total_output / self.max_output_tokens if self.max_output_tokens > 0 else 0
        )
        total_ratio = total / self.max_total_tokens if self.max_total_tokens > 0 else 0

        is_warning = any(
            r > self.warning_threshold for r in (input_ratio, output_ratio, total_ratio)
        )

        return BudgetCheckResult(
            allowed=True,
            reason=None,
            remaining_input=self.max_input_tokens - total_input,
            remaining_output=self.max_output_tokens - total_output,
            is_warning=is_warning,
            usage_ratio=total_ratio,
        )


@dataclass(frozen=True)
class BudgetCheckResult:
    """Result of a budget check."""

    allowed: bool
    reason: str | None
    remaining_input: int
    remaining_output: int
    is_warning: bool = False
    usage_ratio: float = 0.0

    @property
    def should_stop(self) -> bool:
        """Whether execution should stop due to budget."""
        return not self.allowed

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "remaining_input": self.remaining_input,
            "remaining_output": self.remaining_output,
            "is_warning": self.is_warning,
            "usage_ratio": round(self.usage_ratio, 2),
        }


@dataclass
class BudgetTracker:
    """Tracks token usage against budget."""

    config: BudgetConfig = field(default_factory=BudgetConfig)
    input_tokens: int = 0
    output_tokens: int = 0
    turn_count: int = 0
    _history: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        """Total tokens used."""
        return self.input_tokens + self.output_tokens

    def add_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        label: str = "turn",
    ) -> BudgetCheckResult:
        """Add usage and check if still within budget."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self._history.append(
            {
                "label": label,
                "input": input_tokens,
                "output": output_tokens,
                "timestamp": __import__("datetime").datetime.now().isoformat(),
            }
        )
        return self.config.check_budget(self.input_tokens, self.output_tokens)

    def check_before_call(
        self,
        estimated_input: int = 0,
        estimated_output: int = 0,
    ) -> BudgetCheckResult:
        """Check budget before making an expensive call."""
        return self.config.check_budget(
            self.input_tokens,
            self.output_tokens,
            estimated_input,
            estimated_output,
        )

    def increment_turn(self) -> bool:
        """Increment turn counter, return True if within limit."""
        self.turn_count += 1
        return self.turn_count <= self.config.max_turns

    def get_remaining(self) -> dict[str, int]:
        """Get remaining budget."""
        result = self.config.check_budget(self.input_tokens, self.output_tokens)
        return {
            "input": result.remaining_input,
            "output": result.remaining_output,
            "total": result.remaining_input + result.remaining_output,
            "turns": max(0, self.config.max_turns - self.turn_count),
        }

    def get_summary(self) -> dict[str, Any]:
        """Get budget summary."""
        total = self.total_tokens
        max_total = self.config.max_total_tokens
        ratio = total / max_total if max_total > 0 else 0

        return {
            "input_used": self.input_tokens,
            "output_used": self.output_tokens,
            "total_used": total,
            "input_limit": self.config.max_input_tokens,
            "output_limit": self.config.max_output_tokens,
            "total_limit": max_total,
            "usage_ratio": round(ratio, 2),
            "turn_count": self.turn_count,
            "turn_limit": self.config.max_turns,
            "remaining": self.get_remaining(),
        }

    def reset(self) -> None:
        """Reset tracker."""
        self.input_tokens = 0
        self.output_tokens = 0
        self.turn_count = 0
        self._history.clear()


__all__ = [
    "BudgetConfig",
    "BudgetCheckResult",
    "BudgetTracker",
]
