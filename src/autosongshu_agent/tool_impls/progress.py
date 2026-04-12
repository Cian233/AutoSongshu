"""Progress reporting tool -- lets the agent report semantic step progress."""
from __future__ import annotations

from typing import Any

from agentscope.tool import ToolResponse
from agentscope.message import TextBlock

from .registry import registry


registry.create_group(
    "progress",
    description="Report high-level assessment progress to the user.",
    active=True,
)


@registry.register("progress", dedupe=False)
def update_progress(
    current_step: str,
    total_steps: int | None = None,
    status: str = "in_progress",
    detail: str = "",
) -> ToolResponse:
    """Report the current progress of the assessment.

    Use this tool to communicate high-level progress to the user.
    This is separate from automatic tool-call tracking.

    Args:
        current_step: A short description of what you are doing now
            (e.g. "Mapping attack surface", "Testing XSS on login form").
        total_steps: Optional total number of planned steps.
        status: One of "in_progress", "completed", "failed", "blocked".
        detail: Optional additional context about this step.
    """
    valid_statuses = {"in_progress", "completed", "failed", "blocked"}
    if status not in valid_statuses:
        status = "in_progress"

    text = f"Progress: {current_step}"
    if total_steps is not None and total_steps > 0:
        text += f" (step reported)"
    if detail:
        text += f"\n{detail}"

    return ToolResponse(content=[TextBlock(type="text", text=text)])


# Tool specification for registration
PROGRESS_TOOL_SPEC = {
    "name": "update_progress",
    "description": update_progress.__doc__,
    "parameters": {
        "type": "object",
        "properties": {
            "current_step": {
                "type": "string",
                "description": "Short description of the current step",
            },
            "total_steps": {
                "type": "integer",
                "description": "Optional total number of planned steps",
            },
            "status": {
                "type": "string",
                "enum": ["in_progress", "completed", "failed", "blocked"],
                "description": "Status of the current step",
            },
            "detail": {
                "type": "string",
                "description": "Optional additional context",
            },
        },
        "required": ["current_step"],
    },
}
