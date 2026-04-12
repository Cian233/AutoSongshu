from __future__ import annotations

from typing import Any

from agentscope.tool import ToolResponse

from ..runtime import PentestRuntime
from .registry import registry
from .utils import _error_response, _parse_json_object, _tool_response

registry.create_group(
    "http-analysis",
    description="Direct HTTP requests and low-risk web security analysis.",
    active=True,
)

def _http_request_allows_dedupe(arguments: dict[str, Any]) -> bool:
    return str(arguments.get("method") or "GET").strip().upper() in {"GET", "HEAD", "OPTIONS"}

def _http_request_invalidates_cache(arguments: dict[str, Any]) -> bool:
    return not _http_request_allows_dedupe(arguments)

@registry.register(
    "http-analysis",
    dedupe=_http_request_allows_dedupe,
    invalidates_cache=_http_request_invalidates_cache,
    max_retries=2,
)
def http_request(
    runtime: PentestRuntime,
    method: str,
    url: str,
    params_json: str = "{}",
    headers_json: str = "{}",
    json_body: str = "{}",
    form_body: str = "{}",
    follow_redirects: bool = False,
) -> ToolResponse:
    """Send an HTTP request to an in-scope URL. Bodies should be JSON objects encoded as strings."""
    try:
        return _tool_response(
            runtime.http.request(
                method=method,
                url=url,
                params=_parse_json_object(params_json),
                headers={str(k): str(v) for k, v in _parse_json_object(headers_json).items()},
                json_body=_parse_json_object(json_body) or None,
                form_body=_parse_json_object(form_body) or None,
                follow_redirects=follow_redirects,
            ),
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("http-analysis")
def analyze_security_headers(runtime: PentestRuntime, url: str) -> ToolResponse:
    """Inspect common response security headers and obvious cookie-flag gaps."""
    try:
        return _tool_response(runtime.http.analyze_security_headers(url))
    except Exception as exc:
        return _error_response(exc)

@registry.register(
    "http-analysis",
    dedupe=_http_request_allows_dedupe,
    invalidates_cache=_http_request_invalidates_cache,
    max_retries=2,
)
def http_raw_request(
    runtime: PentestRuntime,
    method: str,
    url: str,
    params_json: str = "{}",
    headers_json: str = "{}",
    raw_body: str = "",
    content_type: str = "application/octet-stream",
    follow_redirects: bool = False,
) -> ToolResponse:
    """Send an HTTP request with a raw string body (no JSON serialization). Use this when you need exact byte-level control over the request body, e.g. to prevent double-encoding of percent-encoded characters like %0A, or to send crafted payloads for WAF testing, CRLF injection, etc. The raw_body is transmitted exactly as provided."""
    try:
        return _tool_response(
            runtime.http.raw_request(
                method=method,
                url=url,
                params=_parse_json_object(params_json) or None,
                headers={str(k): str(v) for k, v in _parse_json_object(headers_json).items()} or None,
                raw_body=raw_body or None,
                content_type=content_type,
                follow_redirects=follow_redirects,
            ),
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("http-analysis")
def http_discover_surface(
    runtime: PentestRuntime,
    url: str = "",
    max_pages: int = 6,
    max_candidates_per_page: int = 40,
    max_passive_files: int = 8,
) -> ToolResponse:
    """Perform low-impact same-origin discovery using shallow GET crawling, passive files, and route/API hint extraction."""
    try:
        return _tool_response(
            runtime.http.discover_surface(
                url=url or runtime.scope.start_url,
                max_pages=max_pages,
                max_candidates_per_page=max_candidates_per_page,
                max_passive_files=max_passive_files,
            ),
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("http-analysis")
def probe_reflection(
    runtime: PentestRuntime,
    url: str,
    parameter: str = "q",
    marker: str = "AUTOSONGSHU_REFLECT_12345",
) -> ToolResponse:
    """Inject a low-risk marker into a GET parameter and report whether it is reflected in the response preview."""
    try:
        return _tool_response(
            runtime.http.probe_reflection(url, parameter=parameter, marker=marker),
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("http-analysis")
def analyze_csrf_surface(runtime: PentestRuntime) -> ToolResponse:
    """Heuristically inspect current browser forms for POST actions that appear to lack CSRF-style hidden fields."""
    try:
        forms = runtime.browser.list_forms()
        suspicious = []
        for form in forms:
            if form.get("method", "GET").upper() != "POST":
                continue
            inputs = form.get("inputs", [])
            has_token = any(
                any(
                    keyword in (item.get("name") or "").lower()
                    for keyword in ("csrf", "xsrf", "token", "authenticity")
                )
                for item in inputs
            )
            if not has_token:
                suspicious.append(
                    {
                        "action": form.get("action"),
                        "method": form.get("method"),
                        "reason": "No obvious CSRF-style hidden input detected",
                    },
                )

        return _tool_response(
            {
                "heuristic": True,
                "suspicious_forms": suspicious,
                "current_url": runtime.browser.current_url(),
            },
        )
    except Exception as exc:
        return _error_response(exc)
