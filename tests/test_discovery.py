from __future__ import annotations

import unittest

from autosongshu_agent.discovery import (
    extract_in_scope_candidate_urls,
    prioritize_discovery_urls,
)
from autosongshu_agent.config import ScopePolicy


class DiscoveryHelpersTests(unittest.TestCase):
    def test_extract_in_scope_candidate_urls_filters_to_scope(self) -> None:
        scope = ScopePolicy(
            start_url="https://app.example.internal/",
            allowed_hosts=["example.internal"],
            allow_subdomains=True,
        )
        text = """
        <a href="/login">Login</a>
        <script>
          fetch("/api/v1/users");
          axios.get("/admin/users");
          const graphql = { url: "/graphql" };
          const ignored = "https://outside.example.com/admin";
        </script>
        """

        candidates = extract_in_scope_candidate_urls(
            text,
            base_url="https://app.example.internal/",
            scope=scope,
            max_candidates=20,
        )

        self.assertIn("https://app.example.internal/login", candidates)
        self.assertIn("https://app.example.internal/api/v1/users", candidates)
        self.assertIn("https://app.example.internal/admin/users", candidates)
        self.assertIn("https://app.example.internal/graphql", candidates)
        self.assertNotIn("https://outside.example.com/admin", candidates)

    def test_prioritize_discovery_urls_prefers_api_and_admin_routes(self) -> None:
        prioritized = prioritize_discovery_urls(
            [
                "https://app.example.internal/static/app.js",
                "https://app.example.internal/login",
                "https://app.example.internal/api/v1/users",
                "https://app.example.internal/admin",
            ],
            start_url="https://app.example.internal/",
        )

        self.assertEqual(prioritized[0], "https://app.example.internal/api/v1/users")
        self.assertLess(
            prioritized.index("https://app.example.internal/admin"),
            prioritized.index("https://app.example.internal/static/app.js"),
        )


if __name__ == "__main__":
    unittest.main()
