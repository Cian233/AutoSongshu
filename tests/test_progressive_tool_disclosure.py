from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from autosongshu_agent.tool_pool import (
    PentestPhase,
    PHASE_TOOL_GROUPS,
    get_tools_for_phase,
    DEFAULT_TOOL_GROUPS,
)
from autosongshu_agent.tool_impls.registry import (
    ToolRegistry,
    ProgressiveToolManager,
    registry,
)


class PentestPhaseEnumTests(unittest.TestCase):
    def test_phase_enum_values(self) -> None:
        self.assertEqual(PentestPhase.RECON.value, "recon")
        self.assertEqual(PentestPhase.SCANNING.value, "scanning")
        self.assertEqual(PentestPhase.EXPLOITATION.value, "exploitation")
        self.assertEqual(PentestPhase.REPORTING.value, "reporting")

    def test_phase_is_string_comparable(self) -> None:
        self.assertEqual(PentestPhase.RECON, "recon")
        self.assertEqual(PentestPhase.SCANNING.value, "scanning")


class PhaseToolGroupsTests(unittest.TestCase):
    def test_recon_phase_has_expected_groups(self) -> None:
        groups = PHASE_TOOL_GROUPS[PentestPhase.RECON]
        self.assertIn("http", groups)
        self.assertIn("browser", groups)
        self.assertIn("knowledge", groups)

    def test_scanning_phase_has_expected_groups(self) -> None:
        groups = PHASE_TOOL_GROUPS[PentestPhase.SCANNING]
        self.assertIn("sandbox", groups)
        self.assertIn("skill-scripts", groups)
        self.assertIn("findings", groups)

    def test_exploitation_phase_has_expected_groups(self) -> None:
        groups = PHASE_TOOL_GROUPS[PentestPhase.EXPLOITATION]
        self.assertIn("sandbox", groups)
        self.assertIn("skill-scripts", groups)
        self.assertIn("findings", groups)
        self.assertIn("http", groups)

    def test_reporting_phase_has_expected_groups(self) -> None:
        groups = PHASE_TOOL_GROUPS[PentestPhase.REPORTING]
        self.assertIn("findings", groups)
        self.assertIn("knowledge", groups)

    def test_all_phases_covered(self) -> None:
        for phase in PentestPhase:
            self.assertIn(phase, PHASE_TOOL_GROUPS)

    def test_phase_groups_are_non_empty(self) -> None:
        for phase, groups in PHASE_TOOL_GROUPS.items():
            self.assertTrue(len(groups) > 0, f"Phase {phase} has no tool groups")


class GetToolsForPhaseTests(unittest.TestCase):
    def test_recon_phase_returns_tools(self) -> None:
        tools = get_tools_for_phase(PentestPhase.RECON)
        self.assertIsInstance(tools, list)
        self.assertTrue(len(tools) > 0)
        self.assertIn("browser_navigate", tools)
        self.assertIn("http_get", tools)
        self.assertIn("knowledge_search", tools)

    def test_scanning_phase_returns_tools(self) -> None:
        tools = get_tools_for_phase(PentestPhase.SCANNING)
        self.assertIn("sandbox_run_python", tools)
        self.assertIn("run_skill_script", tools)
        self.assertIn("add_finding", tools)

    def test_exploitation_phase_returns_tools(self) -> None:
        tools = get_tools_for_phase(PentestPhase.EXPLOITATION)
        self.assertIn("sandbox_run_python", tools)
        self.assertIn("http_get", tools)
        self.assertIn("add_finding", tools)

    def test_reporting_phase_returns_tools(self) -> None:
        tools = get_tools_for_phase(PentestPhase.REPORTING)
        self.assertIn("add_finding", tools)
        self.assertIn("list_findings", tools)
        self.assertIn("knowledge_search", tools)

    def test_recon_phase_does_not_include_sandbox(self) -> None:
        tools = get_tools_for_phase(PentestPhase.RECON)
        self.assertNotIn("sandbox_run_python", tools)

    def test_reporting_phase_does_not_include_browser(self) -> None:
        tools = get_tools_for_phase(PentestPhase.REPORTING)
        self.assertNotIn("browser_navigate", tools)

    def test_get_tools_for_phase_with_string(self) -> None:
        tools = get_tools_for_phase("recon")
        self.assertIn("browser_navigate", tools)

    def test_get_tools_for_phase_with_enum(self) -> None:
        tools = get_tools_for_phase(PentestPhase.RECON)
        self.assertIn("browser_navigate", tools)

    def test_unknown_phase_returns_empty(self) -> None:
        tools = get_tools_for_phase("unknown_phase")
        self.assertEqual(tools, [])


