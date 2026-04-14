from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from autosongshu_agent.agent.planner import (
    PentestPhase,
    SubTaskStatus,
    PlanStatus,
    SubTask,
    PentestPlan,
    PlannerAgent,
)
from autosongshu_agent.agent.sub_agent import (
    SubAgentRole,
    SubAgentProfile,
    SubAgentConfig,
    BaseSubAgent,
    get_role_profile,
    create_recon_agent,
    create_scanner_agent,
    create_exploit_agent,
    create_report_agent,
    _resolve_tool_groups,
    _RECON_SYSTEM_PROMPT,
    _SCANNER_SYSTEM_PROMPT,
    _EXPLOIT_SYSTEM_PROMPT,
    _REPORT_SYSTEM_PROMPT,
)
from autosongshu_agent.tool_impls.agent import spawn_agent


class PentestPhaseTests(unittest.TestCase):
    def test_phase_enum_values(self) -> None:
        self.assertEqual(PentestPhase.RECON.value, "recon")
        self.assertEqual(PentestPhase.SCANNING.value, "scanning")
        self.assertEqual(PentestPhase.EXPLOITATION.value, "exploitation")
        self.assertEqual(PentestPhase.REPORTING.value, "reporting")

    def test_phase_is_string_enum(self) -> None:
        self.assertEqual(PentestPhase.RECON, "recon")
        self.assertIn(PentestPhase.SCANNING, ["scanning", "other"])


class SubTaskStatusTests(unittest.TestCase):
    def test_status_enum_values(self) -> None:
        self.assertEqual(SubTaskStatus.PENDING.value, "pending")
        self.assertEqual(SubTaskStatus.IN_PROGRESS.value, "in_progress")
        self.assertEqual(SubTaskStatus.COMPLETED.value, "completed")
        self.assertEqual(SubTaskStatus.FAILED.value, "failed")
        self.assertEqual(SubTaskStatus.SKIPPED.value, "skipped")


class PlanStatusTests(unittest.TestCase):
    def test_status_enum_values(self) -> None:
        self.assertEqual(PlanStatus.DRAFT.value, "draft")
        self.assertEqual(PlanStatus.ACTIVE.value, "active")
        self.assertEqual(PlanStatus.COMPLETED.value, "completed")
        self.assertEqual(PlanStatus.FAILED.value, "failed")


class SubTaskTests(unittest.TestCase):
    def test_subtask_defaults(self) -> None:
        task = SubTask(
            id="abc123",
            name="Test task",
            phase=PentestPhase.RECON,
            description="A test task",
        )
        self.assertEqual(task.id, "abc123")
        self.assertIsNone(task.assigned_agent_id)
        self.assertEqual(task.status, SubTaskStatus.PENDING)
        self.assertIsNone(task.result)

    def test_subtask_with_all_fields(self) -> None:
        task = SubTask(
            id="def456",
            name="Exploit task",
            phase=PentestPhase.EXPLOITATION,
            description="Exploit SQLi",
            assigned_agent_id="agent-1",
            status=SubTaskStatus.COMPLETED,
            result="SQLi confirmed",
        )
        self.assertEqual(task.assigned_agent_id, "agent-1")
        self.assertEqual(task.status, SubTaskStatus.COMPLETED)
        self.assertEqual(task.result, "SQLi confirmed")


class PentestPlanTests(unittest.TestCase):
    def test_plan_defaults(self) -> None:
        plan = PentestPlan(target="https://example.test", phases=[])
        self.assertEqual(plan.target, "https://example.test")
        self.assertEqual(plan.phases, [])
        self.assertEqual(plan.subtasks, [])
        self.assertEqual(plan.status, PlanStatus.DRAFT)
        self.assertEqual(plan.metadata, {})

    def test_plan_with_phases(self) -> None:
        plan = PentestPlan(
            target="https://example.test",
            phases=[PentestPhase.RECON, PentestPhase.SCANNING],
            metadata={"scope": "full"},
        )
        self.assertEqual(len(plan.phases), 2)
        self.assertEqual(plan.metadata["scope"], "full")


