from __future__ import annotations

from typing import Any


def truncate_text(value: str | None, limit: int = 320, ellipsis: str = "...") -> str:
    stripped = str(value or "").strip()
    if len(stripped) <= limit:
        return stripped
    if limit <= len(ellipsis):
        return stripped[:limit]
    return f"{stripped[: limit - len(ellipsis)]}{ellipsis}"


def normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().split())


def dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = normalize_text(raw)
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def merge_priority_strings(
    primary: list[str],
    secondary: list[str],
    *,
    limit: int = 8,
) -> list[str]:
    return dedupe_strings([*primary, *secondary])[:limit]
