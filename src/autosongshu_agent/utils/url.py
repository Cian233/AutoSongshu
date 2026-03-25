from __future__ import annotations

import re
from urllib.parse import urlparse

ABSOLUTE_URL_PATTERN = re.compile(r"https?://[^\s\"'<>\\)]+", re.IGNORECASE)


def extract_absolute_urls(text: str) -> list[str]:
    matches = ABSOLUTE_URL_PATTERN.findall(str(text or ""))
    urls: list[str] = []
    seen: set[str] = set()
    for raw in matches:
        candidate = raw.rstrip(".,;:!?)]}>'\"")
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def safe_host_from_url(url: str) -> str | None:
    try:
        return urlparse(url).hostname
    except Exception:
        return None


def normalize_base_url(url: str | None) -> str:
    if not url:
        return ""
    url = str(url).strip()
    if not url:
        return ""
    parsed = urlparse(url)
    scheme = parsed.scheme or "https"
    host = parsed.hostname or ""
    if not host:
        return ""
    port = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
    return f"{scheme}://{host}{port}"
