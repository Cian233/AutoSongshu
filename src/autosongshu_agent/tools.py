from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from functools import wraps
from collections.abc import Callable
from typing import Any

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse, Toolkit

from .discovery import extract_in_scope_candidate_urls, is_api_like_url, prioritize_discovery_urls
from .models import Finding
from .runtime import PentestRuntime

_ToolPolicyValue = bool | Callable[[dict[str, Any]], bool]


@dataclass(frozen=True)
class _ToolExecutionPolicy:
    dedupe: _ToolPolicyValue = True
    invalidates_cache: _ToolPolicyValue = False


def _tool_response(payload: Any) -> ToolResponse:
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            ),
        ],
    )


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


def _policy_enabled(policy: _ToolPolicyValue, arguments: dict[str, Any]) -> bool:
    return bool(policy(arguments) if callable(policy) else policy)


def _tool_call_cache_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(f"{tool_name}:{payload}".encode("utf-8")).hexdigest()


def _wrap_registered_tool(
    tool_func: Callable[..., ToolResponse],
    runtime: PentestRuntime,
    *,
    policy: _ToolExecutionPolicy | None = None,
) -> Callable[..., ToolResponse]:
    signature = inspect.signature(tool_func)
    execution_policy = policy or _ToolExecutionPolicy()

    @wraps(tool_func)
    def wrapped(*args: Any, **kwargs: Any) -> ToolResponse:
        cache = getattr(runtime, "tool_call_cache", None)
        if cache is None:
            return tool_func(*args, **kwargs)

        bound_arguments = signature.bind_partial(*args, **kwargs)
        bound_arguments.apply_defaults()
        call_arguments = dict(bound_arguments.arguments)
        dedupe_enabled = _policy_enabled(execution_policy.dedupe, call_arguments)
        invalidates_cache = _policy_enabled(execution_policy.invalidates_cache, call_arguments)

        if not dedupe_enabled:
            response = tool_func(*args, **kwargs)
            if invalidates_cache:
                cache.invalidate()
            return response

        call_signature = _tool_call_cache_signature(tool_func.__name__, call_arguments)
        mode, payload = cache.begin_call(call_signature)
        if mode == "cached":
            return payload
        if mode == "wait":
            return cache.wait_for_call(payload)

        try:
            response = tool_func(*args, **kwargs)
        except Exception as exc:
            cache.fail_call(call_signature, exc)
            raise

        cache.complete_call(call_signature, response, invalidates_cache=invalidates_cache)
        return response

    wrapped.__signature__ = signature
    return wrapped


def _register_tool_function(
    toolkit: Toolkit,
    runtime: PentestRuntime,
    tool_func: Callable[..., ToolResponse],
    *,
    group_name: str,
    policy: _ToolExecutionPolicy | None = None,
) -> None:
    toolkit.register_tool_function(
        _wrap_registered_tool(tool_func, runtime, policy=policy),
        group_name=group_name,
    )


def _http_request_allows_dedupe(arguments: dict[str, Any]) -> bool:
    return str(arguments.get("method") or "GET").strip().upper() in {"GET", "HEAD", "OPTIONS"}


def _http_request_invalidates_cache(arguments: dict[str, Any]) -> bool:
    return not _http_request_allows_dedupe(arguments)


