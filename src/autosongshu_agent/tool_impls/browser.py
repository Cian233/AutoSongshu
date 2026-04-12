from __future__ import annotations

from typing import Any

from agentscope.tool import ToolResponse

from ..discovery import extract_in_scope_candidate_urls, is_api_like_url, prioritize_discovery_urls
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _error_response, _parse_json_object, _tool_response

# ── Tool Groups ───────────────────────────────────────────────────
# Split into 5 sub-groups following OpenClaw's tool profile pattern.
# Only browser-basic is active by default; the agent activates others
# on demand via reset_equipped_tools (enable_meta_tool=True).

registry.create_group(
    "browser-basic",
    description="Core browser operations: navigate, snapshot, screenshot, HTML source, and status check.",
    active=True,
    notes="Always available. Use browser_navigate → browser_snapshot as the standard page inspection flow.",
)

registry.create_group(
    "browser-interact",
    description="DOM interaction tools: click, fill, press, hover, select, upload, navigate history.",
    active=True,
    notes="Use for interacting with page elements (forms, buttons, dropdowns, file inputs).",
)

registry.create_group(
    "browser-inspect",
    description="Page inspection tools: element details, forms, links, storage, cookies, scroll, wait.",
    active=False,
    notes="Activate when you need to inspect specific page elements, cookies, storage, or wait for conditions.",
)

registry.create_group(
    "browser-network",
    description="Network and CDP inspection: request logs, response bodies, console, resource analysis, route hints.",
    active=False,
    notes="Activate when you need to analyze network traffic, API calls, console output, or discover endpoints.",
)

registry.create_group(
    "browser-advanced",
    description="Advanced tools: JavaScript evaluation, raw CDP commands.",
    active=False,
    notes="Activate only when standard tools are insufficient and you need direct JS execution or CDP access.",
)

# ── browser-basic (always active, 8 tools) ────────────────────────

@registry.register("browser-basic")
def browser_status(runtime: PentestRuntime) -> ToolResponse:
    """Return browser availability, current mode, active URL, and whether CDP is attached."""
    try:
        return _tool_response(runtime.browser.status())
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-basic", invalidates_cache=True, max_retries=2)
def browser_navigate(runtime: PentestRuntime, url: str) -> ToolResponse:
    """Navigate the active browser page to an in-scope URL. Returns a page summary including title, meta description, text preview, and element counts."""
    try:
        return _tool_response(runtime.browser.navigate(url))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-basic")
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

@registry.register("browser-basic")
def browser_get_html(runtime: PentestRuntime, max_chars: int = 20000) -> ToolResponse:
    """Return current page HTML source preview and total length."""
    try:
        return _tool_response(runtime.browser.get_html(max_chars=max_chars))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-basic")
def browser_screenshot(runtime: PentestRuntime, name: str = "page") -> ToolResponse:
    """Capture a full-page screenshot and return the saved path."""
    try:
        return _tool_response({"path": runtime.browser.screenshot(name=name)})
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-basic", dedupe=False)
def browser_wait_for_load_state(runtime: PentestRuntime, state: str = "networkidle", timeout_ms: int = 5000) -> ToolResponse:
    """Wait for a page load state such as load, domcontentloaded, or networkidle."""
    try:
        return _tool_response(runtime.browser.wait_for_load_state(state=state, timeout_ms=timeout_ms))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-basic", dedupe=False)
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

@registry.register("browser-basic")
def browser_list_forms(runtime: PentestRuntime, max_forms: int = 40, max_inputs: int = 40) -> ToolResponse:
    """List forms on the current page, including actions, methods, and inputs."""
    try:
        return _tool_response(runtime.browser.list_forms(max_forms=max_forms, max_inputs=max_inputs))
    except Exception as exc:
        return _error_response(exc)

# ── browser-interact (on-demand, 9 tools) ─────────────────────────

@registry.register("browser-interact", dedupe=False, invalidates_cache=True)
def browser_click(runtime: PentestRuntime, selector: str) -> ToolResponse:
    """Click a DOM element identified by a Playwright selector."""
    try:
        return _tool_response(runtime.browser.click(selector))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-interact", dedupe=False, invalidates_cache=True)
def browser_fill(runtime: PentestRuntime, selector: str, text: str, submit: bool = False) -> ToolResponse:
    """Fill an input or textarea with text and optionally submit it via Enter."""
    try:
        return _tool_response(runtime.browser.fill(selector, text=text, submit=submit))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-interact", dedupe=False, invalidates_cache=True)
