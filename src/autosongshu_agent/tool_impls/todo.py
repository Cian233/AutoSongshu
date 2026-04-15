"""Todo/Task list management tool.

Ported from claw-code's TodoWrite tool. Allows the agent to maintain a
structured task list for complex, multi-step security assessments.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agentscope.tool import ToolResponse

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _tool_response, _error_response

registry.create_group(
    "task-management",
    description="任务管理工具：维护结构化的任务列表，跟踪多步骤评估进度。",
    risk_level=ToolRiskLevel.LOW,
)

# Status enum values
_TODO_STATUSES = {"pending", "in_progress", "completed"}


@registry.register(
    "task-management",
    description="更新当前会话的结构化任务列表。用于规划和跟踪多步骤安全评估的进度。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=False,
    invalidates_cache=False,
)
def todo_write(
    runtime: PentestRuntime,
    todos: str,
    merge: bool = True,
) -> ToolResponse:
    """Update the structured task list for the current session.

    Args:
        todos: JSON array of todo items. Each item has:
            - content (str, required): Task description.
            - status (str, required): One of "pending", "in_progress", "completed".
            - id (str, optional): Unique identifier. Auto-generated if not provided.
        merge: If true, merge with existing todos (update by id, add new, remove missing).
               If false, replace the entire todo list.
    """
    try:
        # Parse todos
        try:
            todo_list = json.loads(todos)
        except json.JSONDecodeError:
            return _tool_response({"ok": False, "error": "todos 参数必须是 JSON 数组格式"})

        if not isinstance(todo_list, list):
            return _tool_response({"ok": False, "error": "todos 参数必须是 JSON 数组"})

        # Validate and normalize
        normalized: list[dict[str, Any]] = []
        for i, item in enumerate(todo_list):
            if not isinstance(item, dict):
                return _tool_response({"ok": False, "error": f"todo #{i + 1} 必须是 JSON 对象"})
            content = str(item.get("content") or "").strip()
            if not content:
                return _tool_response({"ok": False, "error": f"todo #{i + 1} 缺少 content 字段"})
            status = str(item.get("status") or "pending").strip().lower()
            if status not in _TODO_STATUSES:
                status = "pending"
            todo_id = str(item.get("id") or f"todo_{i}_{int(time.time())}")
            normalized.append({
                "id": todo_id,
                "content": content,
                "status": status,
            })

        # Load existing todos
        # Use project-level workspace for cross-session todo sharing
        todo_file = runtime.sandbox.workspace_dir / "todos.json"
        old_todos: list[dict[str, Any]] = []
        if merge and todo_file.exists():
            try:
                old_todos = json.loads(todo_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                old_todos = []

        if merge:
            # Merge: update existing by id, add new
            old_map = {t["id"]: t for t in old_todos}
            for todo in normalized:
                old_map[todo["id"]] = todo
            merged = list(old_map.values())
            # Remove items not in new list
            new_ids = {t["id"] for t in normalized}
            merged = [t for t in merged if t["id"] in new_ids]
            final = merged
        else:
            final = normalized

        # Persist
        todo_file.write_text(
            json.dumps(final, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        completed = sum(1 for t in final if t["status"] == "completed")
        total = len(final)

        return _tool_response({
            "ok": True,
            "todos": final,
            "total": total,
            "completed": completed,
            "pending": total - completed,
        })
    except Exception as exc:
        return _error_response(exc)
