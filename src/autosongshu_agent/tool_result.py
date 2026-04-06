"""Tool execution result patterns.

Provides immutable result dataclasses for tool execution, replacing
exception-based error handling with explicit result types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolExecutionResult:
    """Result of a tool execution attempt.

    Similar to claw-code's ToolExecution pattern - uses explicit
    success/failure flags instead of exceptions.
    """

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    success: bool = False
    handled: bool = False  # Whether the tool was actually executed
    output: Any = None
    error: str | None = None
    execution_time_ms: int = 0

    @classmethod
    def success_result(
        cls,
        tool_name: str,
        output: Any,
        arguments: dict[str, Any] | None = None,
        execution_time_ms: int = 0,
    ) -> "ToolExecutionResult":
        """Create a successful result."""
        return cls(
            tool_name=tool_name,
            arguments=arguments or {},
            success=True,
            handled=True,
            output=output,
            error=None,
            execution_time_ms=execution_time_ms,
        )

    @classmethod
    def error_result(
        cls,
        tool_name: str,
        error: str,
        arguments: dict[str, Any] | None = None,
        handled: bool = True,
    ) -> "ToolExecutionResult":
        """Create an error result."""
        return cls(
            tool_name=tool_name,
            arguments=arguments or {},
            success=False,
            handled=handled,
            output=None,
            error=error,
        )

    @classmethod
    def permission_denied(
        cls,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        reason: str = "Permission denied",
    ) -> "ToolExecutionResult":
        """Create a permission denied result (not handled)."""
        return cls(
            tool_name=tool_name,
            arguments=arguments or {},
            success=False,
            handled=False,  # Not handled because permission denied
            output=None,
            error=reason,
        )

    @classmethod
    def not_found(
        cls,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> "ToolExecutionResult":
        """Create a 'tool not found' result."""
        return cls(
            tool_name=tool_name,
            arguments=arguments or {},
            success=False,
            handled=False,
            output=None,
            error=f"Unknown tool: {tool_name}",
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize result to dict."""
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "success": self.success,
            "handled": self.handled,
            "output": self.output,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
        }

    def summary(self) -> str:
        """Get a one-line summary of the result."""
        if self.success:
            return f"✓ {self.tool_name} succeeded"
        if not self.handled:
            return f"⊘ {self.tool_name} not executed: {self.error}"
        return f"✗ {self.tool_name} failed: {self.error}"


@dataclass(frozen=True)
class ToolBatchResult:
    """Result of executing multiple tools."""

    results: tuple[ToolExecutionResult, ...] = field(default_factory=tuple)

    @property
    def all_succeeded(self) -> bool:
        """Check if all tools succeeded."""
        return all(r.success for r in self.results)

    @property
    def any_succeeded(self) -> bool:
        """Check if any tool succeeded."""
        return any(r.success for r in self.results)

    @property
    def failed_results(self) -> list[ToolExecutionResult]:
        """Get all failed results."""
        return [r for r in self.results if not r.success]

    def get_result(self, tool_name: str) -> ToolExecutionResult | None:
        """Get result for a specific tool by name."""
        for result in self.results:
            if result.tool_name == tool_name:
                return result
        return None

    def summary(self) -> str:
        """Get batch summary."""
        total = len(self.results)
        succeeded = sum(1 for r in self.results if r.success)
        return f"{succeeded}/{total} tools succeeded"


__all__ = [
    "ToolExecutionResult",
    "ToolBatchResult",
]