def browser_press(runtime: PentestRuntime, selector: str, key: str) -> ToolResponse:
    """Press a keyboard key on an element matched by the selector."""
    try:
        return _tool_response(runtime.browser.press(selector, key=key))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-interact", dedupe=False, invalidates_cache=True)
def browser_hover(runtime: PentestRuntime, selector: str) -> ToolResponse:
    """Hover the mouse over a DOM element (useful for triggering dropdowns, tooltips, or hover-revealed content)."""
    try:
        return _tool_response(runtime.browser.hover(selector))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-interact", dedupe=False, invalidates_cache=True)
def browser_select_option(runtime: PentestRuntime, selector: str, value: str = "", label: str = "") -> ToolResponse:
    """Select an option in a <select> dropdown by value or visible label."""
    try:
        return _tool_response(
            runtime.browser.select_option(
                selector,
                value=value or None,
                label=label or None,
            )
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-interact", dedupe=False, invalidates_cache=True)
def browser_go_back(runtime: PentestRuntime) -> ToolResponse:
    """Navigate the browser back to the previous page in history."""
    try:
        return _tool_response(runtime.browser.go_back())
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-interact", dedupe=False, invalidates_cache=True)
def browser_go_forward(runtime: PentestRuntime) -> ToolResponse:
    """Navigate the browser forward to the next page in history."""
    try:
        return _tool_response(runtime.browser.go_forward())
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-interact", dedupe=False, invalidates_cache=True)
def browser_upload_file(runtime: PentestRuntime, selector: str, file_paths_json: str) -> ToolResponse:
    """Upload files to a file input element. Pass a JSON array of file paths. Example: '["/path/to/shell.php"]'."""
    try:
        file_paths = _parse_json_object(file_paths_json)
        if not isinstance(file_paths, list):
            file_paths = [file_paths]
        return _tool_response(runtime.browser.upload_file(selector, file_paths))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-interact", dedupe=False)
def browser_wait_for_url(runtime: PentestRuntime, pattern: str, timeout_ms: int = 10000) -> ToolResponse:
    """Wait for the page URL to match a glob pattern (e.g. '**/login', '**/dashboard*'). Useful after clicking a link that triggers a redirect."""
    try:
        return _tool_response(runtime.browser.wait_for_url(pattern, timeout_ms=timeout_ms))
    except Exception as exc:
        return _error_response(exc)

# ── browser-inspect (on-demand, 8 tools) ──────────────────────────

@registry.register("browser-inspect")
def browser_get_element(runtime: PentestRuntime, selector: str) -> ToolResponse:
    """Get details of a single DOM element: tag name, text content, attributes, and visibility."""
    try:
        return _tool_response(runtime.browser.get_element(selector))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-inspect")
def browser_list_links(runtime: PentestRuntime, limit: int = 120) -> ToolResponse:
    """List visible anchor links on the current page."""
    try:
        return _tool_response(runtime.browser.list_links(limit=limit))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-inspect")
def browser_storage_snapshot(runtime: PentestRuntime) -> ToolResponse:
    """Return current localStorage and sessionStorage snapshots."""
    try:
        return _tool_response(runtime.browser.storage_snapshot())
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-inspect")
def browser_get_cookies(runtime: PentestRuntime) -> ToolResponse:
    """Return current browser cookies for the active context."""
    try:
        return _tool_response(runtime.browser.get_cookies())
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-inspect", dedupe=False, invalidates_cache=True)
def browser_set_cookies(runtime: PentestRuntime, cookies_json: str) -> ToolResponse:
    """Set browser cookies. Pass a JSON array of cookie objects, each with 'name', 'value', and optionally 'domain', 'path', 'httpOnly', 'secure', 'sameSite'. Example: '[{"name":"session","value":"abc","domain":".example.com"}]'."""
    try:
        cookies = _parse_json_object(cookies_json)
        if not isinstance(cookies, list):
            cookies = [cookies]
        return _tool_response(runtime.browser.add_cookies(cookies))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-inspect", dedupe=False, invalidates_cache=True)
def browser_clear_cookies(runtime: PentestRuntime) -> ToolResponse:
    """Clear all browser cookies for the active context."""
    try:
        return _tool_response(runtime.browser.clear_cookies())
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-inspect", dedupe=False)
def browser_scroll_to(runtime: PentestRuntime, x: int = 0, y: int = 0, selector: str = "") -> ToolResponse:
    """Scroll the page to absolute coordinates (x, y), or scroll an element into view by providing a CSS selector."""
    try:
        return _tool_response(
            runtime.browser.scroll_to(x=x, y=y, selector=selector or None)
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-inspect")
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

# ── browser-network (on-demand, 5 tools) ──────────────────────────

@registry.register("browser-network", dedupe=False)
def browser_get_network_log(runtime: PentestRuntime, limit: int = 100) -> ToolResponse:
    """Return recent browser network events captured during this session."""
    try:
        return _tool_response(runtime.browser.get_network_log(limit=limit))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-network", dedupe=False)
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

@registry.register("browser-network", dedupe=False)
def browser_get_response_bodies(runtime: PentestRuntime, limit: int = 40, url_contains: str = "") -> ToolResponse:
    """Return preview bodies for recent document/xhr/fetch/script/stylesheet responses, optionally filtered by URL substring."""
    try:
        return _tool_response(runtime.browser.get_response_bodies(limit=limit, url_contains=url_contains))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-network", dedupe=False)
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

@registry.register("browser-network", dedupe=False)
def browser_get_console_log(runtime: PentestRuntime, limit: int = 50) -> ToolResponse:
    """Return recent browser console events captured during this session."""
    try:
        return _tool_response(runtime.browser.get_console_log(limit=limit))
    except Exception as exc:
        return _error_response(exc)

# ── browser-advanced (on-demand, 6 tools) ─────────────────────────

@registry.register("browser-advanced", dedupe=False, invalidates_cache=True)
def browser_evaluate(runtime: PentestRuntime, script: str) -> ToolResponse:
    """Evaluate JavaScript in the page context and return its JSON-serializable result."""
    try:
        return _tool_response(runtime.browser.evaluate(script))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-advanced", dedupe=False, invalidates_cache=True)
def browser_inject_script(runtime: PentestRuntime, script: str, world_name: str = "") -> ToolResponse:
    """Inject a script that runs before any page script on EVERY subsequent navigation. Uses CDP Page.addScriptToEvaluateOnNewDocument. Returns a script_id for later removal. Set world_name='UTILITY' to run in the browser's utility context (isolated from page JS)."""
    try:
        return _tool_response(runtime.browser.inject_script(script, world_name=world_name))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-advanced", dedupe=False, invalidates_cache=True)
def browser_add_init_script(runtime: PentestRuntime, script: str) -> ToolResponse:
    """Add a Playwright-level init script that runs before any page script on every navigation. Unlike browser_inject_script, this works even before CDP is attached."""
    try:
        return _tool_response(runtime.browser.add_init_script(script))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-advanced", dedupe=False)
def browser_remove_script(runtime: PentestRuntime, script_id: str) -> ToolResponse:
    """Remove a previously injected script by its script_id (returned by browser_inject_script)."""
    try:
        return _tool_response(runtime.browser.remove_script(script_id))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-advanced", dedupe=False)
def browser_list_injected_scripts(runtime: PentestRuntime) -> ToolResponse:
    """List all scripts that have been injected via browser_inject_script. Returns their IDs and source previews."""
    try:
        return _tool_response(runtime.browser.list_injected_scripts())
    except Exception as exc:
        return _error_response(exc)

# ── Injection templates (convenience wrappers) ─────────────────────

_INJECT_HOOK_NETWORK = """\
// Hook fetch and XMLHttpRequest to capture all network requests
(function() {
  const origFetch = window.fetch;
  window.__captured_requests = [];
  window.fetch = async function(...args) {
    const [input, init] = args;
    const entry = { url: typeof input === 'string' ? input : input.url, method: (init && init.method) || 'GET', headers: {}, body: null };
    if (init && init.headers) entry.headers = Object.fromEntries(new Headers(init.headers));
    if (init && init.body) entry.body = String(init.body).substring(0, 2000);
    window.__captured_requests.push(entry);
    return origFetch.apply(this, args);
  };
  const origOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url) {
    this.__reqInfo = { method, url, headers: {} };
    return origOpen.apply(this, arguments);
  };
  const origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function(body) {
    if (this.__reqInfo) {
      this.__reqInfo.body = body ? String(body).substring(0, 2000) : null;
      window.__captured_requests.push(this.__reqInfo);
    }
    return origSend.apply(this, arguments);
  };
  const origSetHeader = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
    if (this.__reqInfo) this.__reqInfo.headers[name] = value;
    return origSetHeader.apply(this, arguments);
  };
})();
"""

_INJECT_HOOK_CONSOLE = """\
// Capture all console output (log, warn, error, info)
(function() {
  window.__captured_console = [];
  ['log','warn','error','info','debug'].forEach(level => {
    const orig = console[level];
    console[level] = function(...args) {
      window.__captured_console.push({ level, args: args.map(a => { try { return typeof a === 'object' ? JSON.stringify(a).substring(0,500) : String(a).substring(0,500); } catch(e) { return String(a).substring(0,500); } }), time: Date.now() });
      orig.apply(console, args);
    };
  });
})();
"""

_INJECT_HOOK_COOKIE = """\
// Hook document.cookie to monitor all cookie reads and writes
(function() {
  window.__captured_cookies = [];
  const origGetter = Object.getOwnPropertyDescriptor(Document.prototype, 'cookie') || Object.getOwnPropertyDescriptor(HTMLDocument.prototype, 'cookie');
  const origSet = origGetter ? origGetter.set : undefined;
  Object.defineProperty(document, 'cookie', {
    get() { const v = origGetter.get.call(this); return v; },
    set(v) { window.__captured_cookies.push({ action: 'set', value: v, time: Date.now() }); if (origSet) origSet.call(this, v); return v; },
    configurable: true
  });
  // Also capture existing cookies on load
  window.__captured_cookies.push({ action: 'snapshot', value: document.cookie, time: Date.now() });
})();
"""

_INJECT_HOOK_DOM_MUTATIONS = """\
// Monitor DOM mutations (added/removed elements, attribute changes)
(function() {
  window.__captured_mutations = [];
  const observer = new MutationObserver(mutations => {
    for (const m of mutations) {
      if (m.type === 'childList') {
        m.addedNodes.forEach(n => { if (n.nodeType === 1) window.__captured_mutations.push({ type: 'added', tag: n.tagName, id: n.id || '', class: n.className || '', time: Date.now() }); });
        m.removedNodes.forEach(n => { if (n.nodeType === 1) window.__captured_mutations.push({ type: 'removed', tag: n.tagName, id: n.id || '', class: n.className || '', time: Date.now() }); });
      } else if (m.type === 'attributes') {
        window.__captured_mutations.push({ type: 'attr', target: m.target.tagName, attr: m.attributeName, time: Date.now() });
      }
    }
    if (window.__captured_mutations.length > 500) window.__captured_mutations = window.__captured_mutations.slice(-500);
  });
  observer.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['class','style','hidden','disabled','src','href','action','value'] });
})();
"""

_INJECT_HOOK_STORAGE = """\
// Hook localStorage and sessionStorage to capture all reads/writes
(function() {
  window.__captured_storage = [];
  ['localStorage','sessionStorage'].forEach(storeName => {
    const store = window[storeName];
    const origSetItem = store.setItem.bind(store);
    const origRemoveItem = store.removeItem.bind(store);
    const origClear = store.clear.bind(store);
    store.setItem = function(k, v) { window.__captured_storage.push({ store: storeName, action: 'set', key: k, value: v.substring(0, 500), time: Date.now() }); origSetItem(k, v); };
    store.removeItem = function(k) { window.__captured_storage.push({ store: storeName, action: 'remove', key: k, time: Date.now() }); origRemoveItem(k); };
    store.clear = function() { window.__captured_storage.push({ store: storeName, action: 'clear', time: Date.now() }); origClear(); };
  });
})();
"""

@registry.register("browser-advanced", dedupe=False, invalidates_cache=True)
def browser_inject_hook(runtime: PentestRuntime, hook: str) -> ToolResponse:
    """Inject a pre-built hook script that persists across navigations. Available hooks: 'network' (capture fetch/XHR), 'console' (capture console output), 'cookie' (monitor cookie changes), 'dom' (monitor DOM mutations), 'storage' (monitor localStorage/sessionStorage). After injection, use browser_evaluate to read the captured data (e.g. window.__captured_requests)."""
    templates = {
        "network": _INJECT_HOOK_NETWORK,
        "console": _INJECT_HOOK_CONSOLE,
        "cookie": _INJECT_HOOK_COOKIE,
        "dom": _INJECT_HOOK_DOM_MUTATIONS,
        "storage": _INJECT_HOOK_STORAGE,
    }
    script = templates.get(hook)
    if not script:
        available = ", ".join(sorted(templates.keys()))
        return _error_response(ValueError(f"Unknown hook '{hook}'. Available hooks: {available}"))
    try:
        return _tool_response(runtime.browser.inject_script(script))
    except Exception as exc:
        return _error_response(exc)

@registry.register("browser-advanced", dedupe=False, invalidates_cache=True)
def cdp_send(runtime: PentestRuntime, method: str, params_json: str = "{}") -> ToolResponse:
    """Send a raw Chrome DevTools Protocol command to the current page session."""
    try:
        params = _parse_json_object(params_json)
        return _tool_response(runtime.browser.cdp_send(method=method, params=params))
    except Exception as exc:
        return _error_response(exc)