class PlannerAgentTests(unittest.TestCase):
    def _make_planner(self) -> PlannerAgent:
        config = MagicMock()
        config.model.model_name = "gpt-4"
        config.model.api_key = "test-key"
        config.model.base_url = None
        config.model.temperature = 0.7
        config.model.top_p = 1.0
        config.model.max_tokens = None
        config.model.timeout = 60.0
        config.model.fallbacks = []
        config.engagement.name = "test-engagement"
        config.agent.max_iters = 20
        config.agent.enable_meta_tool = False
        config.agent.parallel_tool_calls = False
        config.agent.max_subtasks = 10
        config.skills.enabled = False
        config.skills.directories = []

        with patch("autosongshu_agent.agent.planner.PentestRuntime") as mock_runtime:
            mock_runtime_instance = MagicMock()
            mock_runtime.return_value = mock_runtime_instance
            mock_runtime_instance.artifacts.write_json = MagicMock()
            planner = PlannerAgent(config)
            return planner

    def test_planner_creation(self) -> None:
        planner = self._make_planner()
        self.assertIsNotNone(planner.config)
        self.assertIsNotNone(planner.runtime)
        self.assertIsNone(planner.current_plan)

    def test_analyze_target(self) -> None:
        planner = self._make_planner()
        analysis = planner.analyze_target("https://example.test")
        self.assertEqual(analysis["target"], "https://example.test")
        self.assertEqual(analysis["risk_level"], "unknown")
        self.assertIn(PentestPhase.RECON, analysis["phase_recommendations"])
        self.assertIn(PentestPhase.SCANNING, analysis["phase_recommendations"])
        self.assertIn(PentestPhase.EXPLOITATION, analysis["phase_recommendations"])
        self.assertIn(PentestPhase.REPORTING, analysis["phase_recommendations"])

    def test_generate_plan(self) -> None:
        planner = self._make_planner()
        plan = planner.generate_plan("https://example.test")
        self.assertEqual(plan.target, "https://example.test")
        self.assertEqual(plan.status, PlanStatus.DRAFT)
        self.assertEqual(len(plan.phases), 4)
        self.assertIs(planner.current_plan, plan)

    def test_generate_plan_with_specific_phases(self) -> None:
        planner = self._make_planner()
        plan = planner.generate_plan(
            "https://example.test",
            phases=[PentestPhase.RECON, PentestPhase.SCANNING],
        )
        self.assertEqual(len(plan.phases), 2)
        self.assertIn(PentestPhase.RECON, plan.phases)
        self.assertIn(PentestPhase.SCANNING, plan.phases)

    def test_generate_plan_with_metadata(self) -> None:
        planner = self._make_planner()
        plan = planner.generate_plan(
            "https://example.test",
            metadata={"scope": "full", "engagement_id": "eng-1"},
        )
        self.assertEqual(plan.metadata["scope"], "full")
        self.assertEqual(plan.metadata["engagement_id"], "eng-1")

    def test_decompose_to_subtasks_raises_without_plan(self) -> None:
        planner = self._make_planner()
        with self.assertRaises(RuntimeError):
            planner.decompose_to_subtasks()

    def test_decompose_to_subtasks_all_phases(self) -> None:
        planner = self._make_planner()
        planner.generate_plan("https://example.test")
        subtasks = planner.decompose_to_subtasks()
        self.assertEqual(len(subtasks), 12)
        recon_tasks = [st for st in subtasks if st.phase == PentestPhase.RECON]
        scanning_tasks = [st for st in subtasks if st.phase == PentestPhase.SCANNING]
        exploit_tasks = [st for st in subtasks if st.phase == PentestPhase.EXPLOITATION]
        report_tasks = [st for st in subtasks if st.phase == PentestPhase.REPORTING]
        self.assertEqual(len(recon_tasks), 3)
        self.assertEqual(len(scanning_tasks), 3)
        self.assertEqual(len(exploit_tasks), 3)
        self.assertEqual(len(report_tasks), 3)

    def test_decompose_to_subtasks_single_phase(self) -> None:
        planner = self._make_planner()
        planner.generate_plan("https://example.test")
        subtasks = planner.decompose_to_subtasks(plan=PentestPhase.RECON)
        self.assertEqual(len(subtasks), 3)
        self.assertTrue(all(st.phase == PentestPhase.RECON for st in subtasks))

    def test_dispatch_subtask_raises_without_plan(self) -> None:
        planner = self._make_planner()
        with self.assertRaises(RuntimeError):
            planner.dispatch_subtask("nonexistent")

    def test_dispatch_subtask_raises_for_unknown_id(self) -> None:
        planner = self._make_planner()
        planner.generate_plan("https://example.test")
        with self.assertRaises(ValueError):
            planner.dispatch_subtask("nonexistent-id")

    def test_dispatch_subtask(self) -> None:
        planner = self._make_planner()
        planner.generate_plan("https://example.test")
        subtasks = planner.decompose_to_subtasks()
        first_task = subtasks[0]
        dispatched = planner.dispatch_subtask(first_task.id, agent_id="agent-recon")
        self.assertEqual(dispatched.status, SubTaskStatus.IN_PROGRESS)
        self.assertEqual(dispatched.assigned_agent_id, "agent-recon")

    def test_dispatch_subtask_already_dispatched(self) -> None:
        planner = self._make_planner()
        planner.generate_plan("https://example.test")
        subtasks = planner.decompose_to_subtasks()
        first_task = subtasks[0]
        planner.dispatch_subtask(first_task.id, agent_id="agent-1")
        dispatched_again = planner.dispatch_subtask(first_task.id, agent_id="agent-2")
        self.assertEqual(dispatched_again.assigned_agent_id, "agent-1")

    def test_complete_subtask_raises_without_plan(self) -> None:
        planner = self._make_planner()
        with self.assertRaises(RuntimeError):
            planner.complete_subtask("nonexistent", result="done")

    def test_complete_subtask_success(self) -> None:
        planner = self._make_planner()
        planner.generate_plan("https://example.test")
        subtasks = planner.decompose_to_subtasks()
        first_task = subtasks[0]
        completed = planner.complete_subtask(first_task.id, result="Found 3 open ports", success=True)
        self.assertEqual(completed.status, SubTaskStatus.COMPLETED)
        self.assertEqual(completed.result, "Found 3 open ports")

    def test_complete_subtask_failure(self) -> None:
        planner = self._make_planner()
        planner.generate_plan("https://example.test")
        subtasks = planner.decompose_to_subtasks()
        first_task = subtasks[0]
        completed = planner.complete_subtask(first_task.id, result="Target unreachable", success=False)
        self.assertEqual(completed.status, SubTaskStatus.FAILED)
        self.assertEqual(completed.result, "Target unreachable")

    def test_get_plan_summary_without_plan(self) -> None:
        planner = self._make_planner()
        summary = planner.get_plan_summary()
        self.assertIn("error", summary)

    def test_get_plan_summary(self) -> None:
        planner = self._make_planner()
        planner.generate_plan("https://example.test")
        subtasks = planner.decompose_to_subtasks()
        planner.complete_subtask(subtasks[0].id, result="done")
        summary = planner.get_plan_summary()
        self.assertEqual(summary["target"], "https://example.test")
        self.assertEqual(summary["status"], PlanStatus.DRAFT.value)
        self.assertEqual(summary["total_subtasks"], 12)
        self.assertIn("recon", summary["phase_breakdown"])
        self.assertIn("completed", summary["status_breakdown"])


