from __future__ import annotations

import json
import os
from typing import Any

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def parse_bool_env(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    return default


def parse_int_env(key: str, default: int = 0) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (ValueError, TypeError):
        return default


def parse_float_env(key: str, default: float = 0.0) -> float:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except (ValueError, TypeError):
        return default


def parse_list_env(key: str, default: list[str] | None = None) -> list[str]:
    if default is None:
        default = []
    raw = os.getenv(key)
    if not raw:
        return default
    stripped = str(raw).strip()
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    normalized = stripped.replace("\r\n", "\n").replace(";", "\n").replace(",", "\n")
    return [item.strip() for item in normalized.split("\n") if item.strip()]


def _parse_bool(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"Invalid boolean env value: {raw!r}")
