from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from unittest.mock import patch

from autosongshu_agent.agent.builder import _AgentBuilderMixin
from autosongshu_agent.config import (
    AppConfig,
    EngagementConfig,
    ModelConfig,
    load_config,
)
from autosongshu_agent.model_router import ModelRouter, parse_profiles_from_config


class _Builder(_AgentBuilderMixin):
    pass


class ModelSamplingConfigTests(unittest.TestCase):
    def test_load_config_reads_sampling_overrides_from_env_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                dedent(
                    """
                    model:
                      model_name: gpt-4.1-mini
                      api_key: test-key

                    engagement:
                      start_url: https://example.test/
                    """
                ).strip(),
                encoding="utf-8",
            )
            (root / ".env").write_text(
                "\n".join(
                    [
                        "AUTOSONGSHU_MODEL_TEMPERATURE=1.0",
                        "AUTOSONGSHU_MODEL_TOP_P=0.95",
                    ],
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = load_config(config_path)

        self.assertEqual(config.model.temperature, 1.0)
        self.assertEqual(config.model.top_p, 0.95)

    def test_load_config_reads_nested_overrides_from_env_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                dedent(
                    """
                    model:
                      model_name: gpt-4.1-mini
                      api_key: test-key

                    browser:
                      mode: launch
                      headless: true

                    engagement:
                      name: yaml-engagement
                      authorization: YAML-001
                      start_url: https://yaml.example.test/
                      allowed_hosts:
                        - yaml.example.test
                      allow_subdomains: true
                      max_requests: 200

                    skills:
                      enabled: true
                      directories:
                        - ./skills

                    sandbox:
                      enabled: true
                      allow_package_install: true
                    """
                ).strip(),
                encoding="utf-8",
            )
            (root / ".env").write_text(
                "\n".join(
                    [
                        "AUTOSONGSHU_BROWSER_MODE=connect_over_cdp",
                        "AUTOSONGSHU_BROWSER_CDP_URL=http://127.0.0.1:9222",
                        "AUTOSONGSHU_BROWSER_HEADLESS=false",
                        "AUTOSONGSHU_SCOPE_START_URL=https://env.example.test/",
                        'AUTOSONGSHU_SCOPE_ALLOWED_HOSTS=["env.example.test","app.env.example.test"]',
                        "AUTOSONGSHU_SCOPE_ALLOW_SUBDOMAINS=false",
                        "AUTOSONGSHU_SKILLS_DIRECTORIES=./skills,./extra-skills",
                        "AUTOSONGSHU_AGENT_MAX_ITERS=21",
                        "AUTOSONGSHU_COMPACTION_AUTO=false",
                        "AUTOSONGSHU_SANDBOX_BOOTSTRAP_PACKAGES=requests,httpx,rich",
                    ],
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = load_config(config_path)

        self.assertEqual(config.browser.mode, "connect_over_cdp")
        self.assertEqual(config.browser.cdp_url, "http://127.0.0.1:9222")
        self.assertFalse(config.browser.headless)
        self.assertEqual(config.engagement.start_url, "https://env.example.test/")
        self.assertEqual(
            config.engagement.allowed_hosts,
            ["env.example.test", "app.env.example.test"],
        )
        self.assertFalse(config.engagement.allow_subdomains)
        self.assertEqual(
            config.skills.directories,
            [str((root / "skills").resolve()), str((root / "extra-skills").resolve())],
        )
        self.assertEqual(config.agent.max_iters, 21)
        self.assertFalse(config.compaction.auto)
        self.assertEqual(
            config.sandbox.bootstrap_packages, ["requests", "httpx", "rich"]
        )

    def test_load_config_reads_token_compaction_overrides_from_env_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "config.yaml"
            config_path.write_text(
                dedent(
                    """
                    model:
                      model_name: gpt-4.1-mini
                      api_key: test-key

                    engagement:
                      start_url: https://example.test/
                    """
                ).strip(),
                encoding="utf-8",
            )
            (root / ".env").write_text(
                "\n".join(
                    [
                        "AUTOSONGSHU_COMPACTION_USE_TOKEN_COUNTING=true",
                        "AUTOSONGSHU_COMPACTION_CONTEXT_WINDOW_TOKENS=64000",
                        "AUTOSONGSHU_COMPACTION_RESERVED_TOKENS=6000",
                        "AUTOSONGSHU_COMPACTION_COMPACT_AFTER_TOKENS=42000",
                    ],
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = load_config(config_path)

        self.assertTrue(config.compaction.use_token_counting)
        self.assertEqual(config.compaction.context_window_tokens, 64000)
        self.assertEqual(config.compaction.reserved_tokens, 6000)
        self.assertEqual(config.compaction.compact_after_tokens, 42000)

    def test_build_model_passes_sampling_parameters(self) -> None:
        builder = _Builder()
        builder.config = AppConfig(
            model=ModelConfig(
                model_name="glm-5",
                api_key="test-key",
                temperature=1.0,
                top_p=0.95,
            ),
            engagement=EngagementConfig(
                start_url="https://example.test/",
            ),
        )

        with patch("autosongshu_agent.agent.builder.OpenAIChatModel") as chat_model:
            builder._build_model()

        self.assertEqual(
            chat_model.call_args.kwargs["generate_kwargs"],
            {
                "temperature": 1.0,
                "top_p": 0.95,
            },
        )

    def test_build_memory_model_preserves_sampling_parameters(self) -> None:
        builder = _Builder()
        builder.config = AppConfig(
            model=ModelConfig(
                model_name="glm-5",
                api_key="test-key",
                temperature=1.0,
                top_p=0.95,
            ),
            engagement=EngagementConfig(
                start_url="https://example.test/",
            ),
        )

        with patch("autosongshu_agent.agent.builder.OpenAIChatModel") as chat_model:
            builder._build_memory_model()

        self.assertEqual(
            chat_model.call_args.kwargs["generate_kwargs"],
            {
                "temperature": 0.2,
                "top_p": 0.95,
            },
        )

    def test_parse_profiles_keeps_pydantic_profile_names(self) -> None:
        model_config = ModelConfig(
            model_name="legacy-model",
            api_key="legacy-key",
            profiles=[
                {
                    "name": "primary",
                    "provider": "openai",
                    "model_name": "gpt-4o",
                    "tasks": ["general", "reasoning"],
                },
                {
                    "name": "fallback",
                    "provider": "dashscope",
                    "model_name": "qwen3.6-plus",
                    "tasks": ["search"],
                },
            ],
        )

        profiles = parse_profiles_from_config(model_config)

        self.assertEqual([p.name for p in profiles], ["primary", "fallback"])
        self.assertEqual(profiles[0].provider.value, "openai")
        self.assertEqual(profiles[1].provider.value, "dashscope")
        self.assertIn("reasoning", [task.value for task in profiles[0].tasks])
        self.assertIn("search", [task.value for task in profiles[1].tasks])

    def test_router_keeps_multiple_profiles_from_pydantic_config(self) -> None:
        model_config = ModelConfig(
            model_name="legacy-model",
            api_key="legacy-key",
            active="secondary",
            profiles=[
                {
                    "name": "primary",
                    "provider": "openai",
                    "model_name": "gpt-4o",
                    "tasks": ["general"],
                },
                {
                    "name": "secondary",
                    "provider": "deepseek",
                    "model_name": "deepseek-chat",
                    "tasks": ["general"],
                },
            ],
        )

        router = ModelRouter(
            profiles=parse_profiles_from_config(model_config),
            default_profile_name=model_config.active,
        )

        listed = router.list_profiles()
        self.assertEqual(len(listed), 2)
        self.assertEqual({item["name"] for item in listed}, {"primary", "secondary"})
        active = [item for item in listed if item.get("is_active")]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["name"], "secondary")


if __name__ == "__main__":
    unittest.main()
