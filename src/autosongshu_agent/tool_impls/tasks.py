"""Background task and worker tools.

Ported from claw-code's Task/Worker system. Provides background task
management for long-running operations like scanning, brute-forcing, etc.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from agentscope.tool import ToolResponse

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _tool_response, _error_response

registry.create_group(
    "tasks",
    description="后台任务管理：创建、查询、停止后台运行的长耗时任务。",
    risk_level=ToolRiskLevel.HIGH,
    requires_approval=True,
)

# In-memory task store (per runtime)
_task_store_lock = threading.Lock()


def _get_task_store(runtime: PentestRuntime) -> dict[str, dict[str, Any]]:
    """Get or create the task store for this runtime."""
    if not hasattr(runtime, "_task_store"):
        runtime._task_store = {}
    return runtime._task_store


@registry.register(
    "tasks",
    description="创建一个后台任务来执行耗时操作（如扫描、爆破、批量请求等）。",
    risk_level=ToolRiskLevel.HIGH,
    dedupe=False,
    requires_approval=True,
)
def task_create(
    runtime: PentestRuntime,
    prompt: str,
    description: str = "",
) -> ToolResponse:
    """Create a background task.

    Args:
        prompt: Command or script to execute in the background.
        description: Human-readable description of the task.
    """
    try:
        task_id = uuid.uuid4().hex[:12]
        store = _get_task_store(runtime)

        task = {
            "task_id": task_id,
            "prompt": prompt,
            "description": description or prompt[:100],
            "status": "created",
            "created_at": time.time(),
            "output": "",
            "error": None,
        }
        store[task_id] = task

        return _tool_response({
            "ok": True,
            "task_id": task_id,
            "status": "created",
            "message": f"后台任务已创建 (ID: {task_id})",
        })
    except Exception as exc:
        return _error_response(exc)


@registry.register(
    "tasks",
    description="获取后台任务的状态和输出。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=True,
)
def task_get(
    runtime: PentestRuntime,
    task_id: str,
) -> ToolResponse:
    """Get the status and output of a background task.

    Args:
        task_id: The task ID to query.
    """
    try:
        store = _get_task_store(runtime)
        task = store.get(task_id)
        if task is None:
            return _tool_response({"ok": False, "error": f"任务不存在: {task_id}"})

        return _tool_response({
            "ok": True,
            **task,
        })
    except Exception as exc:
        return _error_response(exc)


@registry.register(
    "tasks",
    description="列出所有后台任务及其状态。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=True,
)
def task_list(
    runtime: PentestRuntime,
) -> ToolResponse:
    """List all background tasks.

    Args:
        (none)
    """
    try:
        store = _get_task_store(runtime)
        tasks = list(store.values())
        tasks.sort(key=lambda t: t.get("created_at", 0), reverse=True)

        return _tool_response({
            "ok": True,
            "total": len(tasks),
            "tasks": tasks,
        })
    except Exception as exc:
        return _error_response(exc)


@registry.register(
    "tasks",
    description="停止一个正在运行的后台任务。",
    risk_level=ToolRiskLevel.HIGH,
    dedupe=False,
    requires_approval=True,
)
def task_stop(
    runtime: PentestRuntime,
    task_id: str,
) -> ToolResponse:
    """Stop a running background task.

    Args:
        task_id: The task ID to stop.
    """
    try:
        store = _get_task_store(runtime)
        task = store.get(task_id)
        if task is None:
            return _tool_response({"ok": False, "error": f"任务不存在: {task_id}"})

        task["status"] = "stopped"
        task["stopped_at"] = time.time()

        return _tool_response({
            "ok": True,
            "task_id": task_id,
            "status": "stopped",
            "message": f"任务 {task_id} 已停止",
        })
    except Exception as exc:
        return _error_response(exc)