class SubAgentRoleTests(unittest.TestCase):
    def test_role_enum_values(self) -> None:
        self.assertEqual(SubAgentRole.RECON.value, "recon")
        self.assertEqual(SubAgentRole.SCANNER.value, "scanner")
        self.assertEqual(SubAgentRole.EXPLOIT.value, "exploit")
        self.assertEqual(SubAgentRole.REPORT.value, "report")


class SubAgentProfileTests(unittest.TestCase):
    def test_get_role_profile_recon(self) -> None:
        profile = get_role_profile(SubAgentRole.RECON)
        self.assertEqual(profile.role, SubAgentRole.RECON)
        self.assertEqual(profile.display_name, "ReconAgent")
        self.assertIn("http", profile.tool_group_names)
        self.assertIn("browser", profile.tool_group_names)
        self.assertIn("knowledge", profile.tool_group_names)

    def test_get_role_profile_scanner(self) -> None:
        profile = get_role_profile(SubAgentRole.SCANNER)
        self.assertEqual(profile.role, SubAgentRole.SCANNER)
        self.assertEqual(profile.display_name, "ScannerAgent")
        self.assertIn("sandbox", profile.tool_group_names)
        self.assertIn("skill-scripts", profile.tool_group_names)
        self.assertIn("findings", profile.tool_group_names)

    def test_get_role_profile_exploit(self) -> None:
        profile = get_role_profile(SubAgentRole.EXPLOIT)
        self.assertEqual(profile.role, SubAgentRole.EXPLOIT)
        self.assertEqual(profile.display_name, "ExploitAgent")
        self.assertIn("sandbox", profile.tool_group_names)
        self.assertIn("http", profile.tool_group_names)

    def test_get_role_profile_report(self) -> None:
        profile = get_role_profile(SubAgentRole.REPORT)
        self.assertEqual(profile.role, SubAgentRole.REPORT)
        self.assertEqual(profile.display_name, "ReportAgent")
        self.assertIn("findings", profile.tool_group_names)
        self.assertIn("knowledge", profile.tool_group_names)

    def test_all_profiles_have_system_prompt(self) -> None:
        for role in SubAgentRole:
            profile = get_role_profile(role)
            self.assertTrue(len(profile.system_prompt) > 0)

    def test_all_profiles_have_tool_groups(self) -> None:
        for role in SubAgentRole:
            profile = get_role_profile(role)
            self.assertTrue(len(profile.tool_group_names) > 0)


