"""Step-level data models for the agent execution pipeline.

Provides lightweight data classes that capture the state and metadata of
individual agent steps, the overall task lifecycle, and token usage
tracking -- aligned with the Trae MTC dynamic-planning architecture.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StepState(enum.Enum):
    """State of a single agent step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskState(enum.Enum):
    """Overall state of a task / session."""

    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TokenUsage:
    """Token consumption record for a single step or turn."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, other: TokenUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens

    def to_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
        }


@dataclass
class AgentStep:
    """Represents a single step in the agent's execution trajectory."""

    index: int = 0
    state: StepState = StepState.PENDING
    action: str = ""
    observation: str = ""
    tool_name: str = ""
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        token_usage = (
            self.token_usage.to_dict()
            if hasattr(self.token_usage, "to_dict")
            else self.token_usage
        )
        return {
            "index": self.index,
            "state": self.state.value,
            "action": self.action,
            "observation": self.observation,
            "tool_name": self.tool_name,
            "tool_arguments": self.tool_arguments,
            "token_usage": token_usage,
            "timestamp": self.timestamp,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


__all__ = ["AgentStep", "StepState", "TaskState", "TokenUsage"]
