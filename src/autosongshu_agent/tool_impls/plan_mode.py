"""Plan mode tools.

Ported from claw-code's EnterPlanMode/ExitPlanMode tools.
Allows the agent to switch between planning and execution modes.
"""
from __future__ import annotations

import time
from typing import Any

from agentscope.tool import ToolResponse

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _tool_response, _error_response

registry.create_group(
    "plan-mode",
    description="规划模式工具：在规划和执行模式之间切换。",
    risk_level=ToolRiskLevel.LOW,
)


@registry.register(
    "plan-mode",
    description="进入规划模式。在规划模式下，agent 将专注于分析和制定计划，不执行任何修改操作。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=False,
)
def enter_plan_mode(
    runtime: PentestRuntime,
    description: str = "",
) -> ToolResponse:
    """Enter plan mode for analysis and planning.

    Args:
        description: What you plan to analyze or plan for.
    """
    try:
        if not hasattr(runtime, "_plan_mode"):
            runtime._plan_mode = False
        runtime._plan_mode = True
        runtime._plan_mode_description = description
        runtime._plan_mode_entered_at = time.time()

        return _tool_response({
            "ok": True,
            "plan_mode": True,
            "description": description,
            "message": "已进入规划模式。当前专注于分析和制定计划。",
        })
    except Exception as exc:
        return _error_response(exc)


@registry.register(
    "plan-mode",
    description="退出规划模式，恢复正常的执行模式。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=False,
)
def exit_plan_mode(
    runtime: PentestRuntime,
) -> ToolResponse:
    """Exit plan mode and resume normal execution mode.

    Args:
        (none)
    """
    try:
        if not hasattr(runtime, "_plan_mode"):
            runtime._plan_mode = False

        was_in_plan_mode = runtime._plan_mode
        runtime._plan_mode = False
        duration = 0
        if hasattr(runtime, "_plan_mode_entered_at"):
            duration = time.time() - runtime._plan_mode_entered_at

        return _tool_response({
            "ok": True,
            "plan_mode": False,
            "was_in_plan_mode": was_in_plan_mode,
            "planning_duration_seconds": round(duration, 1),
            "message": "已退出规划模式，恢复正常执行。",
        })
    except Exception as exc:
        return _error_response(exc)
