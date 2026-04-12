"""Cron/scheduled task tools.

Ported from claw-code's CronCreate/CronDelete/CronList tools.
Allows creating scheduled recurring tasks for periodic checks.
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
    "cron",
    description="定时任务工具：创建、列出和删除定时循环任务。",
    risk_level=ToolRiskLevel.HIGH,
    requires_approval=True,
)


def _get_cron_store(runtime: PentestRuntime) -> dict[str, dict[str, Any]]:
    if not hasattr(runtime, "_cron_store"):
        runtime._cron_store = {}
    return runtime._cron_store


@registry.register(
    "cron",
    description="创建一个定时循环任务，按 cron 表达式定期执行。",
    risk_level=ToolRiskLevel.HIGH,
    dedupe=False,
    requires_approval=True,
)
def cron_create(
    runtime: PentestRuntime,
    schedule: str,
    prompt: str,
    description: str = "",
) -> ToolResponse:
    """Create a scheduled recurring task.

    Args:
        schedule: Cron expression (e.g. "*/30 * * * *" for every 30 minutes).
        prompt: Task prompt to execute on each schedule tick.
        description: Human-readable description.
    """
    try:
        cron_id = uuid.uuid4().hex[:12]
        store = _get_cron_store(runtime)

        cron = {
            "cron_id": cron_id,
            "schedule": schedule,
            "prompt": prompt,
            "description": description or prompt[:100],
            "status": "active",
            "created_at": time.time(),
            "last_run": None,
            "run_count": 0,
        }
        store[cron_id] = cron

        return _tool_response({
            "ok": True,
            "cron_id": cron_id,
            "schedule": schedule,
            "status": "active",
            "message": f"定时任务已创建 (ID: {cron_id}, 调度: {schedule})",
        })
    except Exception as exc:
        return _error_response(exc)


@registry.register(
    "cron",
    description="删除一个定时循环任务。",
    risk_level=ToolRiskLevel.MEDIUM,
    dedupe=False,
)
def cron_delete(
    runtime: PentestRuntime,
    cron_id: str,
) -> ToolResponse:
    """Delete a scheduled task.

    Args:
        cron_id: The cron task ID to delete.
    """
    try:
        store = _get_cron_store(runtime)
        cron = store.pop(cron_id, None)
        if cron is None:
            return _tool_response({"ok": False, "error": f"定时任务不存在: {cron_id}"})

        return _tool_response({
            "ok": True,
            "cron_id": cron_id,
            "message": f"定时任务 {cron_id} 已删除",
        })
    except Exception as exc:
        return _error_response(exc)


@registry.register(
    "cron",
    description="列出所有定时循环任务。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=True,
)
def cron_list(
    runtime: PentestRuntime,
) -> ToolResponse:
    """List all scheduled tasks.

    Args:
        (none)
    """
    try:
        store = _get_cron_store(runtime)
        crons = list(store.values())
        crons.sort(key=lambda c: c.get("created_at", 0), reverse=True)

        return _tool_response({
            "ok": True,
            "total": len(crons),
            "tasks": crons,
        })
    except Exception as exc:
        return _error_response(exc)
