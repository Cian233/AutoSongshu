"""
Tool registry - Single source of truth with three-layer filtering.

Inspired by claw-code's tools.ts:
- getAllBaseTools(): Single registration point
- Three-layer filtering: Compile-time DCE → Load-time env → Runtime isEnabled()
- assembleToolPool(): Merge built-in + MCP tools with stable ordering
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from .base import BuiltTool, ToolDef, build_tool


@dataclass
class ToolRegistry:
    """
    Registry for all tools.

    Single source of truth - all tools are registered here.
    """

    _tools: list[BuiltTool]

    def get_tool(self, name: str) -> BuiltTool | None:
        """Get a tool by name (case-insensitive)."""
        name_lower = name.lower()
        for tool in self._tools:
            if tool.name.lower() == name_lower:
                return tool
            if any(alias.lower() == name_lower for alias in tool.aliases):
                return tool
        return None

    def get_all_tools(self) -> list[BuiltTool]:
        """Get all registered tools."""
        return self._tools.copy()

    def get_tool_names(self) -> list[str]:
        """Get all tool names."""
        return [t.name for t in self._tools]


# Feature flag simulation (in real implementation, use a proper feature flag system)
def feature(flag_name: str) -> bool:
    """Check if a feature flag is enabled."""
    return os.environ.get(f"FEATURE_{flag_name.upper()}", "").lower() in (
        "true",
        "1",
        "yes",
    )


def is_env_truthy(env_var: str) -> bool:
    """Check if an environment variable is truthy."""
    return os.environ.get(env_var, "").lower() in ("true", "1", "yes")


# Placeholder tool definitions - will be replaced with actual implementations
_BROWSER_TOOLS: list[ToolDef] = []
_HTTP_TOOLS: list[ToolDef] = []
_SANDBOX_TOOLS: list[ToolDef] = []
_SKILL_TOOLS: list[ToolDef] = []
_FINDING_TOOLS: list[ToolDef] = []
_KNOWLEDGE_TOOLS: list[ToolDef] = []


def register_tool_group(group_name: str, tools: list[ToolDef]) -> None:
    """Register a group of tools."""
    if group_name == "browser":
        _BROWSER_TOOLS.extend(tools)
    elif group_name == "http":
        _HTTP_TOOLS.extend(tools)
    elif group_name == "sandbox":
        _SANDBOX_TOOLS.extend(tools)
    elif group_name == "skills":
        _SKILL_TOOLS.extend(tools)
    elif group_name == "findings":
        _FINDING_TOOLS.extend(tools)
    elif group_name == "knowledge":
        _KNOWLEDGE_TOOLS.extend(tools)


def get_all_base_tools() -> list[BuiltTool]:
    """
    Get all base tools - Single source of truth.

    Three-layer filtering:
    1. Compile-time DCE (feature flags) - removes entire code paths
    2. Load-time filtering (environment variables) - for version differentiation
    3. Runtime filtering (isEnabled()) - for dynamic conditions

    Inspired by claw-code's tools.ts:193-251
    """
    tools: list[BuiltTool] = []

    # Static imports - always included
    for tool_def in (
        _BROWSER_TOOLS
        + _HTTP_TOOLS
        + _SANDBOX_TOOLS
        + _SKILL_TOOLS
        + _FINDING_TOOLS
        + _KNOWLEDGE_TOOLS
    ):
        tools.append(build_tool(tool_def))

    # Layer 1: Compile-time DCE (feature flags)
    # Example: SleepTool only included if PROACTIVE feature is enabled
    # if feature("PROACTIVE"):
    #     tools.append(SleepTool)

    # Layer 2: Load-time filtering (environment variables)
    # Example: ConfigTool only for internal users
    # if os.environ.get("USER_TYPE") == "ant":
    #     tools.append(ConfigTool)

    # Layer 3: Runtime filtering happens in get_tools()

    return tools


def filter_tools_by_deny_rules(
    tools: list[BuiltTool],
    permission_context: Any,
) -> list[BuiltTool]:
    """Filter tools by deny rules from permission context."""
    if permission_context is None:
        return tools

    deny_names = getattr(permission_context, "deny_names", frozenset())
    deny_prefixes = getattr(permission_context, "deny_prefixes", ())

    if not deny_names and not deny_prefixes:
        return tools

    filtered = []
    for tool in tools:
        name_lower = tool.name.lower()
        if name_lower in deny_names:
            continue
        if any(name_lower.startswith(prefix) for prefix in deny_prefixes):
            continue
        filtered.append(tool)

    return filtered


def get_tools(
    permission_context: Any = None,
    simple_mode: bool = False,
) -> list[BuiltTool]:
    """
    Get available tools after applying all filters.

    Filtering pipeline:
    1. Simple mode check
    2. Get all base tools
    3. Apply deny rules
    4. Apply isEnabled() check

    Inspired by claw-code's tools.ts:271-327
    """
    # Simple mode: only essential tools
    if simple_mode or is_env_truthy("AUTOSONGSHU_SIMPLE_MODE"):
        return []  # In real implementation, return [BashTool, ReadTool, EditTool]

    # Get all base tools
    tools = get_all_base_tools()

    # Apply deny rules
    allowed_tools = filter_tools_by_deny_rules(tools, permission_context)

    # Apply isEnabled() check
    enabled_tools = [t for t in allowed_tools if t.is_enabled()]

    return enabled_tools


def assemble_tool_pool(
    permission_context: Any = None,
    mcp_tools: list[BuiltTool] | None = None,
    simple_mode: bool = False,
) -> list[BuiltTool]:
    """
    Assemble the final tool pool: built-in + MCP tools.

    Merges built-in tools with MCP tools, sorts by name for prompt cache stability.
    Built-in tools take precedence over MCP tools with the same name.

    Inspired by claw-code's tools.ts:345-367
    """
    built_in_tools = get_tools(permission_context, simple_mode)
    mcp_tools = mcp_tools or []

    # Filter MCP tools by deny rules
    allowed_mcp_tools = filter_tools_by_deny_rules(mcp_tools, permission_context)

    # Sort by name for prompt cache stability
    built_in_sorted = sorted(built_in_tools, key=lambda t: t.name)
    mcp_sorted = sorted(allowed_mcp_tools, key=lambda t: t.name)

    # Merge: built-in first, then MCP (built-in takes precedence on name collision)
    seen_names = set()
    result = []

    for tool in built_in_sorted:
        if tool.name not in seen_names:
            seen_names.add(tool.name)
            result.append(tool)

    for tool in mcp_sorted:
        if tool.name not in seen_names:
            seen_names.add(tool.name)
            result.append(tool)

    return result


# Global registry instance
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get the global tool registry."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry(_tools=get_all_base_tools())
    return _registry


def reset_registry() -> None:
    """Reset the global registry (for testing)."""
    global _registry
    _registry = None
