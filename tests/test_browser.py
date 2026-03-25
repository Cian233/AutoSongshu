from __future__ import annotations

import tempfile
import unittest

from autosongshu_agent.artifacts import ArtifactStore
from autosongshu_agent.browser import CDPBrowserSession
from autosongshu_agent.config import BrowserConfig
from autosongshu_agent.config import ScopePolicy


class _FakeCDPSession:
    def send(
        self, method: str, params: dict[str, object] | None = None
    ) -> dict[str, object]:
        if method == "Network.getRequestPostData":
            return {"postData": '{"username":"alice"}'}
        if method == "Network.getResponseBody":
            return {
                "body": 'function login(){return "/api/me";}',
                "base64Encoded": False,
            }
        raise AssertionError(f"Unexpected CDP method: {method} {params}")


class BrowserCDPRequestTests(unittest.TestCase):
    def _build_session(self) -> CDPBrowserSession:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        session = CDPBrowserSession(
            settings=BrowserConfig(),
            scope=ScopePolicy(
                start_url="https://app.example.internal/",
                allowed_hosts=["example.internal"],
                allow_subdomains=True,
            ),
            artifacts=ArtifactStore(temp_dir.name, "demo", "session"),
        )
        self.addCleanup(session.close)
        return session

    def test_cdp_request_details_include_post_data_and_response_body(self) -> None:
        session = self._build_session()
        session.cdp_session = _FakeCDPSession()  # type: ignore[assignment]

        session._on_cdp_request_will_be_sent(
            {
                "requestId": "req-1",
                "type": "XHR",
                "documentURL": "https://app.example.internal/login",
                "frameId": "frame-1",
                "loaderId": "loader-1",
                "initiator": {"type": "script"},
                "request": {
                    "url": "https://app.example.internal/api/login",
                    "method": "POST",
                    "headers": {"content-type": "application/json"},
                    "hasPostData": True,
                },
            },
        )
        session._on_cdp_request_extra_info(
            {
                "requestId": "req-1",
                "headers": {"cookie": "session=abc"},
                "associatedCookies": [{"cookie": {"name": "session"}}],
            },
        )
        session._on_cdp_response_received(
            {
                "requestId": "req-1",
                "type": "XHR",
                "response": {
                    "url": "https://app.example.internal/api/login",
                    "status": 200,
                    "statusText": "OK",
                    "headers": {"content-type": "application/json"},
                    "mimeType": "application/json",
                    "protocol": "h2",
                },
            },
        )
        session._on_cdp_response_extra_info(
            {
                "requestId": "req-1",
                "statusCode": 200,
                "headers": {"set-cookie": "session=abc; HttpOnly"},
            },
        )
        session._on_cdp_loading_finished(
            {"requestId": "req-1", "encodedDataLength": 128}
        )

        records = session._get_cdp_requests_impl(limit=None, body_chars=200)
        self.assertEqual(len(records), 1)

        record = records[0]
        self.assertEqual(record["resource_type"], "XHR")
        self.assertEqual(record["loading_status"], "finished")
        self.assertEqual(record["request"]["method"], "POST")
        self.assertEqual(record["request"]["post_data"], '{"username":"alice"}')
        self.assertEqual(record["response"]["status"], 200)
        self.assertEqual(record["response"]["mime_type"], "application/json")
        self.assertIn("function login()", record["response_body_preview"])
        self.assertEqual(record["response_body_capture"], "text")
        self.assertEqual(
            record["request_extra_info"]["headers"]["cookie"], "session=abc"
        )
        self.assertEqual(
            record["response_extra_info"]["headers"]["set-cookie"],
            "session=abc; HttpOnly",
        )

    def test_analyze_page_resources_merges_dom_performance_and_cdp_sources(
        self,
    ) -> None:
        session = self._build_session()

        session._collect_page_resource_inventory_impl = lambda **kwargs: {  # type: ignore[method-assign]
            "url": "https://app.example.internal/dashboard",
            "title": "Dashboard",
            "ready_state": "complete",
            "external_scripts": [
                {"src": "https://app.example.internal/static/app.js", "type": "module"},
            ],
            "inline_scripts": [
                {"preview": "window.__BOOTSTRAP__ = true;"},
            ],
            "stylesheets": [
                {
                    "href": "https://app.example.internal/static/app.css",
                    "rel": "stylesheet",
                },
            ],
            "inline_styles": [],
            "iframes": [],
            "manifests": [],
            "performance_resources": [
                {
                    "name": "https://app.example.internal/static/app.js",
                    "initiator_type": "script",
                    "duration_ms": 12.0,
                    "transfer_size": 2048,
                },
                {
                    "name": "https://app.example.internal/static/app.css",
                    "initiator_type": "link",
                    "duration_ms": 4.0,
                    "transfer_size": 512,
                },
            ],
            "navigation": {
                "name": "https://app.example.internal/dashboard",
                "type": "navigate",
                "duration_ms": 35.0,
                "transfer_size": 4096,
            },
        }
        session._get_cdp_requests_impl = (
            lambda limit=None, url_contains="", body_chars=4000: [  # type: ignore[method-assign]
                {
                    "request": {
                        "url": "https://app.example.internal/api/me",
                        "method": "GET",
                    },
                    "response": {
                        "status": 200,
                        "mime_type": "application/json",
                    },
                    "resource_type": "XHR",
                    "response_body_preview": '{"id":1,"role":"user"}',
                },
            ]
        )

        result = session._analyze_page_resources_impl(
            max_resources=20, max_inline_scripts=5, max_body_chars=200
        )

        self.assertEqual(result["url"], "https://app.example.internal/dashboard")
        self.assertEqual(result["summary"]["inline_script_count"], 1)
        self.assertEqual(result["summary"]["external_script_count"], 1)
        self.assertEqual(result["summary"]["stylesheet_count"], 1)

        resources_by_url = {item["url"]: item for item in result["loaded_resources"]}
        self.assertIn("https://app.example.internal/dashboard", resources_by_url)
        self.assertIn("https://app.example.internal/static/app.js", resources_by_url)
        self.assertIn("https://app.example.internal/static/app.css", resources_by_url)
        self.assertIn("https://app.example.internal/api/me", resources_by_url)

        app_js = resources_by_url["https://app.example.internal/static/app.js"]
        self.assertIn("dom", app_js["sources"])
        self.assertIn("performance", app_js["sources"])
        self.assertIn("script", app_js["dom_roles"])

        api_me = resources_by_url["https://app.example.internal/api/me"]
        self.assertIn("cdp", api_me["sources"])
        self.assertEqual(api_me["method"], "GET")
        self.assertEqual(api_me["status"], 200)
        self.assertIn('"role":"user"', api_me["response_body_preview"])


if __name__ == "__main__":
    unittest.main()
