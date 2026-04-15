from __future__ import annotations

import gc
import warnings
import unittest

from autosongshu_agent.agent.utils import (
    _StreamLoopGuard,
    _make_agentscope_output_safe,
    _parse_skill_command,
    _prepare_user_message,
    _should_force_tool_continuation,
)
from autosongshu_agent.utils import _should_track_loop_guard_tool
from autosongshu_agent.skills import (
    LoadedSkill,
    SkillLoadEvent,
    SkillLoadReport,
    SkillScript,
)


class _DummyAgent:
    def __init__(self) -> None:
        self._disable_console_output = False


class _DummyInterruptibleAgent:
    def __init__(self) -> None:
        self._disable_console_output = False

    async def _acting(self, tool_call: str) -> str:
        return tool_call


def _event(*blocks: dict[str, object]) -> dict[str, object]:
    return {"blocks": list(blocks)}


class AgentOutputSafetyTests(unittest.TestCase):
    def test_make_agentscope_output_safe_disables_console_output(self) -> None:
        agent = _DummyAgent()

        returned = _make_agentscope_output_safe(agent)

        self.assertIs(returned, agent)
        self.assertTrue(agent._disable_console_output)


class AgentInterruptCoroutineSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrapped_acting_remains_awaitable(self) -> None:
        agent = _make_agentscope_output_safe(_DummyInterruptibleAgent())
        result = await agent._acting("tool:ok")
        self.assertEqual(result, "tool:ok")

    async def test_dropped_unawaited_acting_coroutines_are_closed(self) -> None:
        agent = _make_agentscope_output_safe(_DummyInterruptibleAgent())

        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always", RuntimeWarning)
            pending = [agent._acting("tool:1"), agent._acting("tool:2")]
            first = pending.pop(0)
            second = pending.pop(0)

            self.assertEqual(await first, "tool:1")
            del second
            del pending
            gc.collect()

        unawaited_warnings = [
            warning
            for warning in captured
            if "was never awaited" in str(warning.message)
        ]
        self.assertFalse(unawaited_warnings)

    def test_force_tool_continuation_for_tool_only_blocks_without_summary(self) -> None:
        self.assertTrue(
            _should_force_tool_continuation(
                "",
                blocks=[
                    {
                        "type": "tool_result",
                        "tool_call_id": "tool:1",
                        "name": "browser_navigate",
                        "content": [{"type": "output_text", "text": "HTTP 200"}],
                    },
                ],
            ),
        )

    def test_force_tool_continuation_for_synthetic_tool_summary_without_real_output(
        self,
    ) -> None:
        self.assertTrue(
            _should_force_tool_continuation(
                "This turn executed 1 tool calls: browser_status",
                blocks=[
                    {
                        "type": "tool_result",
                        "tool_call_id": "tool:1",
                        "name": "browser_status",
                        "content": [{"type": "output_json", "value": {"ok": True}}],
                    },
                ],
            ),
        )

    def test_force_tool_continuation_for_unresolved_tool_call_blocks(self) -> None:
        self.assertTrue(
            _should_force_tool_continuation(
                "Trying another approach.",
                blocks=[
                    {
                        "type": "tool_use",
                        "id": "tool:1",
                        "name": "sandbox_run_python",
                        "input": {"code": "print(1)"},
                    },
                ],
            ),
        )

    def test_force_tool_continuation_when_python_script_is_written_but_not_run(
        self,
    ) -> None:
        self.assertTrue(
            _should_force_tool_continuation(
                "Script saved to exploit_final.py.",
                blocks=[
                    {
                        "type": "tool_use",
                        "id": "tool:1",
                        "name": "sandbox_write_file",
                        "input": {
                            "path": "exploit_final.py",
                            "content": "print('ready')\n",
                        },
                    },
                    {
                        "type": "tool_result",
                        "tool_call_id": "tool:1",
                        "name": "sandbox_write_file",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"relative_path": "exploit_final.py"}',
                            }
                        ],
                    },
                ],
            ),
        )

    def test_no_forced_continuation_when_written_python_script_is_run_in_same_turn(
        self,
    ) -> None:
        self.assertFalse(
            _should_force_tool_continuation(
                "Script updated and executed successfully.",
                blocks=[
                    {
                        "type": "tool_use",
                        "id": "tool:1",
                        "name": "sandbox_edit_file",
                        "input": {
                            "path": "exploit_final.py",
                            "old_text": "print('v1')",
                            "new_text": "print('v2')",
                        },
                    },
                    {
                        "type": "tool_result",
                        "tool_call_id": "tool:1",
                        "name": "sandbox_edit_file",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"relative_path": "exploit_final.py"}',
                            }
                        ],
                    },
                    {
                        "type": "tool_use",
                        "id": "tool:2",
                        "name": "sandbox_run_python",
                        "input": {"script_path": "exploit_final.py"},
                    },
                    {
                        "type": "tool_result",
                        "tool_call_id": "tool:2",
                        "name": "sandbox_run_python",
                        "content": [{"type": "output_text", "text": '{"ok": true}'}],
                    },
                    {
                        "type": "text",
                        "text": "Script updated and executed successfully.",
                    },
                ],
            ),
        )

    def test_no_forced_continuation_for_completed_summary(self) -> None:
        self.assertFalse(
            _should_force_tool_continuation("Task completed with confirmed results.")
        )

    def test_loop_guard_ignores_meta_tools(self) -> None:
        self.assertFalse(_should_track_loop_guard_tool("create_plan"))
        self.assertFalse(_should_track_loop_guard_tool("update_subtask_state"))
        self.assertTrue(_should_track_loop_guard_tool("browser_navigate"))

    def test_stream_loop_guard_triggers_after_repeated_identical_branch_then_stalled_output(
        self,
    ) -> None:
        guard = _StreamLoopGuard()

        first = [
            {
                "type": "tool_use",
                "id": "tool:1",
                "name": "browser_navigate",
                "input": {"url": "https://example.test"},
            },
            {
                "type": "tool_result",
                "tool_call_id": "tool:1",
                "name": "browser_navigate",
                "content": [{"type": "output_text", "text": "HTTP 200"}],
            },
        ]
        second = first + [
            {
                "type": "tool_use",
                "id": "tool:2",
                "name": "browser_navigate",
                "input": {"url": "https://example.test"},
            },
            {
                "type": "tool_result",
                "tool_call_id": "tool:2",
                "name": "browser_navigate",
                "content": [{"type": "output_text", "text": "HTTP 200"}],
            },
        ]

        self.assertIsNone(guard.observe(_event(*first)))
        self.assertIsNone(guard.observe(_event(*second)))
        reason = guard.observe(
            _event(*second, {"type": "text", "text": "Trying another approach."})
        )

        self.assertIsNotNone(reason)

    def test_stream_loop_guard_resets_when_new_evidence_appears(self) -> None:
        guard = _StreamLoopGuard()

        first = [
            {
                "type": "tool_use",
                "id": "tool:1",
                "name": "browser_navigate",
                "input": {"url": "https://example.test"},
            },
            {
                "type": "tool_result",
                "tool_call_id": "tool:1",
                "name": "browser_navigate",
                "content": [{"type": "output_text", "text": "HTTP 200"}],
            },
        ]
        second = first + [
            {
                "type": "tool_use",
                "id": "tool:2",
                "name": "browser_navigate",
                "input": {"url": "https://example.test"},
            },
            {
                "type": "tool_result",
                "tool_call_id": "tool:2",
                "name": "browser_navigate",
                "content": [{"type": "output_text", "text": "HTTP 200"}],
            },
        ]
        fresh = second + [
            {
                "type": "tool_use",
                "id": "tool:3",
                "name": "browser_navigate",
                "input": {"url": "https://example.test/admin"},
            },
            {
                "type": "tool_result",
                "tool_call_id": "tool:3",
                "name": "browser_navigate",
                "content": [
                    {"type": "output_text", "text": "HTTP 403 admin panel discovered"}
                ],
            },
        ]

        self.assertIsNone(guard.observe(_event(*first)))
        self.assertIsNone(guard.observe(_event(*second)))
        self.assertIsNone(guard.observe(_event(*fresh)))
        self.assertIsNone(
            guard.observe(
                _event(
                    *fresh,
                    {
                        "type": "text",
                        "text": "Found a new response body and status change.",
                    },
                )
            )
        )

    def test_stream_loop_guard_does_not_trigger_for_repeated_tool_calls_without_results(
        self,
    ) -> None:
        guard = _StreamLoopGuard()

        first = [
            {
                "type": "tool_use",
                "id": "tool:1",
                "name": "browser_navigate",
                "input": {"url": "https://example.test"},
            },
        ]
        second = first + [
            {
                "type": "tool_use",
                "id": "tool:2",
                "name": "browser_navigate",
                "input": {"url": "https://example.test"},
            },
        ]

        self.assertIsNone(guard.observe(_event(*first)))
        self.assertIsNone(guard.observe(_event(*second)))
        self.assertIsNone(
            guard.observe(
                _event(
                    *second, {"type": "text", "text": "Still waiting for a response."}
                )
            )
        )

    def test_parse_skill_command_extracts_requested_names_and_remaining_message(
        self,
    ) -> None:
        command = _parse_skill_command(
            "/skill recon-web, graphql-recon\nInvestigate the login flow"
        )

        self.assertEqual(command.requested_names, ["recon-web", "graphql-recon"])
        self.assertEqual(command.remaining_message, "Investigate the login flow")

    def test_prepare_user_message_injects_explicit_skill_prompt(self) -> None:
        report = SkillLoadReport(
            configured_directories=[],
            manual_available=[
                LoadedSkill(
                    name="recon-web",
                    description="First-pass reconnaissance workflow.",
                    directory="E:/skills/recon-web",
                    source_directory="E:/skills",
                    body="# Recon Web",
                    activation_mode="manual",
                ),
            ],
        )

        prepared = _prepare_user_message(
            "/skill recon-web\nAssess the application entry flow", report
        )

        self.assertIn("Assess the application entry flow", prepared)
        self.assertIn("Available local skills in this session", prepared)
        self.assertIn("recon-web [manual; notes-only]", prepared)
        self.assertIn("Skill: recon-web", prepared)

    def test_prepare_user_message_notes_when_requested_skill_is_unavailable(
        self,
    ) -> None:
        report = SkillLoadReport(
            configured_directories=[],
            skipped=[
                SkillLoadEvent(
                    status="skipped",
                    path="E:/skills/recon-web",
                    name="recon-web",
                    reason="Sandbox support is disabled for this run.",
                ),
            ],
        )

        prepared = _prepare_user_message("/skill recon-web", report)

        self.assertIn("not available", prepared)
        self.assertIn("recon-web", prepared)
        self.assertIn("Sandbox support is disabled", prepared)

    def test_prepare_user_message_prefers_loaded_scripted_skills_before_sandbox(
        self,
    ) -> None:
        report = SkillLoadReport(
            configured_directories=[],
            loaded=[
                LoadedSkill(
                    name="sqlmap-sqli",
                    description="Scoped SQL injection verification.",
                    directory="E:/skills/sqlmap-sqli",
                    source_directory="E:/skills",
                    body="# Sqlmap SQLi",
                    activation_mode="auto",
                    scripts=[
                        SkillScript(
                            name="sqlmap_scan.py",
                            relative_path="scripts/sqlmap_scan.py",
                            absolute_path="E:/skills/sqlmap-sqli/scripts/sqlmap_scan.py",
                            runner="python",
                        ),
                    ],
                ),
            ],
        )

        prepared = _prepare_user_message(
            "Verify this likely SQL injection sink", report
        )

        self.assertIn("Available local skills in this session", prepared)
        self.assertIn("sqlmap-sqli [auto; scripted]", prepared)
        self.assertIn("prefer inspecting and running that packaged workflow", prepared)
        self.assertIn(
            "SQL injection verification tasks: prefer the packaged `sqlmap-sqli` workflow.",
            prepared,
        )


if __name__ == "__main__":
    unittest.main()
