from __future__ import annotations

import json
from typing import Any

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

def _tool_response(payload: Any) -> ToolResponse:
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            ),
        ],
    )

def _error_response(exc: Exception) -> ToolResponse:
    return _tool_response({"ok": False, "error": str(exc)})

def _parse_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object.")
    return parsed

def _parse_list_like(raw: str) -> list[str]:
    cleaned = raw.strip()
    if not cleaned:
        return []
    if cleaned.startswith("["):
        parsed = json.loads(cleaned)
        if not isinstance(parsed, list):
            raise ValueError("Expected a JSON list.")
        return [str(item) for item in parsed]
    return [line.strip() for line in cleaned.splitlines() if line.strip()]

def _parse_json_list(raw: str) -> list[str]:
    if not raw.strip():
        return []
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("Expected a JSON list.")
    return [str(item) for item in parsed]

def _parse_json_object_list(raw: str) -> list[dict[str, Any]]:
    if not raw.strip():
        return []
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("Expected a JSON list.")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(parsed, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Expected edit #{index} to be a JSON object.")
        result.append(item)
    return result

def _parse_package_specs(raw: str) -> list[str]:
    cleaned = raw.strip()
    if not cleaned:
        return []
    if cleaned.startswith("["):
        return _parse_json_list(cleaned)
    if "\n" in cleaned or "," in cleaned:
        normalized = cleaned.replace(",", "\n")
        return [item.strip() for item in normalized.splitlines() if item.strip()]
    return [item.strip() for item in cleaned.split() if item.strip()]
