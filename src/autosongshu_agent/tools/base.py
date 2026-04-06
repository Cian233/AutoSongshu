"""
Tool interface and build_tool() pattern.

Inspired by claw-code's Tool.ts:362-695 and buildTool() pattern.

Key design:
- Tool has 30+ methods, but most are optional
- build_tool() provides fail-closed defaults
- Default values are conservative (assume unsafe)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable


@dataclass
class PermissionResult:
    """Result of a permission check."""

    behavior: str  # "allow", "ask", "deny"
    updated_input: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def allow(cls, updated_input: dict[str, Any] | None = None) -> "PermissionResult":
        return cls(behavior="allow", updated_input=updated_input)

    @classmethod
    def ask(cls, reason: str = "") -> "PermissionResult":
        return cls(behavior="ask", error=reason)

    @classmethod
    def deny(cls, reason: str = "") -> "PermissionResult":
        return cls(behavior="deny", error=reason)


@runtime_checkable
class Tool(Protocol):
    """
    Protocol for a tool.

    A tool is a microservice with:
    - Identity (name, description)
    - Schema (input/output validation)
    - Execution (call method)
    - Security (permissions, concurrency, read-only)
    - UI (render methods)
    """

    # Identity
    name: str
    description: str
    aliases: list[str]
    search_hint: str

    # Execution
    async def call(
        self,
        input_data: dict[str, Any],
        context: Any,
    ) -> dict[str, Any]:
        """Execute the tool."""
        ...

    # Security - all methods have fail-closed defaults
    def is_enabled(self) -> bool:
        """Is this tool available in current environment?"""
        ...

    def is_concurrency_safe(self, input_data: dict[str, Any]) -> bool:
        """Can this tool run concurrently with others? Default: False (assume unsafe)"""
        ...

    def is_read_only(self, input_data: dict[str, Any]) -> bool:
        """Does this tool only read, not write? Default: False (assume writes)"""
        ...

    def is_destructive(self, input_data: dict[str, Any]) -> bool:
        """Is this tool destructive (cannot be undone)?"""
        ...

    def check_permissions(
        self,
        input_data: dict[str, Any],
        context: Any | None = None,
    ) -> PermissionResult:
        """Check permissions for this tool. Default: allow (handled by outer pipeline)"""
        ...

    def user_facing_name(self, input_data: dict[str, Any]) -> str:
        """Human-readable name for this tool call."""
        ...


@dataclass
class ToolDef:
    """
    Tool definition for build_tool().

    Only requires essential fields; build_tool() fills in safe defaults.
    """

    name: str
    description: str
    call: Callable

    # Optional - build_tool will provide defaults
    input_schema: Any = None
    output_schema: Any = None
    aliases: list[str] = field(default_factory=list)
    search_hint: str = ""

    # Security - optional, will get fail-closed defaults
    is_enabled: Callable[[], bool] | None = None
    is_concurrency_safe: Callable[[dict], bool] | None = None
    is_read_only: Callable[[dict], bool] | None = None
    is_destructive: Callable[[dict], bool] | None = None
    check_permissions: Callable[[dict, Any | None], PermissionResult] | None = None
    user_facing_name: Callable[[dict], str] | None = None

    # Execution metadata
    max_result_size_chars: int = 100_000


# Fail-closed defaults - assume the worst case
TOOL_DEFAULTS = {
    "is_enabled": lambda: True,
    "is_concurrency_safe": lambda _: False,  # Assume NOT safe to run concurrently
    "is_read_only": lambda _: False,  # Assume WRITES data
    "is_destructive": lambda _: False,
    "check_permissions": lambda input_data, context=None: PermissionResult.allow(
        input_data
    ),
    "user_facing_name": lambda _: "",
}


@dataclass
class BuiltTool:
    """
    A tool with all defaults filled in.

    Created by build_tool(). Guaranteed to have all methods.
    """

    name: str
    description: str
    call: Callable
    input_schema: Any
    output_schema: Any
    aliases: list[str]
    search_hint: str

    is_enabled: Callable[[], bool]
    is_concurrency_safe: Callable[[dict], bool]
    is_read_only: Callable[[dict], bool]
    is_destructive: Callable[[dict], bool]
    check_permissions: Callable[[dict, Any | None], PermissionResult]
    user_facing_name: Callable[[dict], str]

    max_result_size_chars: int


def build_tool(def_: ToolDef) -> BuiltTool:
    """
    Build a tool with fail-closed defaults.

    This ensures:
    1. All security methods have conservative defaults
    2. Tool authors can't forget to implement safety checks
    3. Default behavior is safe (fail-closed)

    Inspired by claw-code's Tool.ts:757-792
    """
    return BuiltTool(
        # Required fields
        name=def_.name,
        description=def_.description,
        call=def_.call,
        input_schema=def_.input_schema,
        output_schema=def_.output_schema,
        aliases=def_.aliases,
        search_hint=def_.search_hint,
        # Apply defaults: TOOL_DEFAULTS → user_facing_name default → def_
        is_enabled=def_.is_enabled or TOOL_DEFAULTS["is_enabled"],
        is_concurrency_safe=def_.is_concurrency_safe
        or TOOL_DEFAULTS["is_concurrency_safe"],
        is_read_only=def_.is_read_only or TOOL_DEFAULTS["is_read_only"],
        is_destructive=def_.is_destructive or TOOL_DEFAULTS["is_destructive"],
        check_permissions=def_.check_permissions or TOOL_DEFAULTS["check_permissions"],
        user_facing_name=def_.user_facing_name or (lambda _: def_.name),
        max_result_size_chars=def_.max_result_size_chars,
    )
