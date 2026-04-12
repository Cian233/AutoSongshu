"""
Tool execution result pattern.

Explicit result objects instead of exceptions for flow control.
Inspired by claw-code's ToolExecution pattern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolExecutionResult:
    """
    Result of a tool execution.

    Use explicit 'handled' flag to distinguish:
    - handled=True: tool executed but failed
    - handled=False: tool didn't execute (permission denied, not found, etc.)
    """

    tool_name: str
    success: bool
    handled: bool  # True = executed (may have failed), False = not executed
    output: dict[str, Any] = field(default_factory=dict)
    arguments: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def success_result(
        cls,
        tool_name: str,
        output: dict[str, Any],
        arguments: dict[str, Any],
    ) -> "ToolExecutionResult":
        """Create a successful result."""
        return cls(
            tool_name=tool_name,
            success=True,
            handled=True,
            output=output,
            arguments=arguments,
        )

    @classmethod
    def error_result(
        cls,
        tool_name: str,
        error: str,
        arguments: dict[str, Any],
    ) -> "ToolExecutionResult":
        """Create an error result (executed but failed)."""
        return cls(
            tool_name=tool_name,
            success=False,
            handled=True,
            error=error,
            arguments=arguments,
        )

    @classmethod
    def permission_denied(
        cls,
        tool_name: str,
        arguments: dict[str, Any],
        reason: str = "Permission denied",
    ) -> "ToolExecutionResult":
        """Create a permission denied result (not executed)."""
        return cls(
            tool_name=tool_name,
            success=False,
            handled=False,
            error=reason,
            arguments=arguments,
        )

    @classmethod
    def not_found(
        cls,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> "ToolExecutionResult":
        """Create a not found result (tool doesn't exist)."""
        return cls(
            tool_name=tool_name,
            success=False,
            handled=False,
            error=f"Tool '{tool_name}' not found",
            arguments=arguments,
        )


@dataclass
class ToolBatchResult:
    """Result of executing multiple tools."""

    results: list[ToolExecutionResult]

    @property
    def all_success(self) -> bool:
        """Check if all tools succeeded."""
        return all(r.success for r in self.results)

    @property
    def any_handled(self) -> bool:
        """Check if any tool was executed."""
        return any(r.handled for r in self.results)

    @property
    def success_count(self) -> int:
        """Count of successful executions."""
        return sum(1 for r in self.results if r.success)

    @property
    def failure_count(self) -> int:
        """Count of failed executions."""
        return sum(1 for r in self.results if not r.success and r.handled)

    @property
    def skipped_count(self) -> int:
        """Count of skipped (not executed) tools."""
        return sum(1 for r in self.results if not r.handled)
