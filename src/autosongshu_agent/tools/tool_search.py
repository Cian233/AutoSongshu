"""
ToolSearch - Dynamic tool discovery for large tool sets.

When there are many MCP tools (tens or hundreds), including all tool definitions
in the system prompt consumes many tokens. ToolSearch solves this by:

1. Deferred tool mechanism - tools are loaded on demand
2. Keyword search - find tools by name, alias, or search_hint
3. Precise selection - select tools by exact name

Inspired by claw-code's ToolSearchTool pattern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from .base import BuiltTool


@dataclass
class ToolSearchResult:
    """Result of a tool search operation."""

    matches: list[str]
    query: str
    total_deferred: int
    mode: str  # "select" or "keyword"


def is_deferred_tool(
    tool: BuiltTool,
    *,
    always_load_names: frozenset[str] | None = None,
    enable_tool_search: bool = True,
    is_mcp_tool: bool = False,
) -> bool:
    """
    Determine if a tool should be deferred (lazy-loaded).

    Deferred tools:
    - Are listed by name in system prompt
    - Are loaded on demand via ToolSearch
    - Save token costs for large tool sets

    A tool is deferred if:
    1. It has should_defer=True (explicit opt-in)
    2. It's an MCP tool (always deferred by default)
    3. Unless it has always_load=True (explicit opt-out)

    Inspired by claw-code's tools/ToolSearchTool/prompt.ts:62-108
    """
    if not enable_tool_search:
        return False

    # ToolSearch tool itself is never deferred
    always_load = always_load_names or frozenset(["tool_search"])
    if tool.name.lower() in always_load:
        return False

    # MCP tools are always deferred (loaded on demand)
    if is_mcp_tool:
        return True

    # Check tool's explicit defer flag (stored in a custom attribute)
    # For now, we check if search_hint is set (implies tool wants to be searchable)
    return bool(tool.search_hint)


def score_tool_match(
    tool: BuiltTool,
    query_parts: set[str],
    *,
    is_mcp_tool: bool = False,
) -> float:
    """
    Score a tool against a search query.

    Scoring weights (inspired by claw-code):
    - name exact match: MCP 12 / regular 10
    - name partial match: MCP 6 / regular 5
    - search_hint match: 4
    - description match: 2

    Higher score = better match.
    """
    score = 0.0

    # Normalize tool name and aliases
    name_lower = tool.name.lower()
    aliases_lower = [a.lower() for a in tool.aliases]
    search_hint_lower = tool.search_hint.lower() if tool.search_hint else ""
    description_lower = tool.description.lower()

    for part in query_parts:
        part_lower = part.lower()

        # Name exact match (highest priority)
        if part_lower == name_lower or part_lower in aliases_lower:
            score += 12 if is_mcp_tool else 10
            continue

        # Name partial match
        if part_lower in name_lower or any(
            part_lower in alias for alias in aliases_lower
        ):
            score += 6 if is_mcp_tool else 5
            continue

        # search_hint match
        if search_hint_lower and part_lower in search_hint_lower:
            score += 4
            continue

        # description match (lowest priority)
        if part_lower in description_lower:
            score += 2

    return score


def search_tools_by_keyword(
    query: str,
    tools: list[BuiltTool],
    max_results: int = 5,
    *,
    mcp_tool_names: frozenset[str] | None = None,
) -> list[str]:
    """
    Search tools by keyword.

    Supports two modes:
    1. "select:Name1,Name2" - precise selection
    2. Free text - keyword search

    Returns tool names, sorted by relevance score.
    """
    mcp_tool_names = mcp_tool_names or frozenset()

    # Mode 1: Precise selection
    select_match = re.match(r"^select:(.+)$", query, re.IGNORECASE)
    if select_match:
        names = [n.strip() for n in select_match.group(1).split(",")]
        found = []
        for name in names:
            name_lower = name.lower()
            for tool in tools:
                if tool.name.lower() == name_lower:
                    found.append(tool.name)
                    break
        return found[:max_results]

    # Mode 2: Keyword search
    query_parts = set(re.findall(r"\w+", query.lower()))
    if not query_parts:
        return []

    # Score each tool
    scored: list[tuple[float, str]] = []
    for tool in tools:
        is_mcp = tool.name in mcp_tool_names
        score = score_tool_match(tool, query_parts, is_mcp_tool=is_mcp)
        if score > 0:
            scored.append((score, tool.name))

    # Sort by score (descending), then by name (ascending) for stability
    scored.sort(key=lambda x: (-x[0], x[1]))

    return [name for _, name in scored[:max_results]]


@dataclass
class ToolSearchConfig:
    """Configuration for ToolSearch behavior."""

    enabled: bool = True
    mode: str = "tst"  # "tst" (always defer), "tst-auto" (threshold-based), "standard" (never defer)
    auto_threshold_percent: float = 10.0  # For tst-auto mode
    max_results: int = 5


def get_tool_search_config() -> ToolSearchConfig:
    """Get ToolSearch configuration from environment."""
    import os

    env_value = os.environ.get("ENABLE_TOOL_SEARCH", "").lower()

    if env_value in ("false", "0", "no"):
        return ToolSearchConfig(enabled=False, mode="standard")

    if env_value.startswith("auto"):
        threshold = 10.0
        if ":" in env_value:
            try:
                threshold = float(env_value.split(":")[1])
            except (ValueError, IndexError):
                pass
        return ToolSearchConfig(
            enabled=True, mode="tst-auto", auto_threshold_percent=threshold
        )

    # Default: tst (always defer MCP and should_defer tools)
    return ToolSearchConfig(enabled=True, mode="tst")


def calculate_deferred_token_cost(tools: list[BuiltTool]) -> int:
    """
    Estimate the token cost of including all deferred tool definitions.

    This is used for tst-auto mode to decide if tool search should be enabled.
    """
    total_chars = 0
    for tool in tools:
        # Rough estimate: name + description + schema
        total_chars += len(tool.name)
        total_chars += len(tool.description)
        if tool.input_schema:
            total_chars += len(str(tool.input_schema))
        total_chars += 100  # Overhead per tool

    # Rough conversion: ~4 chars per token
    return total_chars // 4


def should_enable_tool_search(
    deferred_tools: list[BuiltTool],
    context_window: int = 200_000,
) -> bool:
    """
    Decide if ToolSearch should be enabled (for tst-auto mode).

    Returns True if deferred tools would consume > threshold of context window.
    """
    config = get_tool_search_config()

    if not config.enabled:
        return False

    if config.mode == "standard":
        return False

    if config.mode == "tst":
        return True

    # tst-auto: check threshold
    token_cost = calculate_deferred_token_cost(deferred_tools)
    threshold_tokens = int(context_window * config.auto_threshold_percent / 100)

    return token_cost > threshold_tokens


def build_tool_search_result_message(
    result: ToolSearchResult,
) -> str:
    """Build a human-readable message for tool search results."""
    if not result.matches:
        return f"No tools found matching '{result.query}'"

    mode_str = "Precise selection" if result.mode == "select" else "Keyword search"
    lines = [
        f"{mode_str} found {len(result.matches)} tool(s) (of {result.total_deferred} deferred):",
        "",
    ]

    for name in result.matches:
        lines.append(f"  - {name}")

    return "\n".join(lines)
