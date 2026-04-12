"""Multi-layered context window management strategy.

Implements a four-tier approach inspired by modern Agent Harness design:

1. **Progressive Disclosure** — minimize initial context by loading tool
   descriptions and reference material on demand rather than at startup.
2. **Tool Output Offloading** — when a tool returns more than a threshold
   number of characters, keep only a summary in-context and persist the
   full output to disk.
3. **Compaction** — when the context approaches the configured limit,
   summarize older turns to free up space.
4. **Context Reset** — as a last resort, clear the context window
   entirely and start a fresh agent with structured hand-off artifacts.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ContextBudget:
    """Tracks how much of the context window is consumed."""

    total_tokens: int = 128000
    reserved_tokens: int = 8000
    used_tokens: int = 0
    tool_output_threshold_chars: int = 8000

    @property
    def available_tokens(self) -> int:
        return max(0, self.total_tokens - self.reserved_tokens - self.used_tokens)

    @property
    def usage_ratio(self) -> float:
        effective = self.total_tokens - self.reserved_tokens
        return self.used_tokens / effective if effective > 0 else 0.0

    @property
    def needs_compaction(self) -> bool:
        return self.usage_ratio >= 0.85

    @property
    def needs_reset(self) -> bool:
        return self.usage_ratio >= 0.95


@dataclass
class OffloadedOutput:
    """Reference to a tool output that has been moved out of the context."""

    tool_name: str
    call_signature: str
    summary: str
    file_path: str | None = None
    original_chars: int = 0


class ContextStrategy(ABC):
    """Base class for context management strategies."""

    @abstractmethod
    def should_offload(self, tool_name: str, output: str) -> bool: ...

    @abstractmethod
    def offload(self, tool_name: str, call_signature: str, output: str) -> OffloadedOutput: ...

    @abstractmethod
    def build_reference(self, offloaded: OffloadedOutput) -> str: ...


class ThresholdOffloadStrategy(ContextStrategy):
    """Offload tool outputs that exceed a character threshold."""

    def __init__(
        self,
        threshold_chars: int = 8000,
        summary_head: int = 2000,
        summary_tail: int = 2000,
    ) -> None:
        self.threshold_chars = threshold_chars
        self.summary_head = summary_head
        self.summary_tail = summary_tail

    def should_offload(self, tool_name: str, output: str) -> bool:
        return len(output) > self.threshold_chars

    def offload(
        self, tool_name: str, call_signature: str, output: str
    ) -> OffloadedOutput:
        if len(output) <= self.summary_head + self.summary_tail:
            summary = output
        else:
            summary = (
                output[: self.summary_head]
                + f"\n\n... [{len(output) - self.summary_head - self.summary_tail} chars truncated] ...\n\n"
                + output[-self.summary_tail :]
            )
        return OffloadedOutput(
            tool_name=tool_name,
            call_signature=call_signature,
            summary=summary,
            original_chars=len(output),
        )

    def build_reference(self, offloaded: OffloadedOutput) -> str:
        ref = (
            f"[{offloaded.tool_name}] Output truncated "
            f"({offloaded.original_chars:,} chars). Summary:\n{offloaded.summary}"
        )
        if offloaded.file_path:
            ref += f"\nFull output saved to: {offloaded.file_path}"
        return ref


class ContextManager:
    """Orchestrates multi-layered context management.

    Usage::

        cm = ContextManager(budget=ContextBudget(total_tokens=128000))
        if cm.budget.needs_compaction:
            cm.compact(turns)
        if strategy.should_offload(tool_name, output):
            offloaded = strategy.offload(tool_name, sig, output)
            reference = strategy.build_reference(offloaded)
    """

    def __init__(
        self,
        budget: ContextBudget | None = None,
        offload_strategy: ContextStrategy | None = None,
    ) -> None:
        self.budget = budget or ContextBudget()
        self.offload_strategy = offload_strategy or ThresholdOffloadStrategy()
        self._offloaded_outputs: list[OffloadedOutput] = []

    def process_tool_output(
        self,
        tool_name: str,
        call_signature: str,
        output: str,
    ) -> str:
        """Decide whether to offload a tool output; return the text to keep in-context."""
        if self.offload_strategy.should_offload(tool_name, output):
            offloaded = self.offload_strategy.offload(tool_name, call_signature, output)
            self._offloaded_outputs.append(offloaded)
            return self.offload_strategy.build_reference(offloaded)
        return output

    def estimate_tokens(self, text: str, chars_per_token: float = 2.0) -> int:
        """Rough token estimate based on character count."""
        return int(len(text) / chars_per_token)

    def update_usage(self, additional_chars: int) -> None:
        """Update the used-token counter."""
        self.budget.used_tokens += self.estimate_tokens(additional_chars)

    @property
    def offloaded_outputs(self) -> list[OffloadedOutput]:
        return list(self._offloaded_outputs)

    def status(self) -> dict[str, Any]:
        return {
            "budget": {
                "total_tokens": self.budget.total_tokens,
                "reserved_tokens": self.budget.reserved_tokens,
                "used_tokens": self.budget.used_tokens,
                "available_tokens": self.budget.available_tokens,
                "usage_ratio": round(self.budget.usage_ratio, 4),
                "needs_compaction": self.budget.needs_compaction,
                "needs_reset": self.budget.needs_reset,
            },
            "offloaded_count": len(self._offloaded_outputs),
        }


__all__ = [
    "ContextBudget",
    "OffloadedOutput",
    "ContextStrategy",
    "ThresholdOffloadStrategy",
    "ContextManager",
]
