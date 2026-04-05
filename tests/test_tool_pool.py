from __future__ import annotations

import unittest

from autosongshu_agent.tool_pool import (
    ToolGroupConfig,
    ToolPoolConfig,
    ToolPool,
    DEFAULT_TOOL_GROUPS,
    build_tool_pool,
)


class ToolGroupConfigTests(unittest.TestCase):
    def test_group_creation(self) -> None:
        group = ToolGroupConfig(
            name="test",
            description="Test group",
            tools=("tool1", "tool2"),
        )
        self.assertEqual(group.name, "test")
        self.assertEqual(len(group.tools), 2)
        self.assertTrue(group.enabled_by_default)

    def test_group_with_options(self) -> None:
        group = ToolGroupConfig(
            name="high_risk",
            description="High risk tools",
            tools=("dangerous_tool",),
            requires_approval=True,
            risk_level="high",
        )
        self.assertTrue(group.requires_approval)
        self.assertEqual(group.risk_level, "high")


class ToolPoolConfigTests(unittest.TestCase):
    def test_default_config(self) -> None:
        config = ToolPoolConfig.default()
        self.assertGreater(len(config.enabled_groups), 0)
        self.assertIn("browser", config.enabled_groups)

    def test_simple_config(self) -> None:
        config = ToolPoolConfig.simple()
        self.assertTrue(config.simple_mode)
        self.assertFalse(config.include_skills)
        self.assertFalse(config.include_sandbox)

    def test_readonly_config(self) -> None:
        config = ToolPoolConfig.readonly()
        self.assertIn("browser_click", config.disabled_tools)
        self.assertIn("sandbox_run_python", config.disabled_tools)


class ToolPoolTests(unittest.TestCase):
    def test_default_pool_has_all_groups(self) -> None:
        pool = ToolPool()
        for group in DEFAULT_TOOL_GROUPS:
            self.assertIn(group.name, pool.config.enabled_groups)

    def test_get_group_for_tool(self) -> None:
        pool = ToolPool()
        self.assertEqual(pool.get_group_for_tool("browser_navigate"), "browser")
        self.assertEqual(pool.get_group_for_tool("sandbox_run_python"), "sandbox")
        self.assertIsNone(pool.get_group_for_tool("nonexistent_tool"))

    def test_is_tool_enabled(self) -> None:
        pool = ToolPool()
        self.assertTrue(pool.is_tool_enabled("browser_navigate"))
        self.assertTrue(pool.is_tool_enabled("http_get"))

    def test_disable_tool(self) -> None:
        pool = ToolPool()
        self.assertTrue(pool.is_tool_enabled("browser_navigate"))
        pool.disable_tool("browser_navigate")
        self.assertFalse(pool.is_tool_enabled("browser_navigate"))

    def test_enable_tool(self) -> None:
        pool = ToolPool(
            config=ToolPoolConfig(
                enabled_groups={"browser"},
                disabled_tools={"browser_navigate"},
            )
        )
        self.assertFalse(pool.is_tool_enabled("browser_navigate"))
        pool.enable_tool("browser_navigate")
        self.assertTrue(pool.is_tool_enabled("browser_navigate"))

    def test_disable_group(self) -> None:
        pool = ToolPool()
        self.assertTrue(pool.is_tool_enabled("browser_navigate"))
        pool.disable_group("browser")
        self.assertFalse(pool.is_tool_enabled("browser_navigate"))
        self.assertFalse(pool.is_tool_enabled("browser_click"))

    def test_enable_group(self) -> None:
        pool = ToolPool(config=ToolPoolConfig(enabled_groups=set()))
        pool.enable_group("browser")
        self.assertTrue(pool.is_tool_enabled("browser_navigate"))

    def test_get_enabled_tools(self) -> None:
        pool = ToolPool()
        enabled = pool.get_enabled_tools()
        self.assertIn("browser_navigate", enabled)
        self.assertIn("http_get", enabled)

    def test_get_blocked_tools(self) -> None:
        pool = ToolPool()
        pool.disable_tool("browser_navigate")
        blocked = pool.get_blocked_tools()
        self.assertIn("browser_navigate", blocked)

    def test_simple_mode_excludes_sandbox_and_skills(self) -> None:
        pool = ToolPool(config=ToolPoolConfig.simple())
        self.assertFalse(pool.is_tool_enabled("sandbox_run_python"))
        self.assertFalse(pool.is_tool_enabled("run_skill_script"))

    def test_get_tools_requiring_approval(self) -> None:
        pool = ToolPool()
        approval_tools = pool.get_tools_requiring_approval()
        self.assertIn("sandbox_run_python", approval_tools)
        self.assertIn("run_skill_script", approval_tools)

    def test_as_summary_dict(self) -> None:
        pool = ToolPool()
        summary = pool.as_summary_dict()
        self.assertIn("enabled_count", summary)
        self.assertIn("blocked_count", summary)
        self.assertIn("enabled_groups", summary)

    def test_as_markdown(self) -> None:
        pool = ToolPool()
        md = pool.as_markdown()
        self.assertIn("# Tool Pool Configuration", md)
        self.assertIn("browser", md)


class BuildToolPoolTests(unittest.TestCase):
    def test_build_default_pool(self) -> None:
        pool = build_tool_pool()
        self.assertIsNotNone(pool)
        self.assertTrue(pool.is_tool_enabled("browser_navigate"))

    def test_build_simple_pool(self) -> None:
        pool = build_tool_pool(simple_mode=True)
        self.assertTrue(pool.config.simple_mode)
        self.assertFalse(pool.is_tool_enabled("sandbox_run_python"))

    def test_build_pool_with_disabled_tools(self) -> None:
        pool = build_tool_pool(disabled_tools=["browser_navigate"])
        self.assertFalse(pool.is_tool_enabled("browser_navigate"))

    def test_build_pool_without_sandbox(self) -> None:
        pool = build_tool_pool(include_sandbox=False)
        self.assertFalse(pool.is_tool_enabled("sandbox_run_python"))

    def test_build_pool_without_skills(self) -> None:
        pool = build_tool_pool(include_skills=False)
        self.assertFalse(pool.is_tool_enabled("run_skill_script"))


class DefaultToolGroupsTests(unittest.TestCase):
    def test_default_groups_exist(self) -> None:
        group_names = [g.name for g in DEFAULT_TOOL_GROUPS]
        self.assertIn("browser", group_names)
        self.assertIn("http", group_names)
        self.assertIn("sandbox", group_names)
        self.assertIn("skills", group_names)
        self.assertIn("findings", group_names)
        self.assertIn("knowledge", group_names)

    def test_sandbox_group_requires_approval(self) -> None:
        sandbox_group = next(g for g in DEFAULT_TOOL_GROUPS if g.name == "sandbox")
        self.assertTrue(sandbox_group.requires_approval)
        self.assertEqual(sandbox_group.risk_level, "high")

    def test_skills_group_requires_approval(self) -> None:
        skills_group = next(g for g in DEFAULT_TOOL_GROUPS if g.name == "skills")
        self.assertTrue(skills_group.requires_approval)


if __name__ == "__main__":
    unittest.main()
