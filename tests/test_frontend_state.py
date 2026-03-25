from __future__ import annotations

import shutil
import subprocess
import textwrap
import unittest
from pathlib import Path


_HAS_NODE = shutil.which("node") is not None
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(_HAS_NODE, "frontend state tests require node")
class FrontendStateTests(unittest.TestCase):
    def test_tool_call_render_signature_changes_when_code_arguments_stream(self) -> None:
        script = textwrap.dedent(
            """
            import { upsertMessage } from "./src/autosongshu_agent/web/static/state.js";

            const detail = { messages: [] };
            const first = {
              id: "m1",
              role: "assistant",
              status: "in_progress",
              updated_at: "2026-03-15T12:00:00",
              order_index: 1,
              content: [
                {
                  type: "tool_call",
                  id: "tool:1",
                  name: "sandbox_write_file",
                  arguments: { path: "demo.py", content: "print(1)" },
                },
              ],
            };
            const second = {
              ...first,
              content: [
                {
                  type: "tool_call",
                  id: "tool:1",
                  name: "sandbox_write_file",
                  arguments: { path: "demo.py", content: "print(123456789)\\nprint(2)" },
                },
              ],
            };

            const afterFirst = upsertMessage(detail, first);
            const afterSecond = upsertMessage(afterFirst, second);

            if (afterFirst.messages[0].render_signature === afterSecond.messages[0].render_signature) {
              throw new Error("render signature did not change for streamed code arguments");
            }
            """
        ).strip()

        completed = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        if completed.returncode != 0:
            self.fail(completed.stderr or completed.stdout or "node frontend signature check failed")


if __name__ == "__main__":
    unittest.main()
