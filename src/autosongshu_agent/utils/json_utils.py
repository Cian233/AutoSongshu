from __future__ import annotations

import json
from typing import Any


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def pretty_json(value: Any, indent: int = 2) -> str:
    return json.dumps(value, ensure_ascii=False, indent=indent, default=str)


def safe_json_loads(text: str | bytes | None, default: Any = None) -> Any:
    if not text:
        return default
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return default
