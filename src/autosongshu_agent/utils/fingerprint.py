from __future__ import annotations

import hashlib
import json
from typing import Any


_LOOP_GUARD_META_TOOLS = frozenset(
    {"create_plan", "update_subtask_state", "plan_subtasks", "get_plan_status"}
)


def stable_fingerprint(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()


def _should_track_loop_guard_tool(tool_name: str) -> bool:
    return str(tool_name or "").strip().lower() not in _LOOP_GUARD_META_TOOLS


def tool_call_signature(block: dict[str, Any]) -> str | None:
    name = str(block.get("name") or "").strip()
    if not name or not _should_track_loop_guard_tool(name):
        return None
    arguments = block.get("input", block.get("arguments"))
    return f"{name}:{stable_fingerprint(arguments)}"


def tool_result_signature(block: dict[str, Any]) -> str | None:
    name = str(block.get("name") or "").strip()
    if not name or not _should_track_loop_guard_tool(name):
        return None
    content = block.get("content", block.get("output"))
    return f"{name}:{stable_fingerprint(content)}"
