from __future__ import annotations

from collections import deque
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from .artifacts import ArtifactStore
from .discovery import (
    COMMON_PASSIVE_DISCOVERY_PATHS,
    extract_in_scope_candidate_urls,
    is_api_like_url,
    is_queueable_discovery_url,
    prioritize_discovery_urls,
)
from .config.scope import ScopePolicy, ScopeViolationError


SECURITY_HEADER_HINTS = {
    "content-security-policy": "Missing Content-Security-Policy",
    "x-frame-options": "Missing X-Frame-Options",
    "x-content-type-options": "Missing X-Content-Type-Options",
    "strict-transport-security": "Missing Strict-Transport-Security for HTTPS response",
    "referrer-policy": "Missing Referrer-Policy",
    "permissions-policy": "Missing Permissions-Policy",
}


class ScopedHttpClient:
    def __init__(
        self,
        scope: ScopePolicy,
        artifacts: ArtifactStore,
        ignore_https_errors: bool,
        timeout: float = 15.0,
        max_requests: int = 200,
    ) -> None:
        self.scope = scope
        self.artifacts = artifacts
        self.max_requests = max_requests
        self.request_count = 0
        self.client = httpx.Client(
            timeout=timeout,
            verify=not ignore_https_errors,
            headers={"User-Agent": "AutoSongshu-Agent/0.1"},
            follow_redirects=False,
        )

    def close(self) -> None:
        self.client.close()

    def _guard_request_budget(self) -> None:
        if self.request_count >= self.max_requests:
            raise RuntimeError(f"HTTP request budget exhausted ({self.max_requests}).")

    def _log(self, record: dict[str, Any]) -> None:
        self.artifacts.append_jsonl("http-log.jsonl", record)

    def _send_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        form_body: dict[str, Any] | None = None,
        follow_redirects: bool = False,
    ) -> tuple[httpx.Response, list[dict[str, Any]], str]:
        self._guard_request_budget()
        target_url = self.scope.assert_in_scope(url)
        self.request_count += 1

        response = self.client.request(
            method.upper(),
            target_url,
            params=params,
            headers=headers,
            json=json_body,
            data=form_body,
            follow_redirects=False,
        )

        history: list[dict[str, Any]] = []
        if follow_redirects:
            response, history = self._follow_redirects(
                method, response, headers=headers
            )

        self._log(
            {
                "method": method.upper(),
                "url": target_url,
                "params": params,
                "headers": headers,
                "status_code": response.status_code,
                "history": history,
            },
        )
        return response, history, target_url

    def _serialize_response(
        self,
        response: httpx.Response,
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        body_preview = response.text[:8000]
        return {
            "url": str(response.url),
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "cookies": dict(response.cookies),
            "history": history or [],
            "body_preview": body_preview,
        }

    def _follow_redirects(
        self,
        method: str,
        response: httpx.Response,
        headers: dict[str, str] | None = None,
    ) -> tuple[httpx.Response, list[dict[str, Any]]]:
        history: list[dict[str, Any]] = []
        current_method = method.upper()
        current_response = response

        for _ in range(5):
            if current_response.status_code not in {301, 302, 303, 307, 308}:
                break

            location = current_response.headers.get("location")
            if not location:
                break

            next_url = urljoin(str(current_response.url), location)
            entry: dict[str, Any] = {
                "from": str(current_response.url),
                "status_code": current_response.status_code,
                "location": next_url,
            }

            try:
                self.scope.assert_in_scope(next_url)
            except ScopeViolationError as exc:
                entry["blocked"] = str(exc)
                history.append(entry)
                break

            next_method = (
                "GET" if current_response.status_code == 303 else current_method
            )
            current_response = self.client.request(
                next_method,
                next_url,
                headers=headers,
                follow_redirects=False,
            )
            history.append(entry)
            current_method = next_method

        return current_response, history

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        form_body: dict[str, Any] | None = None,
        follow_redirects: bool = False,
    ) -> dict[str, Any]:
        response, history, _target_url = self._send_request(
            method,
            url,
            params=params,
            headers=headers,
            json_body=json_body,
            form_body=form_body,
            follow_redirects=follow_redirects,
        )
        return self._serialize_response(response, history=history)

    def raw_request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        raw_body: str | None = None,
        content_type: str = "application/octet-stream",
        follow_redirects: bool = False,
    ) -> dict[str, Any]:
        """Send a request with a raw string body (no JSON serialization).

        The *raw_body* is transmitted byte-for-byte as provided, which
        prevents double-encoding of percent-encoded characters such as
        ``%0A``.  Use this when you need precise control over the exact
        bytes sent on the wire (e.g. testing WAF rules, exploiting CRLF
        injection, sending crafted payloads).
        """
        self._guard_request_budget()
        target_url = self.scope.assert_in_scope(url)
        self.request_count += 1

        req_headers = headers or {}
        if raw_body is not None and "content-type" not in {k.lower() for k in req_headers}:
            req_headers["content-type"] = content_type

        response = self.client.request(
            method.upper(),
            target_url,
            params=params,
            headers=req_headers,
            content=raw_body.encode("utf-8", errors="surrogateescape") if raw_body is not None else None,
            follow_redirects=False,
        )

        history: list[dict[str, Any]] = []
        if follow_redirects:
            response, history = self._follow_redirects(
                method, response, headers=req_headers
            )

        self._log(
            {
                "method": method.upper(),
                "url": target_url,
                "params": params,
                "headers": req_headers,
                "status_code": response.status_code,
                "history": history,
                "raw_body_length": len(raw_body) if raw_body else 0,
            },
        )
        return self._serialize_response(response, history=history)

    def discover_surface(
        self,
        url: str,
        *,
        max_pages: int = 6,
        max_candidates_per_page: int = 40,
        max_passive_files: int = 8,
    ) -> dict[str, Any]:
        if max_pages <= 0:
            raise ValueError("max_pages must be greater than 0.")
        if max_candidates_per_page <= 0:
            raise ValueError("max_candidates_per_page must be greater than 0.")
        if max_passive_files < 0:
            raise ValueError("max_passive_files must be 0 or greater.")

        start_url = self.scope.assert_in_scope(url or self.scope.start_url)
        parsed_start = urlparse(start_url)
        origin = f"{parsed_start.scheme}://{parsed_start.netloc}"

        queue: deque[str] = deque([start_url])
        queued = {start_url}
        seen_pages: set[str] = set()
        discovered_urls: set[str] = {start_url}
        api_hints: set[str] = set()
        page_summaries: list[dict[str, Any]] = []
        passive_files: list[dict[str, Any]] = []
        requests_before = self.request_count

        while queue and len(page_summaries) < max_pages:
            current = queue.popleft()
            queued.discard(current)
            if current in seen_pages:
                continue

            try:
                response, history, _requested_url = self._send_request(
                    "GET", current, follow_redirects=True
                )
            except Exception as exc:
                seen_pages.add(current)
                page_summaries.append(
                    {
                        "requested_url": current,
                        "ok": False,
                        "error": str(exc),
                    },
                )
                continue

            final_url = str(response.url)
            seen_pages.add(current)
            seen_pages.add(final_url)
            content_type = response.headers.get("content-type")
            body_text = response.text if _is_textual_response(response) else ""
            candidates = extract_in_scope_candidate_urls(
                body_text,
                base_url=final_url,
                scope=self.scope,
                max_candidates=max_candidates_per_page * 2,
            )
            prioritized_candidates = prioritize_discovery_urls(
                candidates,
                start_url=start_url,
                max_items=max_candidates_per_page,
            )
            discovered_urls.update(prioritized_candidates)
            api_hints.update(
                item for item in prioritized_candidates if is_api_like_url(item)
            )

            enqueued_urls: list[str] = []
            for candidate in prioritized_candidates:
                if not is_queueable_discovery_url(candidate):
                    continue
                if candidate in seen_pages or candidate in queued:
                    continue
                queue.append(candidate)
                queued.add(candidate)
                enqueued_urls.append(candidate)
                if len(enqueued_urls) >= min(8, max_candidates_per_page):
                    break

            page_summaries.append(
                {
                    "requested_url": current,
                    "url": final_url,
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "history": history,
                    "candidate_urls": prioritized_candidates[:10],
                    "enqueued_urls": enqueued_urls,
                },
            )

        for passive_path in COMMON_PASSIVE_DISCOVERY_PATHS[:max_passive_files]:
            requested_url = urljoin(f"{origin}/", passive_path.lstrip("/"))
            if requested_url in seen_pages:
                continue

            try:
                response, history, _requested_url = self._send_request(
                    "GET", requested_url, follow_redirects=True
                )
            except Exception as exc:
                passive_files.append(
                    {
                        "requested_url": requested_url,
                        "ok": False,
                        "error": str(exc),
                    },
                )
                continue

            final_url = str(response.url)
            seen_pages.add(requested_url)
            seen_pages.add(final_url)
            if response.status_code == 404:
                continue

            content_type = response.headers.get("content-type")
            body_text = response.text if _is_textual_response(response) else ""
            candidates = extract_in_scope_candidate_urls(
                body_text,
                base_url=final_url,
                scope=self.scope,
                max_candidates=max_candidates_per_page,
            )
            prioritized_candidates = prioritize_discovery_urls(
                candidates,
                start_url=start_url,
                max_items=10,
            )
            discovered_urls.update(prioritized_candidates)
            api_hints.update(
                item for item in prioritized_candidates if is_api_like_url(item)
            )

            passive_files.append(
                {
                    "requested_url": requested_url,
                    "url": final_url,
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "history": history,
                    "candidate_urls": prioritized_candidates,
                    "body_preview": body_text[:1000],
                },
            )

        prioritized_discovered = prioritize_discovery_urls(
            discovered_urls, start_url=start_url
        )
        high_value_urls = [
            item
            for item in prioritized_discovered
            if item != start_url
            and (is_api_like_url(item) or is_queueable_discovery_url(item))
        ][:25]

        return {
            "start_url": start_url,
            "origin": origin,
            "requests_used": self.request_count - requests_before,
            "visited_pages": page_summaries,
            "passive_files": passive_files,
            "discovered_urls": prioritized_discovered[:60],
            "high_value_urls": high_value_urls,
            "api_hints": prioritize_discovery_urls(
                api_hints, start_url=start_url, max_items=25
            ),
            "unvisited_candidates": [
                item for item in high_value_urls if item not in seen_pages
            ][:20],
        }

    def analyze_security_headers(self, url: str) -> dict[str, Any]:
        response = self.request("GET", url)
        headers = {key.lower(): value for key, value in response["headers"].items()}
        missing = []

        for header_name, hint in SECURITY_HEADER_HINTS.items():
            if header_name == "strict-transport-security" and not response[
                "url"
            ].startswith("https://"):
                continue
            if header_name not in headers:
                missing.append(hint)

        cookie_findings = []
        raw_set_cookie = response["headers"].get("set-cookie", "")
        if raw_set_cookie:
            cookie_line = raw_set_cookie.lower()
            if "httponly" not in cookie_line:
                cookie_findings.append("Set-Cookie missing HttpOnly")
            if response["url"].startswith("https://") and "secure" not in cookie_line:
                cookie_findings.append("Set-Cookie missing Secure")
            if "samesite" not in cookie_line:
                cookie_findings.append("Set-Cookie missing SameSite")

        return {
            "url": response["url"],
            "status_code": response["status_code"],
            "server": response["headers"].get("server"),
            "powered_by": response["headers"].get("x-powered-by"),
            "missing_headers": missing,
            "cookie_findings": cookie_findings,
            "history": response["history"],
        }

    def probe_reflection(
        self,
        url: str,
        parameter: str = "q",
        marker: str = "AUTOSONGSHU_REFLECT_12345",
    ) -> dict[str, Any]:
        response = self.request(
            "GET",
            url,
            params={parameter: marker},
        )
        reflected = marker in response["body_preview"]
        return {
            "url": response["url"],
            "parameter": parameter,
            "marker": marker,
            "reflected_in_preview": reflected,
            "status_code": response["status_code"],
        }


def _is_textual_response(response: httpx.Response) -> bool:
    content_type = (response.headers.get("content-type") or "").lower()
    return any(
        marker in content_type
        for marker in ("html", "json", "javascript", "text", "xml")
    )
