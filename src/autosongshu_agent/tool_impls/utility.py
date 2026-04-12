"""Utility tools: Sleep, StructuredOutput, ToolSearch.

Ported from claw-code's utility tools for convenience operations.
"""
from __future__ import annotations

import json
import time
from typing import Any

from agentscope.tool import ToolResponse

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _tool_response, _error_response

registry.create_group(
    "utility",
    description="便利工具：等待、结构化输出、工具搜索。",
    risk_level=ToolRiskLevel.LOW,
)


@registry.register(
    "utility",
    description="等待指定秒数。适用于等待页面加载、延迟请求等场景。不占用 shell 进程。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=True,
)
def sleep(
    runtime: PentestRuntime,
    seconds: float = 1.0,
) -> ToolResponse:
    """Wait for the specified number of seconds.

    Args:
        seconds: Number of seconds to wait (0.1 - 60).
    """
    try:
        seconds = max(0.1, min(float(seconds), 60.0))
        time.sleep(seconds)
        return _tool_response({
            "ok": True,
            "slept_seconds": seconds,
            "message": f"已等待 {seconds} 秒",
        })
    except Exception as exc:
        return _error_response(exc)


@registry.register(
    "utility",
    description="以请求的格式返回结构化输出。适用于需要将结果格式化为 JSON、CSV 等特定格式的场景。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=False,
)
def structured_output(
    runtime: PentestRuntime,
    content: str,
    format: str = "json",
) -> ToolResponse:
    """Return structured output in the requested format.

    Args:
        content: The content to format.
        format: Output format: "json", "markdown", "csv", "text".
    """
    try:
        fmt = str(format).strip().lower()
        if fmt == "json":
            try:
                parsed = json.loads(content)
                formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                formatted = content
        elif fmt == "csv":
            # If already CSV-like, pass through; otherwise wrap
            formatted = content
        elif fmt == "markdown":
            formatted = content
        else:
            formatted = content

        return _tool_response({
            "ok": True,
            "format": fmt,
            "content": formatted,
        })
    except Exception as exc:
        return _error_response(exc)


@registry.register(
    "utility",
    description="按名称或关键词搜索可用的工具列表。适用于查找特定功能的工具。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=True,
)
def tool_search(
    runtime: PentestRuntime,
    query: str,
    max_results: int = 10,
) -> ToolResponse:
    """Search for available tools by name or keyword.

    Args:
        query: Search query (tool name or keyword).
        max_results: Maximum number of results to return.
    """
    try:
        from .registry import registry as _registry

        query_lower = query.strip().lower()
        all_tools = _registry.list_tools()

        # Score each tool by relevance
        scored: list[tuple[int, dict[str, str]]] = []
        for tool in all_tools:
            name = tool.get("name", "").lower()
            desc = tool.get("description", "").lower()
            group = tool.get("group", "").lower()

            score = 0
            if query_lower in name:
                score += 100
            if query_lower in desc:
                score += 50
            if query_lower in group:
                score += 20
            # Partial match
            for word in query_lower.split():
                if word in name:
                    score += 30
                if word in desc:
                    score += 10

            if score > 0:
                scored.append((score, tool))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [tool for _, tool in scored[:max(1, int(max_results))]]

        return _tool_response({
            "ok": True,
            "query": query,
            "total_available": len(all_tools),
            "matched": len(results),
            "results": results,
        })
    except Exception as exc:
        return _error_response(exc)
