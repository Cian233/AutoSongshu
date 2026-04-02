from __future__ import annotations

from typing import Any

from agentscope.tool import ToolResponse

from ..discovery import extract_in_scope_candidate_urls, is_api_like_url, prioritize_discovery_urls
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _error_response, _parse_json_object, _tool_response

registry.create_group(
    "browser-cdp",
    description="Browser automation, DOM inspection, and raw CDP access for in-scope targets.",
    active=True,
    notes="Prefer these tools for authenticated flows, DOM state, cookies, console logs, and JS-heavy pages.",
)

@registry.register("browser-cdp")
def browser_status(runtime: PentestRuntime) -> ToolResponse:
    """Return browser availability, current mode, active URL, and whether CDP is attached."""
    try:
        return _tool_response(runtime.browser.status())
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", invalidates_cache=True)
def browser_navigate(runtime: PentestRuntime, url: str) -> ToolResponse:
    """Navigate the active browser page to an in-scope URL."""
    try:
        return _tool_response(runtime.browser.navigate(url))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp")
def browser_snapshot(
    runtime: PentestRuntime,
    max_chars: int = 8000,
    max_forms: int = 40,
    max_inputs: int = 40,
    max_links: int = 120,
    storage_items: int = 50,
) -> ToolResponse:
    """Return a structured page snapshot including title, forms, links, text, and browser storage."""
    try:
        return _tool_response(
            runtime.browser.snapshot(
                max_chars=max_chars,
                max_forms=max_forms,
                max_inputs=max_inputs,
                max_links=max_links,
                storage_items=storage_items,
            ),
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False)
def browser_wait_for_load_state(runtime: PentestRuntime, state: str = "networkidle", timeout_ms: int = 5000) -> ToolResponse:
    """Wait for a page load state such as load, domcontentloaded, or networkidle."""
    try:
        return _tool_response(runtime.browser.wait_for_load_state(state=state, timeout_ms=timeout_ms))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False)
def browser_wait_for_selector(
    runtime: PentestRuntime,
    selector: str,
    state: str = "visible",
    timeout_ms: int = 10000,
) -> ToolResponse:
    """Wait for a selector to appear or change state and return a small text preview."""
    try:
        return _tool_response(
            runtime.browser.wait_for_selector(selector=selector, state=state, timeout_ms=timeout_ms),
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp")
def browser_get_html(runtime: PentestRuntime, max_chars: int = 20000) -> ToolResponse:
    """Return current page HTML source preview and total length."""
    try:
        return _tool_response(runtime.browser.get_html(max_chars=max_chars))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False, invalidates_cache=True)
def browser_click(runtime: PentestRuntime, selector: str) -> ToolResponse:
    """Click a DOM element identified by a Playwright selector."""
    try:
        return _tool_response(runtime.browser.click(selector))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False, invalidates_cache=True)
def browser_fill(runtime: PentestRuntime, selector: str, text: str, submit: bool = False) -> ToolResponse:
    """Fill an input or textarea with text and optionally submit it via Enter."""
    try:
        return _tool_response(runtime.browser.fill(selector, text=text, submit=submit))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False, invalidates_cache=True)
def browser_press(runtime: PentestRuntime, selector: str, key: str) -> ToolResponse:
    """Press a keyboard key on an element matched by the selector."""
    try:
        return _tool_response(runtime.browser.press(selector, key=key))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False, invalidates_cache=True)
def browser_evaluate(runtime: PentestRuntime, script: str) -> ToolResponse:
    """Evaluate JavaScript in the page context and return its JSON-serializable result."""
    try:
        return _tool_response(runtime.browser.evaluate(script))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp")
def browser_list_forms(runtime: PentestRuntime, max_forms: int = 40, max_inputs: int = 40) -> ToolResponse:
    """List forms on the current page, including actions, methods, and inputs."""
    try:
        return _tool_response(runtime.browser.list_forms(max_forms=max_forms, max_inputs=max_inputs))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp")
def browser_list_links(runtime: PentestRuntime, limit: int = 120) -> ToolResponse:
    """List visible anchor links on the current page."""
    try:
        return _tool_response(runtime.browser.list_links(limit=limit))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp")
def browser_storage_snapshot(runtime: PentestRuntime) -> ToolResponse:
    """Return current localStorage and sessionStorage snapshots."""
    try:
        return _tool_response(runtime.browser.storage_snapshot())
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp")
def browser_get_cookies(runtime: PentestRuntime) -> ToolResponse:
    """Return current browser cookies for the active context."""
    try:
        return _tool_response(runtime.browser.get_cookies())
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False)
def browser_get_network_log(runtime: PentestRuntime, limit: int = 100) -> ToolResponse:
    """Return recent browser network events captured during this session."""
    try:
        return _tool_response(runtime.browser.get_network_log(limit=limit))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False)