class ResolveToolGroupsTests(unittest.TestCase):
    def test_resolve_http_group(self) -> None:
        resolved = _resolve_tool_groups(["http"])
        self.assertIn("http-analysis", resolved)

    def test_resolve_browser_group(self) -> None:
        resolved = _resolve_tool_groups(["browser"])
        self.assertIn("browser-basic", resolved)
        self.assertIn("browser-interact", resolved)
        self.assertIn("browser-inspect", resolved)

    def test_resolve_knowledge_group(self) -> None:
        resolved = _resolve_tool_groups(["knowledge"])
        self.assertIn("knowledge-rag", resolved)

    def test_resolve_sandbox_group(self) -> None:
        resolved = _resolve_tool_groups(["sandbox"])
        self.assertIn("python-sandbox", resolved)

    def test_resolve_unknown_group(self) -> None:
        resolved = _resolve_tool_groups(["custom-group"])
        self.assertIn("custom-group", resolved)

    def test_resolve_multiple_groups_no_duplicates(self) -> None:
        resolved = _resolve_tool_groups(["http", "http"])
        self.assertEqual(resolved.count("http-analysis"), 1)


class SubAgentConfigTests(unittest.TestCase):
    def test_config_defaults(self) -> None:
        config = SubAgentConfig(role=SubAgentRole.RECON)
        self.assertEqual(config.role, SubAgentRole.RECON)
        self.assertEqual(config.model_profile, "")
        self.assertEqual(config.tool_groups, [])
        self.assertEqual(config.system_prompt_template, "")

    def test_config_with_custom_values(self) -> None:
        config = SubAgentConfig(
            role=SubAgentRole.EXPLOIT,
            model_profile="fast-model",
            tool_groups=["sandbox", "http"],
            system_prompt_template="Custom prompt",
        )
        self.assertEqual(config.model_profile, "fast-model")
        self.assertEqual(config.tool_groups, ["sandbox", "http"])
        self.assertEqual(config.system_prompt_template, "Custom prompt")


class BaseSubAgentTests(unittest.TestCase):
    def _make_sub_agent(self, role: SubAgentRole) -> BaseSubAgent:
        config = MagicMock()
        config.model.model_name = "gpt-4"
        config.model.api_key = "test-key"
        config.model.base_url = None
        config.model.temperature = 0.7
        config.model.top_p = 1.0
        config.model.max_tokens = None
        config.model.timeout = 60.0
        config.model.fallbacks = []
        config.agent.max_iters = 20
        config.agent.enable_meta_tool = False
        config.agent.parallel_tool_calls = False

        runtime = MagicMock()
        runtime.artifacts.session_dir = MagicMock()
        runtime.artifacts.session_dir.__truediv__ = MagicMock(return_value=MagicMock())

        sub_config = SubAgentConfig(role=role)
        return BaseSubAgent(config, runtime, sub_config)

    def test_sub_agent_config_stored(self) -> None:
        agent = self._make_sub_agent(SubAgentRole.RECON)
        self.assertEqual(agent.sub_config.role, SubAgentRole.RECON)

    def test_resolve_tool_groups_from_profile(self) -> None:
        agent = self._make_sub_agent(SubAgentRole.RECON)
        groups = agent._resolve_tool_groups()
        self.assertIn("http-analysis", groups)
        self.assertIn("browser-basic", groups)

    def test_resolve_tool_groups_from_config(self) -> None:
        config = MagicMock()
        config.model.model_name = "gpt-4"
        config.model.api_key = "test-key"
        config.model.base_url = None
        config.model.temperature = 0.7
        config.model.top_p = 1.0
        config.model.max_tokens = None
        config.model.timeout = 60.0
        config.model.fallbacks = []
        config.agent.max_iters = 20
        config.agent.enable_meta_tool = False
        config.agent.parallel_tool_calls = False

        runtime = MagicMock()
        runtime.artifacts.session_dir = MagicMock()
        runtime.artifacts.session_dir.__truediv__ = MagicMock(return_value=MagicMock())

        sub_config = SubAgentConfig(
            role=SubAgentRole.RECON,
            tool_groups=["http"],
        )
        agent = BaseSubAgent(config, runtime, sub_config)
        groups = agent._resolve_tool_groups()
        self.assertIn("http-analysis", groups)

    def test_build_system_prompt_from_profile(self) -> None:
        agent = self._make_sub_agent(SubAgentRole.SCANNER)
        prompt = agent._build_system_prompt()
        self.assertIn("扫描专家", prompt)

    def test_build_system_prompt_from_template(self) -> None:
        config = MagicMock()
        config.model.model_name = "gpt-4"
        config.model.api_key = "test-key"
        config.model.base_url = None
        config.model.temperature = 0.7
        config.model.top_p = 1.0
        config.model.max_tokens = None
        config.model.timeout = 60.0
        config.model.fallbacks = []
        config.agent.max_iters = 20
        config.agent.enable_meta_tool = False
        config.agent.parallel_tool_calls = False

        runtime = MagicMock()
        runtime.artifacts.session_dir = MagicMock()
        runtime.artifacts.session_dir.__truediv__ = MagicMock(return_value=MagicMock())

        sub_config = SubAgentConfig(
            role=SubAgentRole.RECON,
            system_prompt_template="Custom system prompt for testing",
        )
        agent = BaseSubAgent(config, runtime, sub_config)
        prompt = agent._build_system_prompt()
        self.assertEqual(prompt, "Custom system prompt for testing")


