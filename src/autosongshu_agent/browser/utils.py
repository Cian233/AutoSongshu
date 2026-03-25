from __future__ import annotations

from typing import Any

_TEXTUAL_CONTENT_TYPE_MARKERS = (
    "application/json",
    "application/javascript",
    "application/x-javascript",
    "application/ecmascript",
    "application/xml",
    "application/xhtml+xml",
    "application/x-www-form-urlencoded",
    "application/ld+json",
    "text/",
    "html",
    "xml",
    "svg",
    "css",
    "javascript",
    "json",
)
_TEXTUAL_RESOURCE_TYPES = {
    "Document",
    "Fetch",
    "Manifest",
    "Script",
    "Stylesheet",
    "XHR",
    "document",
    "fetch",
    "manifest",
    "script",
    "stylesheet",
    "xhr",
}
MAX_NETWORK_EVENTS = 1200
MAX_CONSOLE_EVENTS = 400
MAX_RESPONSE_BODIES = 400


def truncate_text(value: str | None, max_chars: int) -> str | None:
    if value is None:
        return None
    if len(value) <= max_chars:
        return value
    return value[:max_chars]


def append_bounded(
    items: list[dict[str, Any]], item: dict[str, Any], limit: int
) -> None:
    items.append(item)
    if len(items) > limit:
        del items[:-limit]


def is_textual_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    lowered = content_type.lower()
    return any(marker in lowered for marker in _TEXTUAL_CONTENT_TYPE_MARKERS)


def is_textual_resource(
    resource_type: str | None, content_type: str | None = None
) -> bool:
    if resource_type in _TEXTUAL_RESOURCE_TYPES:
        return True
    return is_textual_content_type(content_type)