def register_default_tools(toolkit: Toolkit, runtime: PentestRuntime) -> None:
    toolkit.create_tool_group(
        "browser-cdp",
        description="Browser automation, DOM inspection, and raw CDP access for in-scope targets.",
        active=True,
        notes="Prefer these tools for authenticated flows, DOM state, cookies, console logs, and JS-heavy pages.",
    )
    toolkit.create_tool_group(
        "http-analysis",
        description="Direct HTTP requests and low-risk web security analysis.",
        active=True,
    )
    toolkit.create_tool_group(
        "skill-scripts",
        description="List and run bundled scripts that live under available local skills.",
        active=True,
        notes="Use these tools instead of re-implementing deterministic skill helper logic from scratch.",
    )
    toolkit.create_tool_group(
        "findings",
        description="Persist and review findings collected during the assessment.",
        active=True,
    )
    toolkit.create_tool_group(
        "knowledge-rag",
        description="Search reusable internal knowledge and past experience snippets.",
        active=True,
        notes="Use this only when retrieval is truly helpful. Compose a concise query based on the current task.",
    )
    toolkit.create_tool_group(
        "python-sandbox",
        description="Shared per-user Python sandbox for custom test scripts, package installs, and helper automation.",
        active=runtime.config.sandbox.enabled,
        notes="Prefer this for bulk payload fuzzing, retry loops, custom sessions/cookies/headers, encoding tricks, certificate quirks, and any validation the built-in browser/CDP/HTTP tools cannot finish directly.",
    )

    def browser_navigate(url: str) -> ToolResponse:
        """Navigate the active browser page to an in-scope URL."""
        try:
            return _tool_response(runtime.browser.navigate(url))
        except Exception as exc:
            return _error_response(exc)

    def browser_status() -> ToolResponse:
        """Return browser availability, current mode, active URL, and whether CDP is attached."""
        try:
            return _tool_response(runtime.browser.status())
        except Exception as exc:
            return _error_response(exc)

    def browser_snapshot(
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

    def browser_wait_for_load_state(state: str = "networkidle", timeout_ms: int = 5000) -> ToolResponse:
        """Wait for a page load state such as load, domcontentloaded, or networkidle."""
        try:
            return _tool_response(runtime.browser.wait_for_load_state(state=state, timeout_ms=timeout_ms))
        except Exception as exc:
            return _error_response(exc)

    def browser_wait_for_selector(
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

    def browser_get_html(max_chars: int = 20000) -> ToolResponse:
        """Return current page HTML source preview and total length."""
        try:
            return _tool_response(runtime.browser.get_html(max_chars=max_chars))
        except Exception as exc:
            return _error_response(exc)

    def browser_click(selector: str) -> ToolResponse:
        """Click a DOM element identified by a Playwright selector."""
        try:
            return _tool_response(runtime.browser.click(selector))
        except Exception as exc:
            return _error_response(exc)

    def browser_fill(selector: str, text: str, submit: bool = False) -> ToolResponse:
        """Fill an input or textarea with text and optionally submit it via Enter."""
        try:
            return _tool_response(runtime.browser.fill(selector, text=text, submit=submit))
        except Exception as exc:
            return _error_response(exc)

    def browser_press(selector: str, key: str) -> ToolResponse:
        """Press a keyboard key on an element matched by the selector."""
        try:
            return _tool_response(runtime.browser.press(selector, key=key))
        except Exception as exc:
            return _error_response(exc)

    def browser_evaluate(script: str) -> ToolResponse:
        """Evaluate JavaScript in the page context and return its JSON-serializable result."""
        try:
            return _tool_response(runtime.browser.evaluate(script))
        except Exception as exc:
            return _error_response(exc)

    def browser_list_forms(max_forms: int = 40, max_inputs: int = 40) -> ToolResponse:
        """List forms on the current page, including actions, methods, and inputs."""
        try:
            return _tool_response(runtime.browser.list_forms(max_forms=max_forms, max_inputs=max_inputs))
        except Exception as exc:
            return _error_response(exc)

    def browser_list_links(limit: int = 120) -> ToolResponse:
        """List visible anchor links on the current page."""
        try:
            return _tool_response(runtime.browser.list_links(limit=limit))
        except Exception as exc:
            return _error_response(exc)

    def browser_storage_snapshot() -> ToolResponse:
        """Return current localStorage and sessionStorage snapshots."""
        try:
            return _tool_response(runtime.browser.storage_snapshot())
        except Exception as exc:
            return _error_response(exc)

    def browser_get_cookies() -> ToolResponse:
        """Return current browser cookies for the active context."""
        try:
            return _tool_response(runtime.browser.get_cookies())
        except Exception as exc:
            return _error_response(exc)

    def browser_get_network_log(limit: int = 100) -> ToolResponse:
        """Return recent browser network events captured during this session."""
        try:
            return _tool_response(runtime.browser.get_network_log(limit=limit))
        except Exception as exc:
            return _error_response(exc)

    def browser_get_cdp_requests(
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

    def browser_get_response_bodies(limit: int = 40, url_contains: str = "") -> ToolResponse:
        """Return preview bodies for recent document/xhr/fetch/script/stylesheet responses, optionally filtered by URL substring."""
        try:
            return _tool_response(runtime.browser.get_response_bodies(limit=limit, url_contains=url_contains))
        except Exception as exc:
            return _error_response(exc)

    def browser_analyze_page_resources(
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

    def browser_get_console_log(limit: int = 50) -> ToolResponse:
        """Return recent browser console events captured during this session."""
        try:
            return _tool_response(runtime.browser.get_console_log(limit=limit))
        except Exception as exc:
            return _error_response(exc)

    def browser_screenshot(name: str = "page") -> ToolResponse:
        """Capture a full-page screenshot and return the saved path."""
        try:
            return _tool_response({"path": runtime.browser.screenshot(name=name)})
        except Exception as exc:
            return _error_response(exc)

    def cdp_send(method: str, params_json: str = "{}") -> ToolResponse:
        """Send a raw Chrome DevTools Protocol command to the current page session."""
        try:
            params = _parse_json_object(params_json)
            return _tool_response(runtime.browser.cdp_send(method=method, params=params))
        except Exception as exc:
            return _error_response(exc)

    def http_request(
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

    def analyze_security_headers(url: str) -> ToolResponse:
        """Inspect common response security headers and obvious cookie-flag gaps."""
        try:
            return _tool_response(runtime.http.analyze_security_headers(url))
        except Exception as exc:
            return _error_response(exc)

    def http_discover_surface(
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

    def probe_reflection(
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

    def analyze_csrf_surface() -> ToolResponse:
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

    def browser_extract_route_hints(
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

    def list_skill_scripts(skill_name: str = "") -> ToolResponse:
        """List bundled scripts under available skills, including on-demand manual skills, or only for a specific skill when skill_name is provided."""
        try:
            return _tool_response(runtime.skill_scripts.list_scripts(skill_name=skill_name))
        except Exception as exc:
            return _error_response(exc)

    def run_skill_script(
        skill_name: str,
        script_name: str,
        args_json: str = "[]",
        timeout_sec: int = 300,
        max_output_chars: int = 20000,
    ) -> ToolResponse:
        """Run a bundled script from an available skill. script_name accepts either a filename or a relative path under scripts/."""
        try:
            return _tool_response(
                runtime.skill_scripts.run(
                    skill_name=skill_name,
                    script_name=script_name,
                    args=_parse_json_list(args_json),
                    timeout_sec=timeout_sec,
                    max_output_chars=max_output_chars,
                ),
            )
        except Exception as exc:
            return _error_response(exc)

    def knowledge_search(
        query: str,
        knowledge_base_ids_json: str = "[]",
        limit: int = 6,
    ) -> ToolResponse:
        """Search knowledge-base chunks when prior experience may help. query should be concise and retrieval-oriented."""
        try:
            requested_ids = _parse_json_list(knowledge_base_ids_json)
            result = runtime.search_knowledge(
                query=query,
                knowledge_base_ids=requested_ids,
                limit=limit,
            )
            hits = result.get("hits") if isinstance(result, dict) else []
            return _tool_response(
                {
                    "query": str(query or "").strip(),
                    "requested_knowledge_base_ids": requested_ids,
                    **(result if isinstance(result, dict) else {"hits": []}),
                    "hit_count": len(hits) if isinstance(hits, list) else 0,
                },
            )
        except Exception as exc:
            return _error_response(exc)

    def sandbox_status() -> ToolResponse:
        """Call this first before using the sandbox. It returns paths, scope metadata, HTTPS/certificate hints, and package mirror settings."""
        try:
            return _tool_response(runtime.sandbox.status(include_packages=False))
        except Exception as exc:
            return _error_response(exc)

    def sandbox_list_files(pattern: str = "**/*", limit: int = 200) -> ToolResponse:
        """List files in the shared per-user sandbox workspace."""
        try:
            return _tool_response(runtime.sandbox.list_files(pattern=pattern, limit=limit))
        except Exception as exc:
            return _error_response(exc)

    def sandbox_write_file(path: str, content: str) -> ToolResponse:
        """Create or intentionally overwrite a UTF-8 text file inside the sandbox workspace. content must be raw file text only: no markdown fences, no narrative explanations, and no thought-process notes. Prefer edit_file or multiedit_file for iterative changes."""
        try:
            return _tool_response(runtime.sandbox.write_file(path=path, content=content))
        except Exception as exc:
            return _error_response(exc)

    def sandbox_edit_file(
        path: str,
        old_text: str = "",
        new_text: str = "",
        replace_all: bool = False,
        start_line: int = 0,
        end_line: int = 0,
        expected_old_text: str = "",
        max_diff_chars: int = 12000,
    ) -> ToolResponse:
        """Apply one precise edit to an existing UTF-8 text file. new_text must be raw replacement text only, without markdown fences or explanatory prose. Use exact old_text/new_text replacement or a start_line/end_line replacement with optional expected_old_text verification. This refuses whole-file replacement; use write_file only for intentional full overwrites."""
        try:
            return _tool_response(
                runtime.sandbox.edit_file(
                    path=path,
                    old_text=old_text,
                    new_text=new_text,
                    replace_all=replace_all,
                    start_line=start_line,
                    end_line=end_line,
                    expected_old_text=expected_old_text,
                    max_diff_chars=max_diff_chars,
                )
            )
        except Exception as exc:
            return _error_response(exc)

    def sandbox_multiedit_file(
        path: str,
        edits_json: str,
        max_diff_chars: int = 12000,
    ) -> ToolResponse:
        """Apply several precise edits to the same file in order. edits_json must be a JSON list of edit objects, each using old_text/new_text or start_line/end_line/new_text. Every new_text value must be raw replacement text only, without markdown fences or explanatory prose."""
        try:
            return _tool_response(
                runtime.sandbox.multiedit_file(
                    path=path,
                    edits=_parse_json_object_list(edits_json),
                    max_diff_chars=max_diff_chars,
                )
            )
        except Exception as exc:
            return _error_response(exc)

    def sandbox_read_file(
        path: str,
        max_chars: int = 12000,
        start_line: int = 0,
        end_line: int = 0,
        include_line_numbers: bool = False,
    ) -> ToolResponse:
        """Read a UTF-8 text file from the sandbox workspace. Use include_line_numbers=true and an optional line range before line-based edits."""
        try:
            return _tool_response(
                runtime.sandbox.read_file(
                    path=path,
                    max_chars=max_chars,
                    start_line=start_line,
                    end_line=end_line,
                    include_line_numbers=include_line_numbers,
                )
            )
        except Exception as exc:
            return _error_response(exc)

    def sandbox_install_packages(
        packages: str,
        upgrade: bool = False,
        timeout_sec: int = 300,
        max_output_chars: int = 20000,
    ) -> ToolResponse:
        """Install newline-separated, comma-separated, space-separated, or JSON-list Python packages into the sandbox venv."""
        try:
            return _tool_response(
                runtime.sandbox.install_packages(
                    packages=_parse_package_specs(packages),
                    upgrade=upgrade,
                    timeout_sec=timeout_sec,
                    max_output_chars=max_output_chars,
                ),
            )
        except Exception as exc:
            return _error_response(exc)

    def sandbox_run_python(
        code: str = "",
        script_path: str = "",
        args_json: str = "[]",
        env_json: str = "{}",
        timeout_sec: int = 120,
        max_output_chars: int = 20000,
    ) -> ToolResponse:
        """Run inline Python code or an existing sandbox script. If code is provided, it must be raw Python only, without markdown fences or narrative preambles. Prefer script_path for iterative payload work so the file can be updated with sandbox_edit_file or sandbox_multiedit_file between runs. Avoid rerunning identical code unless inputs or logic changed."""
        try:
            return _tool_response(
                runtime.sandbox.run_python(
                    code=code,
                    script_path=script_path,
                    args=_parse_json_list(args_json),
                    env={key: str(value) for key, value in _parse_json_object(env_json).items()},
                    timeout_sec=timeout_sec,
                    max_output_chars=max_output_chars,
                ),
            )
        except Exception as exc:
            return _error_response(exc)

    def record_finding(
        title: str,
        severity: str,
        summary: str,
        url: str = "",
        evidence: str = "",
        recommendation: str = "",
        cwe: str = "",
        tags: str = "",
        status: str = "validated",
    ) -> ToolResponse:
        """Persist a finding. Use newline-separated or JSON-list strings for evidence and tags."""
        try:
            finding = Finding(
                title=title,
                severity=severity,  # type: ignore[arg-type]
                summary=summary,
                url=url or None,
                evidence=_parse_list_like(evidence),
                recommendation=recommendation or None,
                cwe=cwe or None,
                tags=_parse_list_like(tags),
                status=status,  # type: ignore[arg-type]
            )
            saved = runtime.findings.add(finding)
            return _tool_response(saved.model_dump())
        except Exception as exc:
            return _error_response(exc)

    def list_findings() -> ToolResponse:
        """Return all persisted findings."""
        try:
            return _tool_response([item.model_dump() for item in runtime.findings.list()])
        except Exception as exc:
            return _error_response(exc)

    for function, policy in (
        (browser_status, _ToolExecutionPolicy()),
        (browser_navigate, _ToolExecutionPolicy(invalidates_cache=True)),
        (browser_snapshot, _ToolExecutionPolicy()),
        (browser_wait_for_load_state, _ToolExecutionPolicy(dedupe=False)),
        (browser_wait_for_selector, _ToolExecutionPolicy(dedupe=False)),
        (browser_get_html, _ToolExecutionPolicy()),
        (browser_click, _ToolExecutionPolicy(dedupe=False, invalidates_cache=True)),
        (browser_fill, _ToolExecutionPolicy(dedupe=False, invalidates_cache=True)),
        (browser_press, _ToolExecutionPolicy(dedupe=False, invalidates_cache=True)),
        (browser_evaluate, _ToolExecutionPolicy(dedupe=False, invalidates_cache=True)),
        (browser_list_forms, _ToolExecutionPolicy()),
        (browser_list_links, _ToolExecutionPolicy()),
        (browser_storage_snapshot, _ToolExecutionPolicy()),
        (browser_get_cookies, _ToolExecutionPolicy()),
        (browser_get_network_log, _ToolExecutionPolicy(dedupe=False)),
        (browser_get_cdp_requests, _ToolExecutionPolicy(dedupe=False)),
        (browser_get_response_bodies, _ToolExecutionPolicy(dedupe=False)),
        (browser_analyze_page_resources, _ToolExecutionPolicy(dedupe=False)),
        (browser_get_console_log, _ToolExecutionPolicy(dedupe=False)),
        (browser_screenshot, _ToolExecutionPolicy(dedupe=False)),
        (cdp_send, _ToolExecutionPolicy(dedupe=False, invalidates_cache=True)),
    ):
        _register_tool_function(toolkit, runtime, function, group_name="browser-cdp", policy=policy)

    for function, policy in (
        (
            http_request,
            _ToolExecutionPolicy(
                dedupe=_http_request_allows_dedupe,
                invalidates_cache=_http_request_invalidates_cache,
            ),
        ),
        (analyze_security_headers, _ToolExecutionPolicy()),
        (http_discover_surface, _ToolExecutionPolicy()),
        (probe_reflection, _ToolExecutionPolicy()),
        (analyze_csrf_surface, _ToolExecutionPolicy()),
    ):
        _register_tool_function(toolkit, runtime, function, group_name="http-analysis", policy=policy)

    _register_tool_function(toolkit, runtime, browser_extract_route_hints, group_name="browser-cdp")

    for function, policy in (
        (list_skill_scripts, _ToolExecutionPolicy()),
        (run_skill_script, _ToolExecutionPolicy(dedupe=False, invalidates_cache=True)),
    ):
        _register_tool_function(toolkit, runtime, function, group_name="skill-scripts", policy=policy)

    for function, policy in (
        (record_finding, _ToolExecutionPolicy(dedupe=False, invalidates_cache=True)),
        (list_findings, _ToolExecutionPolicy()),
    ):
        _register_tool_function(toolkit, runtime, function, group_name="findings", policy=policy)

    for function, policy in (
        (knowledge_search, _ToolExecutionPolicy()),
    ):
        _register_tool_function(toolkit, runtime, function, group_name="knowledge-rag", policy=policy)

    for function, policy in (
        (sandbox_status, _ToolExecutionPolicy()),
        (sandbox_list_files, _ToolExecutionPolicy()),
        (sandbox_write_file, _ToolExecutionPolicy(dedupe=False, invalidates_cache=True)),
        (sandbox_edit_file, _ToolExecutionPolicy(dedupe=False, invalidates_cache=True)),
        (sandbox_multiedit_file, _ToolExecutionPolicy(dedupe=False, invalidates_cache=True)),
        (sandbox_read_file, _ToolExecutionPolicy()),
        (sandbox_install_packages, _ToolExecutionPolicy(dedupe=False, invalidates_cache=True)),
        (sandbox_run_python, _ToolExecutionPolicy(invalidates_cache=True)),
    ):
        _register_tool_function(toolkit, runtime, function, group_name="python-sandbox", policy=policy)