class SubAgentFactoryTests(unittest.TestCase):
    def _make_config(self) -> MagicMock:
        config = MagicMock()
        config.model.model_name = "gpt-4"
        config.model.api_key = "test-key"
        config.model.base_url = None
        config.model.temperature = 0.7
        config.model.top_p = 1.0
        config.model.max_tokens = None
        config.model.timeout = 60.0
        config.model.fallbacks = []
        config.agent.max_iters = 20
        config.agent.enable_meta_tool = False
        config.agent.parallel_tool_calls = False
        return config

    def _make_runtime(self) -> MagicMock:
        runtime = MagicMock()
        runtime.artifacts.session_dir = MagicMock()
        runtime.artifacts.session_dir.__truediv__ = MagicMock(return_value=MagicMock())
        return runtime

    def test_create_recon_agent(self) -> None:
        agent = create_recon_agent(self._make_config(), self._make_runtime())
        self.assertIsInstance(agent, BaseSubAgent)
        self.assertEqual(agent.sub_config.role, SubAgentRole.RECON)

    def test_create_scanner_agent(self) -> None:
        agent = create_scanner_agent(self._make_config(), self._make_runtime())
        self.assertIsInstance(agent, BaseSubAgent)
        self.assertEqual(agent.sub_config.role, SubAgentRole.SCANNER)

    def test_create_exploit_agent(self) -> None:
        agent = create_exploit_agent(self._make_config(), self._make_runtime())
        self.assertIsInstance(agent, BaseSubAgent)
        self.assertEqual(agent.sub_config.role, SubAgentRole.EXPLOIT)

    def test_create_report_agent(self) -> None:
        agent = create_report_agent(self._make_config(), self._make_runtime())
        self.assertIsInstance(agent, BaseSubAgent)
        self.assertEqual(agent.sub_config.role, SubAgentRole.REPORT)

    def test_create_agent_with_custom_model(self) -> None:
        agent = create_recon_agent(
            self._make_config(),
            self._make_runtime(),
            model_profile="fast-model",
        )
        self.assertEqual(agent.sub_config.model_profile, "fast-model")

    def test_create_agent_with_custom_prompt(self) -> None:
        agent = create_recon_agent(
            self._make_config(),
            self._make_runtime(),
            system_prompt_template="Custom recon prompt",
        )
        self.assertEqual(agent.sub_config.system_prompt_template, "Custom recon prompt")


