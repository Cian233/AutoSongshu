from __future__ import annotations

import unittest

from autosongshu_agent.router import (
    RoutedMatch,
    CommandEntry,
    ToolEntry,
    SkillEntry,
    PromptRouter,
    DEFAULT_COMMANDS,
    DEFAULT_TOOLS,
    build_router_from_skill_registry,
)


class CommandEntryTests(unittest.TestCase):
    def test_matches_name(self) -> None:
        cmd = CommandEntry(name="/help", description="Show help")
        self.assertTrue(cmd.matches_token("help"))
        self.assertTrue(cmd.matches_token("HELP"))

    def test_matches_description(self) -> None:
        cmd = CommandEntry(name="/stats", description="Show token usage")
        self.assertTrue(cmd.matches_token("token"))
        self.assertTrue(cmd.matches_token("usage"))

    def test_matches_aliases(self) -> None:
        cmd = CommandEntry(name="/help", description="Help", aliases=("?", "h"))
        self.assertTrue(cmd.matches_token("?"))
        self.assertTrue(cmd.matches_token("h"))

    def test_no_match(self) -> None:
        cmd = CommandEntry(name="/help", description="Show help")
        self.assertFalse(cmd.matches_token("xyz"))


class ToolEntryTests(unittest.TestCase):
    def test_matches_name(self) -> None:
        tool = ToolEntry(name="http_get", description="HTTP GET")
        self.assertTrue(tool.matches_token("http"))
        self.assertTrue(tool.matches_token("get"))

    def test_matches_group(self) -> None:
        tool = ToolEntry(name="test", description="Test", group="browser")
        self.assertTrue(tool.matches_token("browser"))

    def test_no_match(self) -> None:
        tool = ToolEntry(name="http_get", description="HTTP GET")
        self.assertFalse(tool.matches_token("sandbox"))


class SkillEntryTests(unittest.TestCase):
    def test_matches_name(self) -> None:
        skill = SkillEntry(name="nmap-scan", description="Run nmap")
        self.assertTrue(skill.matches_token("nmap"))
        self.assertTrue(skill.matches_token("scan"))

    def test_matches_tags(self) -> None:
        skill = SkillEntry(name="tool", description="Test", tags=("recon", "network"))
        self.assertTrue(skill.matches_token("recon"))
        self.assertTrue(skill.matches_token("network"))


class PromptRouterTests(unittest.TestCase):
    def test_default_router_has_commands_and_tools(self) -> None:
        router = PromptRouter()
        self.assertGreater(len(router.commands), 0)
        self.assertGreater(len(router.tools), 0)

    def test_tokenize_prompt(self) -> None:
        router = PromptRouter()
        tokens = router.tokenize_prompt("Run nmap scan on target")
        self.assertIn("run", tokens)
        self.assertIn("nmap", tokens)
        self.assertIn("scan", tokens)
        self.assertIn("target", tokens)

    def test_tokenize_prompt_removes_slashes(self) -> None:
        router = PromptRouter()
        tokens = router.tokenize_prompt("/help me")
        self.assertIn("help", tokens)
        self.assertIn("me", tokens)
        self.assertNotIn("/help", tokens)

    def test_route_returns_matches(self) -> None:
        router = PromptRouter()
        matches = router.route("help")
        self.assertGreater(len(matches), 0)
        help_match = next((m for m in matches if m.name == "/help"), None)
        self.assertIsNotNone(help_match)
        self.assertEqual(help_match.kind, "command")

    def test_route_limits_results(self) -> None:
        router = PromptRouter()
        matches = router.route("http browser sandbox", limit=3)
        self.assertLessEqual(len(matches), 3)

    def test_route_empty_prompt(self) -> None:
        router = PromptRouter()
        matches = router.route("")
        self.assertEqual(len(matches), 0)

    def test_is_command(self) -> None:
        router = PromptRouter()
        self.assertTrue(router.is_command("/help"))
        self.assertTrue(router.is_command("  /stats  "))
        self.assertFalse(router.is_command("help me"))
        self.assertFalse(router.is_command(""))

    def test_parse_command(self) -> None:
        router = PromptRouter()
        result = router.parse_command("/stats tokens")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "/stats")
        self.assertEqual(result[1], "tokens")

    def test_parse_command_no_args(self) -> None:
        router = PromptRouter()
        result = router.parse_command("/help")
        self.assertIsNotNone(result)
        self.assertEqual(result[0], "/help")
        self.assertEqual(result[1], "")

    def test_parse_command_not_command(self) -> None:
        router = PromptRouter()
        result = router.parse_command("help me")
        self.assertIsNone(result)

    def test_suggest_commands(self) -> None:
        router = PromptRouter()
        suggestions = router.suggest_commands("hel")
        self.assertGreater(len(suggestions), 0)
        for cmd in suggestions:
            self.assertIn("hel", cmd.name.lower())

    def test_suggest_commands_empty_prefix(self) -> None:
        router = PromptRouter()
        suggestions = router.suggest_commands("")
        self.assertGreater(len(suggestions), 0)

    def test_suggest_tools(self) -> None:
        router = PromptRouter()
        suggestions = router.suggest_tools("http")
        self.assertGreater(len(suggestions), 0)
        for tool in suggestions:
            self.assertTrue(
                "http" in tool.name.lower() or "http" in tool.description.lower()
            )

    def test_register_skill(self) -> None:
        router = PromptRouter()
        skill = SkillEntry(name="custom-scan", description="Custom scanner")
        router.register_skill(skill)
        self.assertIn(skill, router.skills)

    def test_register_command(self) -> None:
        router = PromptRouter()
        cmd = CommandEntry(name="/custom", description="Custom command")
        router.register_command(cmd)
        self.assertIn(cmd, router.commands)

    def test_register_tool(self) -> None:
        router = PromptRouter()
        tool = ToolEntry(name="custom_tool", description="Custom tool")
        router.register_tool(tool)
        self.assertIn(tool, router.tools)

    def test_route_with_skills(self) -> None:
        router = PromptRouter()
        skill = SkillEntry(
            name="nmap-recon", description="Nmap scanner", tags=("recon", "network")
        )
        router.register_skill(skill)
        matches = router.route("nmap recon")
        skill_match = next((m for m in matches if m.kind == "skill"), None)
        self.assertIsNotNone(skill_match)

    def test_summary_dict(self) -> None:
        router = PromptRouter()
        summary = router.summary_dict()
        self.assertIn("commands", summary)
        self.assertIn("tools", summary)
        self.assertIn("skills", summary)
        self.assertGreater(summary["commands"], 0)
        self.assertGreater(summary["tools"], 0)


class BuildRouterFromSkillRegistryTests(unittest.TestCase):
    def test_build_router_empty_registry(self) -> None:
        registry = type("Registry", (), {"loaded": []})()
        router = build_router_from_skill_registry(registry)
        self.assertEqual(len(router.skills), 0)

    def test_build_router_with_skills(self) -> None:
        skill_info = type(
            "SkillInfo",
            (),
            {
                "name": "nmap-recon",
                "description": "Run nmap",
                "path": "/skills/nmap",
                "tags": ["recon"],
            },
        )()
        registry = type("Registry", (), {"loaded": [skill_info]})()
        router = build_router_from_skill_registry(registry)
        self.assertEqual(len(router.skills), 1)
        self.assertEqual(router.skills[0].name, "nmap-recon")


if __name__ == "__main__":
    unittest.main()
