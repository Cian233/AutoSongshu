from __future__ import annotations

import unittest

from autosongshu_agent.config import AppConfig, EngagementConfig, ModelConfig
from autosongshu_agent.prompts import build_system_prompt


class PromptCoverageTests(unittest.TestCase):
    def test_system_prompt_requires_resource_and_cdp_request_analysis(self) -> None:
        config = AppConfig(
            model=ModelConfig(model_name="gpt-4.1-mini", api_key="test-key"),
            engagement=EngagementConfig(
                name="demo",
                authorization="AUTH-001",
                start_url="https://app.example.internal/",
                allowed_hosts=["example.internal"],
            ),
        )

        prompt = build_system_prompt(config)

        self.assertIn("browser_analyze_page_resources", prompt)
        self.assertIn("browser_get_cdp_requests", prompt)
        self.assertIn("sandbox_edit_file", prompt)
        self.assertIn("sandbox_multiedit_file", prompt)
        self.assertIn("sandbox_read_file(include_line_numbers=True)", prompt)
        self.assertIn("raw file content only", prompt)
        self.assertIn("Never include markdown fences", prompt)
        self.assertIn("Code comments must stay sparse and technical", prompt)
        self.assertIn("loaded page resources and code", prompt)
        self.assertIn("full request details", prompt)


if __name__ == "__main__":
    unittest.main()
