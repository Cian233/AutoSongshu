from __future__ import annotations

import json
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from autosongshu_agent.artifacts import ArtifactStore
from autosongshu_agent.config import SandboxConfig
from autosongshu_agent.sandbox import PythonSandbox, SandboxError
from autosongshu_agent.config import ScopePolicy
from autosongshu_agent.tools import register_default_tools


class _RecordingToolkit:
    def __init__(self) -> None:
        self.groups: dict[str, dict[str, object]] = {}
        self.registered: dict[str, object] = {}

    def create_tool_group(self, name: str, **kwargs: object) -> None:
        self.groups[name] = kwargs

    def register_tool_function(self, func, *, group_name: str) -> None:
        self.registered[func.__name__] = {"group_name": group_name, "func": func}


class _SandboxStub:
    def edit_file(self, **kwargs: object) -> dict[str, object]:
        return {"ok": True, "received": kwargs}

    def multiedit_file(self, **kwargs: object) -> dict[str, object]:
        return {"ok": True, "received": kwargs}


class SandboxEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.artifacts = ArtifactStore(
            str(root / "artifacts"), "demo", session_name="session"
        )
        self.sandbox = PythonSandbox(
            settings=SandboxConfig(shared_root_dir=str(root / "sandboxes")),
            scope=ScopePolicy("https://example.test", ["example.test"]),
            artifacts=self.artifacts,
            engagement_name="demo",
            authorization="AUTH-001",
        )

    def test_edit_file_replaces_unique_text_without_rewriting_whole_file(self) -> None:
        self.sandbox.write_file("payload.py", "print('v1')\n# keep\n")

        result = self.sandbox.edit_file(
            "payload.py",
            old_text="print('v1')",
            new_text="print('v2')",
        )

        self.assertTrue(result["changed"])
        self.assertEqual(result["edit_mode"], "replace_text")
        self.assertEqual(result["replaced_count"], 1)
        self.assertIn("-print('v1')", result["diff"])
        self.assertIn("+print('v2')", result["diff"])
        self.assertEqual(
            self.sandbox.read_file("payload.py")["content"],
            "print('v2')\n# keep\n",
        )

    def test_edit_file_rejects_ambiguous_text_matches(self) -> None:
        self.sandbox.write_file("payload.py", "token = 'x'\ntoken = 'x'\n")

        with self.assertRaises(SandboxError):
            self.sandbox.edit_file(
                "payload.py",
                old_text="token = 'x'",
                new_text="token = 'y'",
            )

    def test_edit_file_rejects_full_file_text_replacement(self) -> None:
        self.sandbox.write_file("payload.py", "print('v1')\n# keep\n")

        with self.assertRaises(SandboxError):
            self.sandbox.edit_file(
                "payload.py",
                old_text="print('v1')\n# keep\n",
                new_text="print('v2')\n# changed\n",
            )

    def test_write_file_rejects_markdown_fence_wrapped_code(self) -> None:
        with self.assertRaisesRegex(SandboxError, "Markdown code fences"):
            self.sandbox.write_file(
                "payload.py",
                "```python\nprint('hello')\n```",
            )

    def test_write_file_rejects_explanation_heavy_comment_dump(self) -> None:
        reasoning_block = "\n".join(
            [
                "# Core idea: explain the exploit path and compare several options in detail.",
                "# Step 1: describe why the previous attempt failed and what should happen next.",
                "# Step 2: evaluate another branch before touching the actual payload again.",
                "# Step 3: restate the assumptions, blockers, and observations in full sentences.",
                "# Step 4: reason about edge cases, retries, and alternative request shapes here.",
                "# Step 5: summarize the expected behavior before running the code below once more.",
                "# Step 6: continue narrating the plan instead of keeping the script itself concise.",
                "# Step 7: compare possible outcomes and explain what each result would imply.",
                "# Step 8: keep dumping analysis into comments instead of only the needed code.",
                "# Step 9: repeat the conclusion and the next action as more prose in comments.",
            ]
        )

        with self.assertRaisesRegex(SandboxError, "explanation-heavy comment block"):
            self.sandbox.write_file(
                "payload.py",
                "import requests\n\n"
                "def main():\n"
                f"{reasoning_block}\n"
                "    print('run')\n",
            )

    def test_write_file_allows_regular_code_with_brief_comments(self) -> None:
        result = self.sandbox.write_file(
            "payload.py",
            "# helper for the session check\n"
            "import requests\n\n"
            "def main():\n"
            "    print('ok')\n",
        )

        self.assertEqual(result["relative_path"], "payload.py")
        self.assertIn("print('ok')", self.sandbox.read_file("payload.py")["content"])

    def test_edit_file_can_replace_line_ranges(self) -> None:
        self.sandbox.write_file("payload.py", "line1\nline2\nline3\nline4\n")

        result = self.sandbox.edit_file(
            "payload.py",
            start_line=2,
            end_line=3,
            expected_old_text="line2\nline3\n",
            new_text="changed2\nchanged3\n",
        )

        self.assertTrue(result["changed"])
        self.assertEqual(result["edit_mode"], "replace_lines")
        self.assertEqual(result["replaced_count"], 2)
        self.assertEqual(
            self.sandbox.read_file("payload.py")["content"],
            "line1\nchanged2\nchanged3\nline4\n",
        )

    def test_multiedit_file_applies_ordered_precise_edits(self) -> None:
        self.sandbox.write_file("payload.py", "print('v1')\nvalue = 1\n# keep\n")

        result = self.sandbox.multiedit_file(
            "payload.py",
            edits=[
                {
                    "old_text": "print('v1')",
                    "new_text": "print('v2')",
                },
                {
                    "start_line": 2,
                    "end_line": 2,
                    "expected_old_text": "value = 1\n",
                    "new_text": "value = 2\n",
                },
            ],
        )

        self.assertTrue(result["changed"])
        self.assertEqual(result["edit_count"], 2)
        self.assertEqual(result["edits"][0]["edit_mode"], "replace_text")
        self.assertEqual(result["edits"][1]["edit_mode"], "replace_lines")
        self.assertEqual(
            self.sandbox.read_file("payload.py")["content"],
            "print('v2')\nvalue = 2\n# keep\n",
        )

    def test_read_file_can_return_line_numbered_slice(self) -> None:
        self.sandbox.write_file("payload.py", "line1\nline2\nline3\n")

        result = self.sandbox.read_file(
            "payload.py",
            start_line=2,
            end_line=3,
            include_line_numbers=True,
        )

        self.assertEqual(result["content"], "line2\nline3\n")
        self.assertEqual(result["selected_start_line"], 2)
        self.assertEqual(result["selected_end_line"], 3)
        self.assertIn("2: line2", result["numbered_content"])
        self.assertIn("3: line3", result["numbered_content"])

    def test_run_python_waits_for_pending_write_of_same_script_path(self) -> None:
        script_target = self.sandbox._resolve_workspace_path("exploit_final.py")
        write_finished = threading.Event()
        original_ensure_bootstrapped = self.sandbox._ensure_bootstrapped
        original_run_command = self.sandbox._run_command

        self.sandbox._ensure_bootstrapped = lambda: None

        def fake_run_command(
            command, *, timeout_sec, cwd=None, extra_env=None, input_text=None
        ):
            _ = (command, timeout_sec, cwd, extra_env, input_text)
            self.assertTrue(
                write_finished.is_set(),
                "run_python started before the pending file write completed",
            )
            return {
                "ok": True,
                "exit_code": 0,
                "stdout": "ready\n",
                "stderr": "",
                "duration_sec": 0.01,
                "command": list(command),
                "cwd": str(cwd or self.sandbox.workspace_dir),
                "timed_out": False,
            }

        self.sandbox._run_command = fake_run_command

        def delayed_write() -> None:
            update_key = self.sandbox._begin_workspace_update(script_target)
            try:
                time.sleep(0.2)
                with self.sandbox._lock:
                    script_target.parent.mkdir(parents=True, exist_ok=True)
                    script_target.write_text("print('ready')\n", encoding="utf-8")
            finally:
                write_finished.set()
                self.sandbox._finish_workspace_update(update_key)

        writer = threading.Thread(target=delayed_write)
        writer.start()
        try:
            result = self.sandbox.run_python(
                script_path="exploit_final.py", timeout_sec=5
            )
        finally:
            writer.join(timeout=2)
            self.sandbox._ensure_bootstrapped = original_ensure_bootstrapped
            self.sandbox._run_command = original_run_command

        self.assertTrue(result["ok"])
        self.assertEqual(result["relative_script_path"], "exploit_final.py")
        self.assertIn("ready", result["stdout"])

    def test_run_python_rejects_inline_markdown_fence_wrapped_code(self) -> None:
        with self.assertRaisesRegex(SandboxError, "Markdown code fences"):
            self.sandbox.run_python(code="```python\nprint('ready')\n```")

    def test_register_default_tools_exposes_sandbox_edit_file(self) -> None:
        toolkit = _RecordingToolkit()
        runtime = SimpleNamespace(
            config=SimpleNamespace(sandbox=SimpleNamespace(enabled=True)),
            sandbox=_SandboxStub(),
        )

        register_default_tools(toolkit, runtime)

        self.assertIn("sandbox_edit_file", toolkit.registered)
        tool_entry = toolkit.registered["sandbox_edit_file"]
        self.assertEqual(tool_entry["group_name"], "python-sandbox")
        response = tool_entry["func"](
            path="payload.py",
            old_text="old",
            new_text="new",
        )
        first = response.content[0]
        payload = json.loads(first["text"] if isinstance(first, dict) else first.text)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["received"]["path"], "payload.py")

    def test_register_default_tools_exposes_sandbox_multiedit_file(self) -> None:
        toolkit = _RecordingToolkit()
        runtime = SimpleNamespace(
            config=SimpleNamespace(sandbox=SimpleNamespace(enabled=True)),
            sandbox=_SandboxStub(),
        )

        register_default_tools(toolkit, runtime)

        self.assertIn("sandbox_multiedit_file", toolkit.registered)
        tool_entry = toolkit.registered["sandbox_multiedit_file"]
        self.assertEqual(tool_entry["group_name"], "python-sandbox")
        response = tool_entry["func"](
            path="payload.py",
            edits_json='[{"old_text": "old", "new_text": "new"}]',
        )
        first = response.content[0]
        payload = json.loads(first["text"] if isinstance(first, dict) else first.text)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["received"]["path"], "payload.py")
        self.assertEqual(payload["received"]["edits"][0]["old_text"], "old")


if __name__ == "__main__":
    unittest.main()
