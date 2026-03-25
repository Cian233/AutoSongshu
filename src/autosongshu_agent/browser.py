from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    CDPSession,
    Page,
    Playwright,
    sync_playwright,
)

from .artifacts import ArtifactStore
from .config import BrowserConfig
from .scope import ScopePolicy


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
_MAX_NETWORK_EVENTS = 1200
_MAX_CONSOLE_EVENTS = 400
_MAX_RESPONSE_BODIES = 400


def _timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _truncate_text(value: str | None, max_chars: int) -> str | None:
    if value is None:
        return None
    if len(value) <= max_chars:
        return value
    return value[:max_chars]


def _append_bounded(items: list[dict[str, Any]], item: dict[str, Any], limit: int) -> None:
    items.append(item)
    if len(items) > limit:
        del items[:-limit]


def _is_textual_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    lowered = content_type.lower()
    return any(marker in lowered for marker in _TEXTUAL_CONTENT_TYPE_MARKERS)


def _is_textual_resource(resource_type: str | None, content_type: str | None = None) -> bool:
    if resource_type in _TEXTUAL_RESOURCE_TYPES:
        return True
    return _is_textual_content_type(content_type)


class CDPBrowserSession:
    def __init__(
        self,
        settings: BrowserConfig,
        scope: ScopePolicy,
        artifacts: ArtifactStore,
    ) -> None:
        self.settings = settings
        self.scope = scope
        self.artifacts = artifacts
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.cdp_session: CDPSession | None = None
        self.network_events: list[dict[str, Any]] = []
        self.console_events: list[dict[str, Any]] = []
        self.response_bodies: list[dict[str, Any]] = []
        self.cdp_request_details: dict[str, dict[str, Any]] = {}
        self.cdp_request_order: list[str] = []
        self._events_bound = False
        self.active_mode: str | None = None
        self.last_start_error: str | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="autosongshu-browser")
        self._browser_thread_id: int | None = None
        self._closed = False

    def _ensure_cdp_request_record(self, request_id: str) -> dict[str, Any]:
        record = self.cdp_request_details.get(request_id)
        if record is None:
            record = {
                "request_id": request_id,
                "resource_type": None,
                "frame_id": None,
                "loader_id": None,
                "document_url": None,
                "initiator": None,
                "served_from_cache": False,
                "loading_status": "pending",
                "request": {},
                "response": {},
                "request_extra_info": {},
                "response_extra_info": {},
                "redirect_chain": [],
                "response_body_preview": None,
                "response_body_length": None,
                "response_body_base64": False,
                "response_body_capture": "unavailable",
                "timestamps": {},
            }
            self.cdp_request_details[request_id] = record
            self.cdp_request_order.append(request_id)
            if len(self.cdp_request_order) > 600:
                oldest = self.cdp_request_order.pop(0)
                self.cdp_request_details.pop(oldest, None)
        return record

    def _serialize_cdp_request_record(
        self,
        record: dict[str, Any],
        body_chars: int = 4000,
    ) -> dict[str, Any]:
        request = dict(record.get("request") or {})
        response = dict(record.get("response") or {})
        request["post_data"] = _truncate_text(request.get("post_data"), body_chars)
        body_preview = _truncate_text(record.get("response_body_preview"), body_chars)
        return {
            "request_id": record.get("request_id"),
            "resource_type": record.get("resource_type"),
            "frame_id": record.get("frame_id"),
            "loader_id": record.get("loader_id"),
            "document_url": record.get("document_url"),
            "initiator": record.get("initiator"),
            "served_from_cache": record.get("served_from_cache"),
            "loading_status": record.get("loading_status"),
            "failure_text": record.get("failure_text"),
            "request": request,
            "response": response,
            "request_extra_info": record.get("request_extra_info") or {},
            "response_extra_info": record.get("response_extra_info") or {},
            "redirect_chain": list(record.get("redirect_chain") or []),
            "response_body_preview": body_preview,
            "response_body_length": record.get("response_body_length"),
            "response_body_base64": record.get("response_body_base64"),
            "response_body_capture": record.get("response_body_capture"),
            "timestamps": dict(record.get("timestamps") or {}),
        }

    def _capture_cdp_request_post_data(self, request_id: str, record: dict[str, Any]) -> None:
        if self.cdp_session is None:
            return
        request = record.setdefault("request", {})
        if request.get("post_data") or not request.get("has_post_data"):
            return
        try:
            result = self.cdp_session.send("Network.getRequestPostData", {"requestId": request_id})
        except Exception as exc:
            request["post_data_error"] = str(exc)
            return
        request["post_data"] = result.get("postData")

    def _capture_cdp_response_body(self, request_id: str, record: dict[str, Any]) -> None:
        if self.cdp_session is None:
            return
        if record.get("response_body_capture") not in {None, "unavailable"}:
            return

        response = record.get("response") or {}
        content_type = (
            response.get("mime_type")
            or (response.get("headers") or {}).get("content-type")
            or (record.get("response_extra_info") or {}).get("headers", {}).get("content-type")
        )
        if not _is_textual_resource(record.get("resource_type"), content_type):
            record["response_body_capture"] = "skipped"
            return

        try:
            result = self.cdp_session.send("Network.getResponseBody", {"requestId": request_id})
        except Exception as exc:
            record["response_body_capture"] = "error"
            record["response_body_error"] = str(exc)
            return

        body = result.get("body")
        if not isinstance(body, str):
            record["response_body_capture"] = "empty"
            record["response_body_length"] = 0
            return

        record["response_body_base64"] = bool(result.get("base64Encoded"))
        record["response_body_length"] = len(body)
        record["response_body_preview"] = _truncate_text(body, 12000)
        record["response_body_capture"] = "base64" if result.get("base64Encoded") else "text"

    def _on_cdp_request_will_be_sent(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId") or "")
        if not request_id:
            return

        record = self._ensure_cdp_request_record(request_id)
        redirect_response = event.get("redirectResponse")
        if redirect_response:
            record.setdefault("redirect_chain", []).append(
                {
                    "url": redirect_response.get("url"),
                    "status": redirect_response.get("status"),
                    "status_text": redirect_response.get("statusText"),
                    "headers": redirect_response.get("headers") or {},
                    "mime_type": redirect_response.get("mimeType"),
                },
            )
            record["response"] = {}
            record["response_body_preview"] = None
            record["response_body_length"] = None
            record["response_body_base64"] = False
            record["response_body_capture"] = "unavailable"

        request = event.get("request") or {}
        post_data = request.get("postData")
        post_data_entries = request.get("postDataEntries")
        if post_data is None and isinstance(post_data_entries, list):
            encoded_chunks = []
            for item in post_data_entries:
                bytes_value = item.get("bytes") if isinstance(item, dict) else None
                if isinstance(bytes_value, str):
                    encoded_chunks.append(bytes_value)
            if encoded_chunks:
                post_data = "\n".join(encoded_chunks)

        record["resource_type"] = event.get("type") or record.get("resource_type")
        record["frame_id"] = event.get("frameId") or record.get("frame_id")
        record["loader_id"] = event.get("loaderId") or record.get("loader_id")
        record["document_url"] = event.get("documentURL") or record.get("document_url")
        record["initiator"] = event.get("initiator") or record.get("initiator")
        record["loading_status"] = "pending"
        record["timestamps"]["request"] = _timestamp()
        record["request"] = {
            "url": request.get("url"),
            "method": request.get("method"),
            "headers": request.get("headers") or {},
            "has_post_data": bool(request.get("hasPostData") or post_data),
            "post_data": post_data,
            "mixed_content_type": request.get("mixedContentType"),
            "initial_priority": request.get("initialPriority"),
            "referrer_policy": request.get("referrerPolicy"),
        }

    def _on_cdp_request_extra_info(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId") or "")
        if not request_id:
            return
        record = self._ensure_cdp_request_record(request_id)
        record["request_extra_info"] = {
            "headers": event.get("headers") or {},
            "associated_cookies": event.get("associatedCookies") or [],
            "connect_timing": event.get("connectTiming"),
            "site_has_cookie_in_other_partition": event.get("siteHasCookieInOtherPartition"),
            "client_security_state": event.get("clientSecurityState"),
        }

    def _on_cdp_response_received(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId") or "")
        if not request_id:
            return

        record = self._ensure_cdp_request_record(request_id)
        response = event.get("response") or {}
        record["resource_type"] = event.get("type") or record.get("resource_type")
        record["frame_id"] = event.get("frameId") or record.get("frame_id")
        record["loader_id"] = event.get("loaderId") or record.get("loader_id")
        record["timestamps"]["response"] = _timestamp()
        record["response"] = {
            "url": response.get("url"),
            "status": response.get("status"),
            "status_text": response.get("statusText"),
            "headers": response.get("headers") or {},
            "mime_type": response.get("mimeType"),
            "protocol": response.get("protocol"),
            "remote_ip_address": response.get("remoteIPAddress"),
            "remote_port": response.get("remotePort"),
            "from_disk_cache": response.get("fromDiskCache"),
            "from_service_worker": response.get("fromServiceWorker"),
            "from_prefetch_cache": response.get("fromPrefetchCache"),
            "encoded_data_length": response.get("encodedDataLength"),
            "security_state": response.get("securityState"),
            "security_details": response.get("securityDetails"),
        }

    def _on_cdp_response_extra_info(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId") or "")
        if not request_id:
            return
        record = self._ensure_cdp_request_record(request_id)
        record["response_extra_info"] = {
            "status_code": event.get("statusCode"),
            "headers": event.get("headers") or {},
            "headers_text": event.get("headersText"),
            "blocked_cookies": event.get("blockedCookies") or [],
            "resource_ip_address_space": event.get("resourceIPAddressSpace"),
            "cookie_partition_key": event.get("cookiePartitionKey"),
        }
        response = record.setdefault("response", {})
        if event.get("statusCode") and not response.get("status"):
            response["status"] = event.get("statusCode")
        if event.get("headers") and not response.get("headers"):
            response["headers"] = event.get("headers") or {}

    def _on_cdp_request_served_from_cache(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId") or "")
        if not request_id:
            return
        record = self._ensure_cdp_request_record(request_id)
        record["served_from_cache"] = True

    def _on_cdp_loading_finished(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId") or "")
        if not request_id:
            return
        record = self._ensure_cdp_request_record(request_id)
        record["loading_status"] = "finished"
        record["timestamps"]["finished"] = _timestamp()
        response = record.setdefault("response", {})
        response["encoded_data_length"] = event.get("encodedDataLength")
        self._capture_cdp_request_post_data(request_id, record)
        self._capture_cdp_response_body(request_id, record)

    def _on_cdp_loading_failed(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("requestId") or "")
        if not request_id:
            return
        record = self._ensure_cdp_request_record(request_id)
        record["loading_status"] = "failed"
        record["failure_text"] = event.get("errorText")
        record["timestamps"]["failed"] = _timestamp()

    def _run_in_browser_thread(self, function: Any, *args: Any, **kwargs: Any) -> Any:
        if self._closed:
            raise RuntimeError("Browser session is already closed.")

        current_thread_id = threading.get_ident()
        if self._browser_thread_id is not None and current_thread_id == self._browser_thread_id:
            return function(*args, **kwargs)

        future = self._executor.submit(self._call_in_browser_thread, function, *args, **kwargs)
        return future.result()

    def _call_in_browser_thread(self, function: Any, *args: Any, **kwargs: Any) -> Any:
        if self._browser_thread_id is None:
            self._browser_thread_id = threading.get_ident()
        return function(*args, **kwargs)

    def _launch_local_browser(self, chromium: Any) -> None:
        launch_kwargs: dict[str, Any] = {"headless": self.settings.headless}
        if self.settings.channel:
            launch_kwargs["channel"] = self.settings.channel
        if self.settings.executable_path:
            launch_kwargs["executable_path"] = self.settings.executable_path
        self.browser = chromium.launch(**launch_kwargs)
        self.context = self.browser.new_context(
            ignore_https_errors=self.settings.ignore_https_errors,
            viewport={
                "width": self.settings.viewport_width,
                "height": self.settings.viewport_height,
            },
        )
        self.active_mode = "launch"

    def _start_impl(self) -> None:
        if self.page is not None:
            return

        self.playwright = sync_playwright().start()
        chromium = self.playwright.chromium

        if self.settings.mode == "connect_over_cdp":
            try:
                self.browser = chromium.connect_over_cdp(self.settings.cdp_url)
                if self.browser.contexts:
                    self.context = self.browser.contexts[0]
                else:
                    self.context = self.browser.new_context(
                        ignore_https_errors=self.settings.ignore_https_errors,
                        viewport={
                            "width": self.settings.viewport_width,
                            "height": self.settings.viewport_height,
                        },
                    )
                self.active_mode = "connect_over_cdp"
                self.last_start_error = None
            except Exception as exc:
                self.last_start_error = str(exc)
                if not self.settings.fallback_to_launch_on_cdp_error:
                    raise
                self._launch_local_browser(chromium)
        else:
            self._launch_local_browser(chromium)

        if self.context is None:
            raise RuntimeError("Unable to create or access a browser context.")

        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(self.settings.timeout_ms)
        self._wire_events()
        self._attach_cdp()

    def start(self) -> None:
        self._run_in_browser_thread(self._start_impl)

    def _wire_events(self) -> None:
        if self.page is None or self._events_bound:
            return

        def on_console(msg: Any) -> None:
            _append_bounded(
                self.console_events,
                {
                    "timestamp": _timestamp(),
                    "type": msg.type,
                    "text": msg.text,
                },
                _MAX_CONSOLE_EVENTS,
            )

        def on_request(request: Any) -> None:
            post_data: str | None = None
            try:
                candidate = getattr(request, "post_data", None)
                post_data = candidate() if callable(candidate) else candidate
            except Exception:
                post_data = None
            _append_bounded(
                self.network_events,
                {
                    "timestamp": _timestamp(),
                    "phase": "request",
                    "method": request.method,
                    "url": request.url,
                    "resource_type": request.resource_type,
                    "headers": request.headers,
                    "post_data_preview": _truncate_text(post_data, 4000),
                },
                _MAX_NETWORK_EVENTS,
            )

        def on_response(response: Any) -> None:
            request = response.request
            resource_type = request.resource_type
            content_type = response.headers.get("content-type")
            _append_bounded(
                self.network_events,
                {
                    "timestamp": _timestamp(),
                    "phase": "response",
                    "method": request.method,
                    "url": response.url,
                    "status": response.status,
                    "resource_type": resource_type,
                    "content_type": content_type,
                    "headers": response.headers,
                },
                _MAX_NETWORK_EVENTS,
            )
            if resource_type not in {"document", "xhr", "fetch", "script", "stylesheet", "manifest"}:
                return
            preview: str | None = None
            if _is_textual_content_type(content_type):
                try:
                    preview = _truncate_text(response.text(), 12000)
                except Exception:
                    preview = None
            _append_bounded(
                self.response_bodies,
                {
                    "timestamp": _timestamp(),
                    "method": request.method,
                    "url": response.url,
                    "status": response.status,
                    "resource_type": resource_type,
                    "content_type": content_type,
                    "request_headers": request.headers,
                    "body_preview": preview,
                },
                _MAX_RESPONSE_BODIES,
            )

        def on_request_failed(request: Any) -> None:
            failure = request.failure
            _append_bounded(
                self.network_events,
                {
                    "timestamp": _timestamp(),
                    "phase": "request_failed",
                    "method": request.method,
                    "url": request.url,
                    "failure": failure if isinstance(failure, str) else str(failure),
                },
                _MAX_NETWORK_EVENTS,
            )

        self.page.on("console", on_console)
        self.page.on("request", on_request)
        self.page.on("response", on_response)
        self.page.on("requestfailed", on_request_failed)
        self._events_bound = True

    def _attach_cdp(self) -> None:
        if self.context is None or self.page is None:
            return
        self.cdp_session = self.context.new_cdp_session(self.page)
        event_handlers = {
            "Network.requestWillBeSent": self._on_cdp_request_will_be_sent,
            "Network.requestWillBeSentExtraInfo": self._on_cdp_request_extra_info,
            "Network.responseReceived": self._on_cdp_response_received,
            "Network.responseReceivedExtraInfo": self._on_cdp_response_extra_info,
            "Network.requestServedFromCache": self._on_cdp_request_served_from_cache,
            "Network.loadingFinished": self._on_cdp_loading_finished,
            "Network.loadingFailed": self._on_cdp_loading_failed,
        }
        for event_name, handler in event_handlers.items():
            try:
                self.cdp_session.on(event_name, handler)
            except Exception:
                continue
        for command in ("Page.enable", "Runtime.enable", "Network.enable"):
            try:
                self.cdp_session.send(command)
            except Exception:
                continue

    def _ensure_page(self) -> Page:
        self._start_impl()
        if self.page is None:
            raise RuntimeError("Browser page is not initialized.")
        return self.page

    def _current_url_impl(self) -> str:
        page = self._ensure_page()
        return page.url or self.scope.start_url

    def current_url(self) -> str:
        return self._run_in_browser_thread(self._current_url_impl)

    def _status_impl(self) -> dict[str, Any]:
        page = self._ensure_page()
        return {
            "requested_mode": self.settings.mode,
            "active_mode": self.active_mode,
            "cdp_url": self.settings.cdp_url,
            "cdp_attached": self.cdp_session is not None,
            "fallback_to_launch_on_cdp_error": self.settings.fallback_to_launch_on_cdp_error,
            "last_start_error": self.last_start_error,
            "current_url": page.url or self.scope.start_url,
            "title": page.title(),
        }

    def status(self) -> dict[str, Any]:
        return self._run_in_browser_thread(self._status_impl)

    def _navigate_impl(self, url: str) -> dict[str, Any]:
        page = self._ensure_page()
        target_url = self.scope.assert_in_scope(url, current_url=self._current_url_impl())
        response = page.goto(target_url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=min(self.settings.timeout_ms, 5000))
        except Exception:
            pass
        return {
            "url": page.url,
            "title": page.title(),
            "status": response.status if response else None,
        }

    def navigate(self, url: str) -> dict[str, Any]:
        return self._run_in_browser_thread(self._navigate_impl, url)

    def _click_impl(self, selector: str) -> dict[str, Any]:
        page = self._ensure_page()
        page.click(selector)
        return {"clicked": selector, "url": page.url}

    def click(self, selector: str) -> dict[str, Any]:
        return self._run_in_browser_thread(self._click_impl, selector)

    def _fill_impl(self, selector: str, text: str, submit: bool = False) -> dict[str, Any]:
        page = self._ensure_page()
        page.fill(selector, text)
        if submit:
            page.press(selector, "Enter")
        return {"filled": selector, "submitted": submit, "url": page.url}

    def fill(self, selector: str, text: str, submit: bool = False) -> dict[str, Any]:
        return self._run_in_browser_thread(self._fill_impl, selector, text, submit)

    def _press_impl(self, selector: str, key: str) -> dict[str, Any]:
        page = self._ensure_page()
        page.press(selector, key)
        return {"selector": selector, "key": key, "url": page.url}

    def press(self, selector: str, key: str) -> dict[str, Any]:
        return self._run_in_browser_thread(self._press_impl, selector, key)

    def _evaluate_impl(self, script: str) -> Any:
        page = self._ensure_page()
        return page.evaluate(script)

    def evaluate(self, script: str) -> Any:
        return self._run_in_browser_thread(self._evaluate_impl, script)

    def _wait_for_load_state_impl(self, state: str = "networkidle", timeout_ms: int | None = None) -> dict[str, Any]:
        page = self._ensure_page()
        effective_timeout = timeout_ms if timeout_ms is not None else self.settings.timeout_ms
        page.wait_for_load_state(state, timeout=effective_timeout)
        return {"state": state, "timeout_ms": effective_timeout, "url": page.url}

    def wait_for_load_state(self, state: str = "networkidle", timeout_ms: int | None = None) -> dict[str, Any]:
        return self._run_in_browser_thread(self._wait_for_load_state_impl, state, timeout_ms)

    def _wait_for_selector_impl(
        self,
        selector: str,
        state: str = "visible",
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        page = self._ensure_page()
        effective_timeout = timeout_ms if timeout_ms is not None else self.settings.timeout_ms
        locator = page.wait_for_selector(selector, state=state, timeout=effective_timeout)
        text_preview = ""
        if locator is not None:
            try:
                text_preview = (locator.inner_text() or "").strip()[:300]
            except Exception:
                text_preview = ""
        return {
            "selector": selector,
            "state": state,
            "timeout_ms": effective_timeout,
            "url": page.url,
            "text_preview": text_preview,
        }

    def wait_for_selector(
        self,
        selector: str,
        state: str = "visible",
        timeout_ms: int | None = None,
    ) -> dict[str, Any]:
        return self._run_in_browser_thread(self._wait_for_selector_impl, selector, state, timeout_ms)

    def _get_html_impl(self, max_chars: int = 20000) -> dict[str, Any]:
        page = self._ensure_page()
        html = page.content()
        return {
            "url": page.url,
            "title": page.title(),
            "html_preview": html[:max_chars],
            "html_length": len(html),
        }

    def get_html(self, max_chars: int = 20000) -> dict[str, Any]:
        return self._run_in_browser_thread(self._get_html_impl, max_chars)

    def _snapshot_impl(
        self,
        max_chars: int = 8000,
        max_forms: int = 40,
        max_inputs: int = 40,
        max_links: int = 120,
        storage_items: int = 50,
    ) -> dict[str, Any]:
        page = self._ensure_page()
        return page.evaluate(
            """
            ({ maxChars, maxForms, maxInputs, maxLinks, storageItems }) => {
              const safeEntries = (storage) => {
                try {
                  return Object.fromEntries(
                    Object.keys(storage).slice(0, storageItems).map((key) => [key, storage.getItem(key)])
                  );
                } catch (error) {
                  return { error: String(error) };
                }
              };

              const forms = Array.from(document.forms).slice(0, maxForms).map((form, index) => ({
                index,
                action: form.action || location.href,
                method: (form.method || "get").toUpperCase(),
                id: form.id || null,
                name: form.name || null,
                inputs: Array.from(form.elements).slice(0, maxInputs).map((element) => ({
                  tag: element.tagName,
                  type: element.type || null,
                  name: element.name || null,
                  valuePreview: typeof element.value === "string" ? element.value.slice(0, 100) : null,
                })),
              }));

              const links = Array.from(document.querySelectorAll("a[href]"))
                .slice(0, maxLinks)
                .map((anchor) => ({
                  text: (anchor.innerText || anchor.textContent || "").trim().slice(0, 120),
                  href: anchor.href,
                }));

              return {
                url: location.href,
                title: document.title,
                forms,
                links,
                text_excerpt: (document.body?.innerText || "").slice(0, maxChars),
                local_storage: safeEntries(window.localStorage),
                session_storage: safeEntries(window.sessionStorage),
              };
            }
            """,
            {
                "maxChars": max_chars,
                "maxForms": max_forms,
                "maxInputs": max_inputs,
                "maxLinks": max_links,
                "storageItems": storage_items,
            },
        )

    def snapshot(
        self,
        max_chars: int = 8000,
        max_forms: int = 40,
        max_inputs: int = 40,
        max_links: int = 120,
        storage_items: int = 50,
    ) -> dict[str, Any]:
        return self._run_in_browser_thread(
            self._snapshot_impl,
            max_chars,
            max_forms,
            max_inputs,
            max_links,
            storage_items,
        )

    def list_forms(self, max_forms: int = 40, max_inputs: int = 40) -> list[dict[str, Any]]:
        return self._run_in_browser_thread(
            lambda: self._snapshot_impl(
                max_chars=1000,
                max_forms=max_forms,
                max_inputs=max_inputs,
                max_links=0,
            )["forms"],
        )

    def list_links(self, limit: int = 120) -> list[dict[str, Any]]:
        return self._run_in_browser_thread(self._list_links_impl, limit)

    def _list_links_impl(self, limit: int = 120) -> list[dict[str, Any]]:
        page = self._ensure_page()
        return page.evaluate(
            """
            ({ limit }) => Array.from(document.querySelectorAll("a[href]"))
              .slice(0, limit)
              .map((anchor) => ({
                text: (anchor.innerText || anchor.textContent || "").trim().slice(0, 120),
                href: anchor.href,
              }))
            """,
            {"limit": limit},
        )

    def storage_snapshot(self) -> dict[str, Any]:
        return self._run_in_browser_thread(self._storage_snapshot_impl)

    def _storage_snapshot_impl(self) -> dict[str, Any]:
        snapshot = self._snapshot_impl(max_chars=1000, max_forms=0, max_inputs=0, max_links=0, storage_items=50)
        return {
            "url": snapshot["url"],
            "local_storage": snapshot["local_storage"],
            "session_storage": snapshot["session_storage"],
        }

    def get_cookies(self) -> list[dict[str, Any]]:
        return self._run_in_browser_thread(self._get_cookies_impl)

    def _get_cookies_impl(self) -> list[dict[str, Any]]:
        if self.context is None:
            self._start_impl()
        if self.context is None:
            raise RuntimeError("Browser context is not initialized.")
        return self.context.cookies()

    def get_network_log(self, limit: int | None = 100) -> list[dict[str, Any]]:
        return self._run_in_browser_thread(self._get_network_log_impl, limit)

    def _get_network_log_impl(self, limit: int | None = 100) -> list[dict[str, Any]]:
        if limit is None:
            return list(self.network_events)
        return self.network_events[-limit:]

    def get_console_log(self, limit: int | None = 50) -> list[dict[str, Any]]:
        return self._run_in_browser_thread(self._get_console_log_impl, limit)

    def _get_console_log_impl(self, limit: int | None = 50) -> list[dict[str, Any]]:
        if limit is None:
            return list(self.console_events)
        return self.console_events[-limit:]

    def get_response_bodies(self, limit: int = 40, url_contains: str = "") -> list[dict[str, Any]]:
        return self._run_in_browser_thread(self._get_response_bodies_impl, limit, url_contains)

    def _get_response_bodies_impl(self, limit: int = 40, url_contains: str = "") -> list[dict[str, Any]]:
        entries = self.response_bodies
        if url_contains:
            lowered = url_contains.lower()
            entries = [item for item in entries if lowered in item["url"].lower()]
        return entries[-limit:]

    def get_cdp_requests(
        self,
        limit: int | None = 100,
        url_contains: str = "",
        body_chars: int = 4000,
    ) -> list[dict[str, Any]]:
        return self._run_in_browser_thread(self._get_cdp_requests_impl, limit, url_contains, body_chars)

    def _get_cdp_requests_impl(
        self,
        limit: int | None = 100,
        url_contains: str = "",
        body_chars: int = 4000,
    ) -> list[dict[str, Any]]:
        records = [
            self._serialize_cdp_request_record(self.cdp_request_details[request_id], body_chars=body_chars)
            for request_id in self.cdp_request_order
            if request_id in self.cdp_request_details
        ]
        if url_contains:
            lowered = url_contains.lower()
            records = [
                item
                for item in records
                if lowered in str((item.get("request") or {}).get("url") or "").lower()
                or lowered in str((item.get("response") or {}).get("url") or "").lower()
            ]
        if limit is None:
            return records
        return records[-limit:]

    def _collect_page_resource_inventory_impl(
        self,
        max_external_scripts: int = 80,
        max_inline_scripts: int = 20,
        max_stylesheets: int = 40,
        max_inline_styles: int = 10,
        max_iframes: int = 20,
        max_performance_entries: int = 200,
        max_inline_code_chars: int = 4000,
    ) -> dict[str, Any]:
        page = self._ensure_page()
        return page.evaluate(
            """
            ({
              maxExternalScripts,
              maxInlineScripts,
              maxStylesheets,
              maxInlineStyles,
              maxIframes,
              maxPerformanceEntries,
              maxInlineCodeChars,
            }) => {
              const trim = (value, maxChars) => typeof value === "string" ? value.slice(0, maxChars) : null;
              const toNumber = (value) => Number.isFinite(value) ? Number(value.toFixed(2)) : null;
              const normalizeUrl = (value) => {
                if (!value) {
                  return null;
                }
                try {
                  return new URL(value, location.href).href;
                } catch (error) {
                  return value;
                }
              };

              const scriptNodes = Array.from(document.scripts || []);
              const externalScripts = scriptNodes
                .filter((script) => script.src)
                .slice(0, maxExternalScripts)
                .map((script, index) => ({
                  index,
                  src: script.src,
                  type: script.type || null,
                  async: Boolean(script.async),
                  defer: Boolean(script.defer),
                  crossOrigin: script.crossOrigin || null,
                  referrerPolicy: script.referrerPolicy || null,
                  integrity: script.integrity || null,
                }));

              const inlineScripts = scriptNodes
                .filter((script) => !script.src)
                .slice(0, maxInlineScripts)
                .map((script, index) => ({
                  index,
                  type: script.type || null,
                  nonce: script.nonce || null,
                  preview: trim(script.textContent || "", maxInlineCodeChars),
                }));

              const stylesheetLinks = Array.from(
                document.querySelectorAll('link[rel~="stylesheet"], link[as="style"]')
              )
                .slice(0, maxStylesheets)
                .map((link, index) => ({
                  index,
                  href: normalizeUrl(link.getAttribute("href") || link.href || ""),
                  rel: link.rel || null,
                  media: link.media || null,
                  disabled: Boolean(link.disabled),
                  crossOrigin: link.crossOrigin || null,
                  integrity: link.integrity || null,
                }));

              const inlineStyles = Array.from(document.querySelectorAll("style"))
                .slice(0, maxInlineStyles)
                .map((style, index) => ({
                  index,
                  preview: trim(style.textContent || "", maxInlineCodeChars),
                }));

              const iframes = Array.from(document.querySelectorAll("iframe"))
                .slice(0, maxIframes)
                .map((frame, index) => ({
                  index,
                  src: normalizeUrl(frame.getAttribute("src") || frame.src || ""),
                  name: frame.name || null,
                  title: frame.title || null,
                }));

              const manifests = Array.from(document.querySelectorAll('link[rel="manifest"]')).map((link, index) => ({
                index,
                href: normalizeUrl(link.getAttribute("href") || link.href || ""),
              }));

              const performanceResources = Array.from(performance.getEntriesByType("resource"))
                .slice(-maxPerformanceEntries)
                .map((entry) => ({
                  name: entry.name,
                  initiator_type: entry.initiatorType || null,
                  duration_ms: toNumber(entry.duration),
                  transfer_size: Number.isFinite(entry.transferSize) ? entry.transferSize : null,
                  encoded_body_size: Number.isFinite(entry.encodedBodySize) ? entry.encodedBodySize : null,
                  decoded_body_size: Number.isFinite(entry.decodedBodySize) ? entry.decodedBodySize : null,
                  next_hop_protocol: entry.nextHopProtocol || null,
                  render_blocking_status: entry.renderBlockingStatus || null,
                }));

              const navigationEntry = performance.getEntriesByType("navigation")[0];
              return {
                url: location.href,
                title: document.title,
                ready_state: document.readyState,
                external_scripts: externalScripts,
                inline_scripts: inlineScripts,
                stylesheets: stylesheetLinks,
                inline_styles: inlineStyles,
                iframes,
                manifests,
                performance_resources: performanceResources,
                navigation: navigationEntry
                  ? {
                      name: navigationEntry.name,
                      type: navigationEntry.type || null,
                      duration_ms: toNumber(navigationEntry.duration),
                      transfer_size: Number.isFinite(navigationEntry.transferSize)
                        ? navigationEntry.transferSize
                        : null,
                    }
                  : null,
              };
            }
            """,
            {
                "maxExternalScripts": max_external_scripts,
                "maxInlineScripts": max_inline_scripts,
                "maxStylesheets": max_stylesheets,
                "maxInlineStyles": max_inline_styles,
                "maxIframes": max_iframes,
                "maxPerformanceEntries": max_performance_entries,
                "maxInlineCodeChars": max_inline_code_chars,
            },
        )

    def analyze_page_resources(
        self,
        max_resources: int = 120,
        max_inline_scripts: int = 20,
        max_body_chars: int = 4000,
    ) -> dict[str, Any]:
        return self._run_in_browser_thread(
            self._analyze_page_resources_impl,
            max_resources,
            max_inline_scripts,
            max_body_chars,
        )

    def _analyze_page_resources_impl(
        self,
        max_resources: int = 120,
        max_inline_scripts: int = 20,
        max_body_chars: int = 4000,
    ) -> dict[str, Any]:
        inventory = self._collect_page_resource_inventory_impl(
            max_inline_scripts=max_inline_scripts,
            max_inline_code_chars=max_body_chars,
            max_performance_entries=max(max_resources * 2, 200),
        )
        cdp_records = self._get_cdp_requests_impl(limit=None, body_chars=max_body_chars)

        merged: dict[str, dict[str, Any]] = {}
        order: list[str] = []

        def ensure_resource(url: str | None) -> dict[str, Any] | None:
            if not url:
                return None
            item = merged.get(url)
            if item is None:
                item = {
                    "url": url,
                    "sources": [],
                    "dom_roles": [],
                    "request_count": 0,
                    "resource_type": None,
                    "method": None,
                    "status": None,
                    "content_type": None,
                    "request_body_preview": None,
                    "response_body_preview": None,
                    "performance": {},
                }
                merged[url] = item
                order.append(url)
            return item

        def add_source(item: dict[str, Any], source: str) -> None:
            if source not in item["sources"]:
                item["sources"].append(source)

        def add_dom_role(item: dict[str, Any], role: str) -> None:
            if role not in item["dom_roles"]:
                item["dom_roles"].append(role)

        navigation = inventory.get("navigation") or {}
        current_url = str(inventory.get("url") or self._current_url_impl())
        current_item = ensure_resource(current_url)
        if current_item is not None:
            add_source(current_item, "dom")
            add_source(current_item, "navigation")
            add_dom_role(current_item, "document")
            current_item["resource_type"] = current_item.get("resource_type") or "document"
            current_item["performance"] = {
                **current_item.get("performance", {}),
                **{key: value for key, value in navigation.items() if key != "name"},
            }

        for record in cdp_records:
            request = record.get("request") or {}
            response = record.get("response") or {}
            url = str(request.get("url") or response.get("url") or "")
            item = ensure_resource(url)
            if item is None:
                continue
            add_source(item, "cdp")
            item["request_count"] = int(item.get("request_count") or 0) + 1
            item["resource_type"] = record.get("resource_type") or item.get("resource_type")
            item["method"] = request.get("method") or item.get("method")
            item["status"] = response.get("status") or item.get("status")
            item["content_type"] = (
                response.get("mime_type")
                or (response.get("headers") or {}).get("content-type")
                or item.get("content_type")
            )
            if request.get("post_data"):
                item["request_body_preview"] = request.get("post_data")
            if record.get("response_body_preview"):
                item["response_body_preview"] = record.get("response_body_preview")

        for entry in inventory.get("performance_resources") or []:
            url = str(entry.get("name") or "")
            item = ensure_resource(url)
            if item is None:
                continue
            add_source(item, "performance")
            item["resource_type"] = item.get("resource_type") or entry.get("initiator_type")
            item["performance"] = {
                **item.get("performance", {}),
                **{key: value for key, value in entry.items() if key != "name"},
            }

        for script in inventory.get("external_scripts") or []:
            item = ensure_resource(script.get("src"))
            if item is not None:
                add_source(item, "dom")
                add_dom_role(item, "script")
                item["resource_type"] = item.get("resource_type") or "script"

        for stylesheet in inventory.get("stylesheets") or []:
            item = ensure_resource(stylesheet.get("href"))
            if item is not None:
                add_source(item, "dom")
                add_dom_role(item, "stylesheet")
                item["resource_type"] = item.get("resource_type") or "stylesheet"

        for frame in inventory.get("iframes") or []:
            item = ensure_resource(frame.get("src"))
            if item is not None:
                add_source(item, "dom")
                add_dom_role(item, "iframe")
                item["resource_type"] = item.get("resource_type") or "iframe"

        for manifest in inventory.get("manifests") or []:
            item = ensure_resource(manifest.get("href"))
            if item is not None:
                add_source(item, "dom")
                add_dom_role(item, "manifest")
                item["resource_type"] = item.get("resource_type") or "manifest"

        resources = [merged[url] for url in order][:max_resources]
        resource_type_counts = Counter(str(item.get("resource_type") or "unknown") for item in resources)
        source_counts = Counter(source for item in resources for source in item.get("sources") or [])

        return {
            "url": current_url,
            "title": inventory.get("title"),
            "ready_state": inventory.get("ready_state"),
            "summary": {
                "inventory_count": len(resources),
                "external_script_count": len(inventory.get("external_scripts") or []),
                "inline_script_count": len(inventory.get("inline_scripts") or []),
                "stylesheet_count": len(inventory.get("stylesheets") or []),
                "inline_style_count": len(inventory.get("inline_styles") or []),
                "iframe_count": len(inventory.get("iframes") or []),
                "performance_resource_count": len(inventory.get("performance_resources") or []),
                "cdp_request_count": len(cdp_records),
                "resource_type_counts": dict(resource_type_counts),
                "source_counts": dict(source_counts),
            },
            "dom": {
                "external_scripts": inventory.get("external_scripts") or [],
                "inline_scripts": inventory.get("inline_scripts") or [],
                "stylesheets": inventory.get("stylesheets") or [],
                "inline_styles": inventory.get("inline_styles") or [],
                "iframes": inventory.get("iframes") or [],
                "manifests": inventory.get("manifests") or [],
            },
            "loaded_resources": resources,
            "recent_cdp_requests": cdp_records[-min(25, len(cdp_records)):],
        }

    def screenshot(self, name: str = "page") -> str:
        return self._run_in_browser_thread(self._screenshot_impl, name)

    def _screenshot_impl(self, name: str = "page") -> str:
        page = self._ensure_page()
        relative_path = f"screenshots/{name}.png"
        target = self.artifacts.path(relative_path)
        page.screenshot(path=str(target), full_page=True)
        return str(target)

    def cdp_send(self, method: str, params: dict[str, Any] | None = None) -> Any:
        return self._run_in_browser_thread(self._cdp_send_impl, method, params)

    def _cdp_send_impl(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._start_impl()
        if self.cdp_session is None:
            raise RuntimeError("CDP session is not available.")
        result = self.cdp_session.send(method, params or {})
        self.artifacts.append_jsonl(
            "cdp-log.jsonl",
            {"method": method, "params": params or {}, "result": result},
        )
        return result

    def _close_impl(self) -> None:
        if self.browser is not None:
            self.browser.close()
        if self.playwright is not None:
            self.playwright.stop()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.cdp_session = None

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._run_in_browser_thread(self._close_impl)
        finally:
            self._closed = True
            self._executor.shutdown(wait=True, cancel_futures=True)
