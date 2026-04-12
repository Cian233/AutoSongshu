"""Team collaboration tools.

Ported from claw-code's TeamCreate/TeamDelete tools. Allows creating
teams of sub-agents that can work in parallel on complex assessments.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from agentscope.tool import ToolResponse

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _tool_response, _error_response

registry.create_group(
    "team",
    description="团队协作工具：创建和管理子 Agent 团队，并行执行复杂任务。",
    risk_level=ToolRiskLevel.HIGH,
    requires_approval=True,
)


def _get_team_store(runtime: PentestRuntime) -> dict[str, dict[str, Any]]:
    if not hasattr(runtime, "_team_store"):
        runtime._team_store = {}
    return runtime._team_store


@registry.register(
    "team",
    description="创建一个子 Agent 团队来并行执行多个任务。每个任务由一个独立的 Agent 处理。",
    risk_level=ToolRiskLevel.HIGH,
    dedupe=False,
    requires_approval=True,
)
def team_create(
    runtime: PentestRuntime,
    name: str,
    tasks: str,
) -> ToolResponse:
    """Create a team of sub-agents for parallel task execution.

    Args:
        name: Team name.
        tasks: JSON array of task objects, each with "prompt" (required) and "description" (optional).
    """
    try:
        task_list = json.loads(tasks)
        if not isinstance(task_list, list) or not task_list:
            return _tool_response({"ok": False, "error": "tasks 必须是非空 JSON 数组"})

        team_id = uuid.uuid4().hex[:12]
        agent_tasks = []
        for i, t in enumerate(task_list):
            if not isinstance(t, dict) or not t.get("prompt"):
                return _tool_response({"ok": False, "error": f"任务 #{i + 1} 缺少 prompt 字段"})
            agent_id = uuid.uuid4().hex[:8]
            agent_tasks.append({
                "agent_id": agent_id,
                "prompt": t["prompt"],
                "description": t.get("description", ""),
                "status": "pending",
            })

        team = {
            "team_id": team_id,
            "name": name,
            "status": "created",
            "created_at": time.time(),
            "tasks": agent_tasks,
        }

        store = _get_team_store(runtime)
        store[team_id] = team

        return _tool_response({
            "ok": True,
            "team_id": team_id,
            "name": name,
            "agent_count": len(agent_tasks),
            "status": "created",
            "message": f"团队 '{name}' 已创建，包含 {len(agent_tasks)} 个子 Agent",
        })
    except json.JSONDecodeError:
        return _tool_response({"ok": False, "error": "tasks 参数必须是 JSON 数组"})
    except Exception as exc:
        return _error_response(exc)


@registry.register(
    "team",
    description="删除一个团队并停止所有关联的任务。",
    risk_level=ToolRiskLevel.HIGH,
    dedupe=False,
    requires_approval=True,
)
def team_delete(
    runtime: PentestRuntime,
    team_id: str,
) -> ToolResponse:
    """Delete a team and stop all its tasks.

    Args:
        team_id: The team ID to delete.
    """
    try:
        store = _get_team_store(runtime)
        team = store.pop(team_id, None)
        if team is None:
            return _tool_response({"ok": False, "error": f"团队不存在: {team_id}"})

        # Mark all tasks as stopped
        for task in team.get("tasks", []):
            task["status"] = "stopped"

        return _tool_response({
            "ok": True,
            "team_id": team_id,
            "message": f"团队 '{team.get('name', team_id)}' 已删除",
        })
    except Exception as exc:
        return _error_response(exc)
