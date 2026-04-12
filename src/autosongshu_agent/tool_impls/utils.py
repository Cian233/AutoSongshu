from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

_MAX_IMAGE_BYTES = 10 * 1024 * 1024


def _tool_response(payload: Any) -> ToolResponse:
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            ),
        ],
    )


def _image_response(
    file_path: str,
    description: str = "",
) -> ToolResponse:
    """Build a *ToolResponse* that includes an image loaded from *file_path*.

    The response content contains two blocks:

    1. A short text description of the image.
    2. An ``image_url`` block carrying the base64-encoded image data.

    The ``SafeOpenAIChatFormatter`` post-processor will recognise the
    ``image_url`` block and pass it through to the LLM API so the model
    can actually *see* the image content.
    """
    path = Path(file_path)
    if not path.is_file():
        return _tool_response({"ok": False, "error": f"File not found: {file_path}"})

    size = path.stat().st_size
    if size > _MAX_IMAGE_BYTES:
        return _tool_response({
            "ok": False,
            "error": f"Image too large ({size} bytes, max {_MAX_IMAGE_BYTES})",
        })
    if size == 0:
        return _tool_response({"ok": False, "error": "Image file is empty"})

    try:
        data = path.read_bytes()
    except Exception as exc:
        return _tool_response({"ok": False, "error": f"Failed to read image: {exc}"})

    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    b64 = base64.b64encode(data).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    desc = description or f"Image loaded from {file_path} ({mime}, {size} bytes)"
    content: list[Any] = [
        TextBlock(type="text", text=desc),
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    return ToolResponse(content=content)


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