def browser_get_cdp_requests(
    runtime: PentestRuntime,
    limit: int = 120,
    url_contains: str = "",
    body_chars: int = 4000,
) -> ToolResponse:
    """Return detailed CDP request/response records, including method, headers, post data, redirects, and text body previews when available."""
    try:
        return _tool_response(
            runtime.browser.get_cdp_requests(
                limit=limit,
                url_contains=url_contains,
                body_chars=body_chars,
            ),
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False)
def browser_get_response_bodies(runtime: PentestRuntime, limit: int = 40, url_contains: str = "") -> ToolResponse:
    """Return preview bodies for recent document/xhr/fetch/script/stylesheet responses, optionally filtered by URL substring."""
    try:
        return _tool_response(runtime.browser.get_response_bodies(limit=limit, url_contains=url_contains))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False)
def browser_analyze_page_resources(
    runtime: PentestRuntime,
    max_resources: int = 120,
    max_inline_scripts: int = 20,
    max_body_chars: int = 4000,
) -> ToolResponse:
    """Enumerate loaded page files and code by combining DOM assets, performance entries, and CDP request details."""
    try:
        return _tool_response(
            runtime.browser.analyze_page_resources(
                max_resources=max_resources,
                max_inline_scripts=max_inline_scripts,
                max_body_chars=max_body_chars,
            ),
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False)
def browser_get_console_log(runtime: PentestRuntime, limit: int = 50) -> ToolResponse:
    """Return recent browser console events captured during this session."""
    try:
        return _tool_response(runtime.browser.get_console_log(limit=limit))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False)
def browser_screenshot(runtime: PentestRuntime, name: str = "page") -> ToolResponse:
    """Capture a full-page screenshot and return the saved path."""
    try:
        return _tool_response({"path": runtime.browser.screenshot(name=name)})
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp", dedupe=False, invalidates_cache=True)
def cdp_send(runtime: PentestRuntime, method: str, params_json: str = "{}") -> ToolResponse:
    """Send a raw Chrome DevTools Protocol command to the current page session."""
    try:
        params = _parse_json_object(params_json)
        return _tool_response(runtime.browser.cdp_send(method=method, params=params))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-cdp")
def browser_extract_route_hints(
    runtime: PentestRuntime,
    max_html_chars: int = 30000,
    max_response_bodies: int = 60,
    max_candidates: int = 120,
) -> ToolResponse:
    """Extract same-origin route, endpoint, and documentation hints from the current HTML and recent response bodies."""
    try:
        html = runtime.browser.get_html(max_chars=max_html_chars)
        current_url = str(html.get("url") or runtime.scope.start_url)
        html_candidates = extract_in_scope_candidate_urls(
            str(html.get("html_preview") or ""),
            base_url=current_url,
            scope=runtime.scope,
            max_candidates=max_candidates,
        )

        response_sources: list[dict[str, Any]] = []
        response_candidates: set[str] = set()
        for entry in runtime.browser.get_response_bodies(limit=max_response_bodies):
            body_preview = str(entry.get("body_preview") or "")
            if not body_preview:
                continue
            candidates = extract_in_scope_candidate_urls(
                body_preview,
                base_url=str(entry.get("url") or current_url),
                scope=runtime.scope,
                max_candidates=min(40, max_candidates),
            )
            if not candidates:
                continue
            prioritized = prioritize_discovery_urls(candidates, start_url=current_url, max_items=10)
            response_candidates.update(prioritized)
            response_sources.append(
                {
                    "url": entry.get("url"),
                    "status": entry.get("status"),
                    "content_type": entry.get("content_type"),
                    "candidate_urls": prioritized,
                },
            )

        combined_candidates = prioritize_discovery_urls(
            {*(html_candidates or []), *response_candidates},
            start_url=current_url,
            max_items=max_candidates,
        )
        api_hints = [item for item in combined_candidates if is_api_like_url(item)][:25]

        return _tool_response(
            {
                "current_url": current_url,
                "html_candidate_urls": prioritize_discovery_urls(
                    html_candidates,
                    start_url=current_url,
                    max_items=25,
                ),
                "response_candidate_urls": prioritize_discovery_urls(
                    response_candidates,
                    start_url=current_url,
                    max_items=25,
                ),
                "combined_candidate_urls": combined_candidates,
                "api_hints": api_hints,
                "response_sources": response_sources[:12],
            },
        )
    except Exception as exc:
        return _error_response(exc)