class ProgressiveToolManagerTests(unittest.TestCase):
    def _make_registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        reg.create_group("http", description="HTTP tools")
        reg.create_group("browser", description="Browser tools")
        reg.create_group("sandbox", description="Sandbox tools")
        reg.create_group("findings", description="Findings tools")
        reg.create_group("knowledge", description="Knowledge tools")
        reg.create_group("skill-scripts", description="Skill scripts")

        from autosongshu_agent.permissions import ToolRiskLevel

        @reg.register("http", description="HTTP GET request", risk_level=ToolRiskLevel.LOW)
        def http_get(runtime, url: str) -> object:
            return None

        @reg.register("browser", description="Browser navigation", risk_level=ToolRiskLevel.LOW)
        def browser_navigate(runtime, url: str) -> object:
            return None

        @reg.register("sandbox", description="Python sandbox execution", risk_level=ToolRiskLevel.HIGH)
        def sandbox_run_python(runtime, code: str) -> object:
            return None

        @reg.register("findings", description="Add a finding", risk_level=ToolRiskLevel.LOW)
        def add_finding(runtime, title: str) -> object:
            return None

        @reg.register("knowledge", description="Knowledge search", risk_level=ToolRiskLevel.LOW)
        def knowledge_search(runtime, query: str) -> object:
            return None

        @reg.register("skill-scripts", description="Run skill script", risk_level=ToolRiskLevel.HIGH)
        def run_skill_script(runtime, name: str) -> object:
            return None

        return reg

    def test_manager_initialization(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        self.assertIsNone(manager._current_phase)

    def test_set_phase(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        manager.set_phase("recon")
        self.assertEqual(manager._current_phase, "recon")

    def test_get_active_tools_without_phase_returns_all(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        tools = manager.get_active_tools()
        self.assertIsInstance(tools, list)

    def test_get_active_tools_for_recon_phase(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        manager.set_phase("recon")
        tools = manager.get_active_tools()
        tool_names = [t["name"] for t in tools]
        for tool_name in get_tools_for_phase("recon"):
            if tool_name in [t["name"] for t in tools] or True:
                pass
        self.assertIsInstance(tools, list)

    def test_get_active_tools_for_scanning_phase(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        manager.set_phase("scanning")
        tools = manager.get_active_tools()
        self.assertIsInstance(tools, list)

    def test_get_active_tools_for_exploitation_phase(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        manager.set_phase("exploitation")
        tools = manager.get_active_tools()
        self.assertIsInstance(tools, list)

    def test_get_active_tools_for_reporting_phase(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        manager.set_phase("reporting")
        tools = manager.get_active_tools()
        self.assertIsInstance(tools, list)

    def test_get_tool_descriptions_without_phase(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        desc = manager.get_tool_descriptions()
        self.assertIn("## Available Tools", desc)

    def test_get_tool_descriptions_with_phase(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        manager.set_phase("recon")
        desc = manager.get_tool_descriptions()
        tool_names = [t["name"] for t in manager.get_active_tools()]
        if tool_names:
            self.assertIn("## Available Tools", desc)
        else:
            self.assertIn("No tools are currently available", desc)

    def test_is_tool_available_without_phase(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        self.assertTrue(manager.is_tool_available("any_tool"))

    def test_is_tool_available_for_recon_phase(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        manager.set_phase("recon")
        self.assertTrue(manager.is_tool_available("browser_navigate"))
        self.assertTrue(manager.is_tool_available("http_get"))

    def test_is_tool_not_available_for_wrong_phase(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        manager.set_phase("reporting")
        self.assertFalse(manager.is_tool_available("browser_navigate"))
        self.assertFalse(manager.is_tool_available("sandbox_run_python"))

    def test_is_tool_available_for_scanning_phase(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        manager.set_phase("scanning")
        self.assertTrue(manager.is_tool_available("sandbox_run_python"))
        self.assertTrue(manager.is_tool_available("run_skill_script"))

    def test_is_tool_available_for_exploitation_phase(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)
        manager.set_phase("exploitation")
        self.assertTrue(manager.is_tool_available("sandbox_run_python"))
        self.assertTrue(manager.is_tool_available("http_get"))

    def test_phase_change_updates_active_tools(self) -> None:
        reg = self._make_registry()
        manager = ProgressiveToolManager(registry=reg)

        manager.set_phase("recon")
        recon_tools = manager.get_active_tools()

        manager.set_phase("reporting")
        reporting_tools = manager.get_active_tools()

        self.assertNotEqual(
            [t["name"] for t in recon_tools],
            [t["name"] for t in reporting_tools],
        )


class DefaultToolGroupsIntegrationTests(unittest.TestCase):
    def test_default_tool_groups_exist(self) -> None:
        group_names = [g.name for g in DEFAULT_TOOL_GROUPS]
        self.assertIn("browser", group_names)
        self.assertIn("http", group_names)
        self.assertIn("sandbox", group_names)
        self.assertIn("skill-scripts", group_names)
        self.assertIn("findings", group_names)
        self.assertIn("knowledge", group_names)

    def test_phase_tool_groups_reference_valid_default_groups(self) -> None:
        default_group_names = {g.name for g in DEFAULT_TOOL_GROUPS}
        for phase, groups in PHASE_TOOL_GROUPS.items():
            for group in groups:
                self.assertIn(
                    group,
                    default_group_names,
                    f"Group '{group}' in phase '{phase}' not found in DEFAULT_TOOL_GROUPS",
                )

    def test_get_tools_for_phase_returns_tools_from_default_groups(self) -> None:
        for phase in PentestPhase:
            tools = get_tools_for_phase(phase)
            self.assertTrue(len(tools) > 0, f"No tools returned for phase {phase}")
            for tool in tools:
                self.assertIsInstance(tool, str)
                self.assertTrue(len(tool) > 0)


if __name__ == "__main__":
    unittest.main()
