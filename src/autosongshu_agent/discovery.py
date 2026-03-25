from __future__ import annotations

import re
from html import unescape
from urllib.parse import urldefrag, urlparse

from .config.scope import ScopePolicy, ScopeViolationError

COMMON_PASSIVE_DISCOVERY_PATHS = [
    "/robots.txt",
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/.well-known/security.txt",
    "/manifest.json",
    "/manifest.webmanifest",
    "/openapi.json",
    "/swagger.json",
]

_DISCOVERY_PRIORITY_KEYWORDS = (
    "login",
    "signin",
    "sign-in",
    "signup",
    "register",
    "auth",
    "oauth",
    "sso",
    "admin",
    "dashboard",
    "account",
    "profile",
    "settings",
    "portal",
    "console",
    "api",
    "graphql",
    "swagger",
    "openapi",
    "docs",
    "upload",
    "download",
    "search",
    "user",
    "users",
    "tenant",
)
_STATIC_ASSET_EXTENSIONS = {
    ".7z",
    ".avi",
    ".bmp",
    ".css",
    ".csv",
    ".doc",
    ".docx",
    ".eot",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".map",
    ".mov",
    ".mp3",
    ".mp4",
    ".otf",
    ".pdf",
    ".png",
    ".svg",
    ".tar",
    ".tgz",
    ".ttf",
    ".txt",
    ".wav",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
}
_ATTRIBUTE_URL_PATTERN = re.compile(
    r"""(?:href|src|action)\s*=\s*["']([^"'#>]+)["']""", re.IGNORECASE
)
_JS_CALL_URL_PATTERN = re.compile(
    r"""(?:fetch|open|axios(?:\.(?:get|post|put|patch|delete|request))?)\s*\(\s*["']([^"'<>]+)["']""",
    re.IGNORECASE,
)
_URL_FIELD_PATTERN = re.compile(r"""url\s*:\s*["']([^"'<>]+)["']""", re.IGNORECASE)
_ABSOLUTE_URL_PATTERN = re.compile(r"""https?://[^\s"'<>\\)]+""", re.IGNORECASE)
_ROOT_PATH_PATTERN = re.compile(
    r"""["'](\/(?:api|graphql|swagger|openapi|auth|login|signin|signup|register|admin|account|user|users|dashboard|docs|search|upload|download|settings|portal|console|tenant|v\d+)[^"'<>]*)["']""",
    re.IGNORECASE,
)


def normalize_discovery_candidate(
    raw: str, *, base_url: str, scope: ScopePolicy
) -> str | None:
    candidate = unescape(str(raw or "")).strip().strip("\"'")
    candidate = candidate.rstrip(".,);")
    if not candidate:
        return None
    lowered = candidate.lower()
    if lowered.startswith(("javascript:", "mailto:", "tel:", "data:", "#")):
        return None

    if candidate.startswith("//"):
        candidate = f"{urlparse(base_url).scheme}:{candidate}"

    try:
        resolved = scope.assert_in_scope(candidate, current_url=base_url)
    except ScopeViolationError:
        return None

    normalized, _fragment = urldefrag(resolved)
    return normalized


def extract_in_scope_candidate_urls(
    text: str,
    *,
    base_url: str,
    scope: ScopePolicy,
    max_candidates: int = 120,
) -> list[str]:
    if max_candidates <= 0 or not text:
        return []

    patterns = (
        _ATTRIBUTE_URL_PATTERN,
        _JS_CALL_URL_PATTERN,
        _URL_FIELD_PATTERN,
        _ROOT_PATH_PATTERN,
        _ABSOLUTE_URL_PATTERN,
    )
    candidates: set[str] = set()

    for pattern in patterns:
        for match in pattern.finditer(text):
            raw_candidate = match.group(1) if match.lastindex else match.group(0)
            normalized = normalize_discovery_candidate(
                raw_candidate, base_url=base_url, scope=scope
            )
            if not normalized:
                continue
            candidates.add(normalized)

    return prioritize_discovery_urls(
        candidates, start_url=base_url, max_items=max_candidates
    )


def is_api_like_url(url: str) -> bool:
    lowered = url.lower()
    return any(
        marker in lowered
        for marker in (
            "/api/",
            "/graphql",
            "/swagger",
            "/openapi",
            "/api-docs",
            ".json",
            "/v1/",
            "/v2/",
            "/v3/",
        )
    )


def is_queueable_discovery_url(url: str) -> bool:
    parsed = urlparse(url)
    extension = ""
    if "." in parsed.path.rsplit("/", 1)[-1]:
        extension = "." + parsed.path.rsplit(".", 1)[-1].lower()
    return extension not in _STATIC_ASSET_EXTENSIONS


def discovery_priority(url: str, *, start_url: str = "") -> int:
    lowered = url.lower()
    parsed = urlparse(url)
    score = 0

    if start_url and url == start_url:
        score -= 50
    if parsed.query:
        score -= 1
    if is_queueable_discovery_url(url):
        score += 2
    if is_api_like_url(url):
        score += 8
    for keyword in _DISCOVERY_PRIORITY_KEYWORDS:
        if keyword in lowered:
            score += 4
    depth = parsed.path.count("/")
    score += max(0, 4 - min(depth, 4))
    return score


def prioritize_discovery_urls(
    urls: list[str] | set[str],
    *,
    start_url: str = "",
    max_items: int | None = None,
) -> list[str]:
    ordered = sorted(
        {str(item) for item in urls if str(item).strip()},
        key=lambda item: (
            -discovery_priority(item, start_url=start_url),
            len(item),
            item,
        ),
    )
    if max_items is None or max_items <= 0:
        return ordered
    return ordered[:max_items]
