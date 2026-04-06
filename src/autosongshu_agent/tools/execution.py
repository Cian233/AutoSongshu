"""
Tool execution - Concurrent and serial execution.

Inspired by claw-code's services/tools/toolOrchestration.ts:
- partition_tool_calls(): Split into concurrency-safe batches
- run_tools_concurrently(): Execute safe tools in parallel
- run_tools_serially(): Execute unsafe tools one by one
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from .base import BuiltTool
from .result import ToolExecutionResult


@dataclass
class ToolBatch:
    """A batch of tool calls to execute together."""

    is_concurrency_safe: bool
    blocks: list[dict[str, Any]]


def find_tool_by_name(tools: list[BuiltTool], name: str) -> BuiltTool | None:
    """Find a tool by name (case-insensitive)."""
    name_lower = name.lower()
    for tool in tools:
        if tool.name.lower() == name_lower:
            return tool
    return None


def partition_tool_calls(
    tool_use_messages: list[dict[str, Any]],
    tools: list[BuiltTool],
) -> list[ToolBatch]:
    """
    Partition tool calls into concurrency-safe batches.

    Algorithm:
    1. Parse input with Zod (validation)
    2. Check is_concurrency_safe() for each tool
    3. Consecutive safe tools -> merge into one batch
    4. Unsafe tools -> separate batch each

    Inspired by claw-code's services/tools/toolOrchestration.ts:91-116
    """
    batches: list[ToolBatch] = []

    for tool_use in tool_use_messages:
        tool_name = tool_use.get("name", "")
        tool_input = tool_use.get("input", {})

        tool = find_tool_by_name(tools, tool_name)

        # Determine if concurrency safe
        is_safe = False
        if tool:
            try:
                is_safe = tool.is_concurrency_safe(tool_input)
            except Exception:
                # On error, assume unsafe (fail-closed)
                is_safe = False

        # Merge consecutive safe tools into one batch
        if is_safe and batches and batches[-1].is_concurrency_safe:
            batches[-1].blocks.append(tool_use)
        else:
            batches.append(
                ToolBatch(
                    is_concurrency_safe=is_safe,
                    blocks=[tool_use],
                )
            )

    return batches


async def execute_tool(
    tool: BuiltTool,
    input_data: dict[str, Any],
    context: Any,
) -> ToolExecutionResult:
    """Execute a single tool."""
    try:
        result = await tool.call(input_data, context)
        return ToolExecutionResult.success_result(
            tool_name=tool.name,
            output=result,
            arguments=input_data,
        )
    except Exception as e:
        return ToolExecutionResult.error_result(
            tool_name=tool.name,
            error=str(e),
            arguments=input_data,
        )


async def run_tools_concurrently(
    blocks: list[dict[str, Any]],
    tools: list[BuiltTool],
    context: Any,
    max_concurrency: int = 10,
) -> AsyncGenerator[ToolExecutionResult, None]:
    """
    Execute multiple tools concurrently.

    Uses asyncio semaphore to limit concurrency.
    Results are yielded as they complete (not in order).
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def run_with_semaphore(block: dict[str, Any]) -> ToolExecutionResult:
        async with semaphore:
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})

            tool = find_tool_by_name(tools, tool_name)
            if not tool:
                return ToolExecutionResult.not_found(tool_name, tool_input)

            return await execute_tool(tool, tool_input, context)

    tasks = [run_with_semaphore(block) for block in blocks]

    for coro in asyncio.as_completed(tasks):
        yield await coro


async def run_tools_serially(
    blocks: list[dict[str, Any]],
    tools: list[BuiltTool],
    context: Any,
) -> AsyncGenerator[ToolExecutionResult, None]:
    """
    Execute tools one by one (serially).

    Each tool waits for the previous one to complete.
    """
    for block in blocks:
        tool_name = block.get("name", "")
        tool_input = block.get("input", {})

        tool = find_tool_by_name(tools, tool_name)
        if not tool:
            yield ToolExecutionResult.not_found(tool_name, tool_input)
            continue

        result = await execute_tool(tool, tool_input, context)
        yield result


async def run_tools(
    tool_use_messages: list[dict[str, Any]],
    tools: list[BuiltTool],
    context: Any,
    max_concurrency: int = 10,
) -> AsyncGenerator[ToolExecutionResult, None]:
    """
    Execute all tool calls with proper concurrency handling.

    Pipeline:
    1. Partition into safe/unsafe batches
    2. Execute safe batches concurrently
    3. Execute unsafe batches serially

    Inspired by claw-code's services/tools/toolOrchestration.ts:19-82
    """
    batches = partition_tool_calls(tool_use_messages, tools)

    for batch in batches:
        if batch.is_concurrency_safe:
            async for result in run_tools_concurrently(
                batch.blocks, tools, context, max_concurrency
            ):
                yield result
        else:
            async for result in run_tools_serially(batch.blocks, tools, context):
                yield result
