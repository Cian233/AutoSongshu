"""
Selectors - Derived state from AppState.

Selectors compute derived state from AppState. Use them to:
- Avoid duplicating computation logic
- Create reusable derived state
- Encapsulate complex state access patterns

Inspired by claw-code's state/selectors.ts
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class ActiveAgentForInput(TypedDict):
    """Active agent context for input handling."""

    type: Literal["leader", "viewed", "named_agent"]
    task: dict[str, Any] | None


def get_active_agent_for_input(app_state: dict[str, Any]) -> ActiveAgentForInput:
    """
    Determine which agent is active for input handling.

    Returns a discriminated union:
    - {type: "viewed", task: ...} if viewing a teammate task
    - {type: "named_agent", task: ...} if viewing a specific agent task
    - {type: "leader"} otherwise
    """
    viewed_task = get_viewed_teammate_task(app_state)
    if viewed_task:
        return {"type": "viewed", "task": viewed_task}

    viewing_agent_task_id = app_state.get("viewing_agent_task_id")
    if viewing_agent_task_id:
        tasks = app_state.get("tasks", {})
        task = tasks.get(viewing_agent_task_id)
        if task and task.get("type") == "local_agent":
            return {"type": "named_agent", "task": task}

    return {"type": "leader", "task": None}


def get_viewed_teammate_task(app_state: dict[str, Any]) -> dict[str, Any] | None:
    """Get the currently viewed teammate task, if any."""
    expanded_view = app_state.get("expanded_view")
    if expanded_view != "teammates":
        return None

    tasks = app_state.get("tasks", {})
    # Find first running task
    for task_id, task in tasks.items():
        if task.get("status") == "running":
            return task

    return None


def get_model_for_request(app_state: dict[str, Any]) -> str:
    """
    Get the model to use for the next API request.

    Priority:
    1. Explicit override
    2. main_loop_model from state
    3. Default model
    """
    model = app_state.get("model_override") or app_state.get("main_loop_model")
    return model or "default"


def get_permission_mode(app_state: dict[str, Any]) -> str:
    """Get current permission mode."""
    return app_state.get("tool_permission_context", {}).get("mode", "auto")


def is_thinking_enabled(app_state: dict[str, Any]) -> bool:
    """Check if thinking is enabled for current model."""
    return app_state.get("thinking_enabled", False) or False


def get_enabled_tools_count(app_state: dict[str, Any]) -> int:
    """Get count of enabled tools (excluding MCP for now)."""
    # In a real implementation, this would count actual enabled tools
    return len(app_state.get("tools", []))


def should_show_progress_bar(app_state: dict[str, Any]) -> bool:
    """Check if progress bar should be shown."""
    tasks = app_state.get("tasks", {})
    running_tasks = sum(1 for t in tasks.values() if t.get("status") == "running")
    return running_tasks > 0