class SpawnAgentToolTests(unittest.TestCase):
    def test_spawn_agent_creates_recon_agent(self) -> None:
        runtime = MagicMock()
        runtime.artifacts.path = MagicMock(return_value=MagicMock())
        runtime.artifacts.path.return_value.__truediv__ = MagicMock(return_value=MagicMock())
        runtime.artifacts.write_json = MagicMock()

        response = spawn_agent(
            runtime=runtime,
            description="Perform web reconnaissance",
            prompt="Scan the target for open ports and services",
            role="recon",
        )
        text = response.content[0]["text"]
        self.assertIn('"ok": true', text)
        self.assertIn("recon", text)
        self.assertIn("信息收集专家", text)

    def test_spawn_agent_creates_scanner_agent(self) -> None:
        runtime = MagicMock()
        runtime.artifacts.path = MagicMock(return_value=MagicMock())
        runtime.artifacts.path.return_value.__truediv__ = MagicMock(return_value=MagicMock())
        runtime.artifacts.write_json = MagicMock()

        response = spawn_agent(
            runtime=runtime,
            description="Scan for vulnerabilities",
            prompt="Run nmap and dirsearch",
            role="scanner",
        )
        text = response.content[0]["text"]
        self.assertIn("漏洞扫描专家", text)

    def test_spawn_agent_creates_exploit_agent(self) -> None:
        runtime = MagicMock()
        runtime.artifacts.path = MagicMock(return_value=MagicMock())
        runtime.artifacts.path.return_value.__truediv__ = MagicMock(return_value=MagicMock())
        runtime.artifacts.write_json = MagicMock()

        response = spawn_agent(
            runtime=runtime,
            description="Exploit SQL injection",
            prompt="Use sqlmap to exploit the identified SQLi",
            role="exploit",
        )
        text = response.content[0]["text"]
        self.assertIn("漏洞利用专家", text)

    def test_spawn_agent_creates_report_agent(self) -> None:
        runtime = MagicMock()
        runtime.artifacts.path = MagicMock(return_value=MagicMock())
        runtime.artifacts.path.return_value.__truediv__ = MagicMock(return_value=MagicMock())
        runtime.artifacts.write_json = MagicMock()

        response = spawn_agent(
            runtime=runtime,
            description="Generate final report",
            prompt="Compile all findings into a structured report",
            role="report",
        )
        text = response.content[0]["text"]
        self.assertIn("报告生成专家", text)

    def test_spawn_agent_defaults_to_general_role(self) -> None:
        runtime = MagicMock()
        runtime.artifacts.path = MagicMock(return_value=MagicMock())
        runtime.artifacts.path.return_value.__truediv__ = MagicMock(return_value=MagicMock())
        runtime.artifacts.write_json = MagicMock()

        response = spawn_agent(
            runtime=runtime,
            description="General task",
            prompt="Do something",
            role="invalid_role",
        )
        text = response.content[0]["text"]
        self.assertIn("通用专家", text)

    def test_spawn_agent_with_custom_name(self) -> None:
        runtime = MagicMock()
        runtime.artifacts.path = MagicMock(return_value=MagicMock())
        runtime.artifacts.path.return_value.__truediv__ = MagicMock(return_value=MagicMock())
        runtime.artifacts.write_json = MagicMock()

        response = spawn_agent(
            runtime=runtime,
            description="Named agent test",
            prompt="Test",
            name="my-custom-agent",
        )
        text = response.content[0]["text"]
        self.assertIn("my-custom-agent", text)

    def test_spawn_agent_stores_in_runtime_registry(self) -> None:
        runtime = MagicMock()
        runtime.artifacts.path = MagicMock(return_value=MagicMock())
        runtime.artifacts.path.return_value.__truediv__ = MagicMock(return_value=MagicMock())
        runtime.artifacts.write_json = MagicMock()
        runtime._agents = {}

        spawn_agent(
            runtime=runtime,
            description="Registry test",
            prompt="Test",
        )
        self.assertTrue(hasattr(runtime, "_agents"))
        self.assertGreater(len(runtime._agents), 0)


class SystemPromptTests(unittest.TestCase):
    def test_recon_prompt_content(self) -> None:
        self.assertIn("侦察专家", _RECON_SYSTEM_PROMPT)
        self.assertIn("HTTP", _RECON_SYSTEM_PROMPT)
        self.assertIn("浏览器", _RECON_SYSTEM_PROMPT)

    def test_scanner_prompt_content(self) -> None:
        self.assertIn("扫描专家", _SCANNER_SYSTEM_PROMPT)
        self.assertIn("沙箱", _SCANNER_SYSTEM_PROMPT)

    def test_exploit_prompt_content(self) -> None:
        self.assertIn("漏洞利用专家", _EXPLOIT_SYSTEM_PROMPT)
        self.assertIn("PoC", _EXPLOIT_SYSTEM_PROMPT)

    def test_report_prompt_content(self) -> None:
        self.assertIn("报告专家", _REPORT_SYSTEM_PROMPT)
        self.assertIn("安全评估报告", _REPORT_SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
