from __future__ import annotations

import tempfile
import unittest

import httpx

from autosongshu_agent.artifacts import ArtifactStore
from autosongshu_agent.http_client import ScopedHttpClient
from autosongshu_agent.config import ScopePolicy


class ScopedHttpClientDiscoveryTests(unittest.TestCase):
    def test_discover_surface_collects_shallow_and_passive_recon(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            client = ScopedHttpClient(
                scope=ScopePolicy(
                    start_url="https://app.example.internal/",
                    allowed_hosts=["example.internal"],
                    allow_subdomains=True,
                ),
                artifacts=ArtifactStore(temp_dir, "demo", "session"),
                ignore_https_errors=True,
                timeout=5.0,
                max_requests=50,
            )
            responses = {
                "https://app.example.internal/": (
                    200,
                    {"content-type": "text/html; charset=utf-8"},
                    """
                    <a href="/login">Login</a>
                    <a href="/docs">Docs</a>
                    <script>
                      fetch("/api/v1/users");
                      const route = { url: "/graphql" };
                    </script>
                    """,
                ),
                "https://app.example.internal/login": (
                    200,
                    {"content-type": "text/html; charset=utf-8"},
                    """
                    <form action="/auth/login" method="post"></form>
                    <a href="/dashboard">Dashboard</a>
                    """,
                ),
                "https://app.example.internal/docs": (
                    200,
                    {"content-type": "text/html; charset=utf-8"},
                    """
                    <a href="/openapi.json">OpenAPI</a>
                    <a href="/admin">Admin</a>
                    """,
                ),
                "https://app.example.internal/robots.txt": (
                    200,
                    {"content-type": "text/plain"},
                    "Allow: /admin\nSitemap: https://app.example.internal/sitemap.xml\n",
                ),
                "https://app.example.internal/sitemap.xml": (
                    200,
                    {"content-type": "application/xml"},
                    """
                    <urlset>
                      <url><loc>https://app.example.internal/admin</loc></url>
                      <url><loc>https://app.example.internal/search</loc></url>
                    </urlset>
                    """,
                ),
                "https://app.example.internal/sitemap_index.xml": (
                    404,
                    {"content-type": "application/xml"},
                    "",
                ),
                "https://app.example.internal/.well-known/security.txt": (
                    404,
                    {"content-type": "text/plain"},
                    "",
                ),
                "https://app.example.internal/manifest.json": (
                    200,
                    {"content-type": "application/json"},
                    '{"start_url":"/dashboard"}',
                ),
                "https://app.example.internal/manifest.webmanifest": (
                    404,
                    {"content-type": "application/json"},
                    "",
                ),
                "https://app.example.internal/openapi.json": (
                    200,
                    {"content-type": "application/json"},
                    '{"openapi":"3.0.0","servers":[{"url":"https://app.example.internal/api"}]}',
                ),
                "https://app.example.internal/swagger.json": (
                    404,
                    {"content-type": "application/json"},
                    "",
                ),
            }

            def fake_request(method: str, url: str, **kwargs: object) -> httpx.Response:
                normalized_url = str(url)
                if normalized_url not in responses:
                    raise AssertionError(f"Unexpected request: {normalized_url}")
                status_code, headers, body = responses[normalized_url]
                return httpx.Response(
                    status_code,
                    headers=headers,
                    text=body,
                    request=httpx.Request(method, normalized_url),
                )

            client.client.request = fake_request  # type: ignore[method-assign]
            try:
                result = client.discover_surface(
                    "https://app.example.internal/",
                    max_pages=3,
                    max_candidates_per_page=20,
                    max_passive_files=8,
                )
            finally:
                client.close()

        self.assertEqual(result["start_url"], "https://app.example.internal/")
        self.assertGreaterEqual(result["requests_used"], 6)
        self.assertIn("https://app.example.internal/login", result["high_value_urls"])
        self.assertIn("https://app.example.internal/admin", result["high_value_urls"])
        self.assertIn("https://app.example.internal/api/v1/users", result["api_hints"])
        self.assertIn("https://app.example.internal/graphql", result["api_hints"])
        self.assertIn("https://app.example.internal/search", result["discovered_urls"])

        passive_requested_urls = {
            item["requested_url"]
            for item in result["passive_files"]
            if item.get("ok", True)
        }
        self.assertIn("https://app.example.internal/robots.txt", passive_requested_urls)
        self.assertIn(
            "https://app.example.internal/sitemap.xml", passive_requested_urls
        )
        self.assertIn(
            "https://app.example.internal/manifest.json", passive_requested_urls
        )


if __name__ == "__main__":
    unittest.main()
