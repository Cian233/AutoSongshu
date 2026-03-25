from __future__ import annotations

import unittest

from autosongshu_agent.message_blocks import (
    finalize_completed_assistant_content,
    merge_assistant_content,
    normalize_message_content,
    unresolved_tool_call_ids,
)


class MessageBlocksTests(unittest.TestCase):
    def test_merge_assistant_content_deduplicates_repeated_delta_blocks(self) -> None:
        existing = [
            {"type": "output_text", "text": "Check browser status."},
            {"type": "tool_call", "id": "tool:status:0", "name": "browser_status", "arguments": {}},
            {
                "type": "tool_result",
                "tool_call_id": "tool:status:0",
                "name": "browser_status",
                "content": [{"type": "output_text", "text": "connected"}],
            },
            {"type": "output_text", "text": "Browser is connected. Let me take a snapshot."},
            {"type": "tool_call", "id": "tool:snapshot:1", "name": "browser_snapshot", "arguments": {}},
        ]
        delta = [
            {"type": "output_text", "text": "Browser is connected. Let me take a snapshot."},
            {"type": "tool_call", "id": "tool:snapshot:1", "name": "browser_snapshot", "arguments": {}},
        ]

        merged = existing
        for _ in range(12):
            merged = merge_assistant_content(merged, delta)

        self.assertEqual(
            merged,
            [
                {"type": "output_text", "text": "Check browser status."},
                {"type": "tool_call", "id": "tool:status:0", "name": "browser_status", "arguments": {}},
                {
                    "type": "tool_result",
                    "tool_call_id": "tool:status:0",
                    "name": "browser_status",
                    "content": [{"type": "output_text", "text": "connected"}],
                },
                {"type": "output_text", "text": "Browser is connected. Let me take a snapshot."},
                {"type": "tool_call", "id": "tool:snapshot:1", "name": "browser_snapshot", "arguments": {}},
            ],
        )

    def test_merge_assistant_content_inserts_new_tool_parts_before_future_anchor(self) -> None:
        merged = merge_assistant_content(
            [
                {"type": "output_text", "text": "Inspect the page."},
                {"type": "output_text", "text": "Found login form."},
            ],
            [
                {"type": "tool_call", "id": "tool:html:1", "name": "browser_get_html", "arguments": {}},
                {
                    "type": "tool_result",
                    "tool_call_id": "tool:html:1",
                    "name": "browser_get_html",
                    "content": [{"type": "output_text", "text": "<form>...</form>"}],
                },
                {"type": "output_text", "text": "Found login form."},
            ],
        )

        self.assertEqual(
            merged,
            [
                {"type": "output_text", "text": "Inspect the page."},
                {"type": "tool_call", "id": "tool:html:1", "name": "browser_get_html", "arguments": {}},
                {
                    "type": "tool_result",
                    "tool_call_id": "tool:html:1",
                    "name": "browser_get_html",
                    "content": [{"type": "output_text", "text": "<form>...</form>"}],
                },
                {"type": "output_text", "text": "Found login form."},
            ],
        )

    def test_normalize_message_content_compacts_existing_duplicate_assistant_parts(self) -> None:
        normalized = normalize_message_content(
            [
                {"type": "output_text", "text": "Take snapshot."},
                {"type": "tool_call", "id": "tool:snapshot:1", "name": "browser_snapshot", "arguments": {}},
                {"type": "output_text", "text": "Take snapshot."},
                {"type": "tool_call", "id": "tool:snapshot:1", "name": "browser_snapshot", "arguments": {}},
            ],
            role="assistant",
        )

        self.assertEqual(
            normalized,
            [
                {"type": "output_text", "text": "Take snapshot."},
                {"type": "tool_call", "id": "tool:snapshot:1", "name": "browser_snapshot", "arguments": {}},
            ],
        )

    def test_finalize_completed_assistant_content_drops_unresolved_tool_calls(self) -> None:
        content = [
            {"type": "output_text", "text": "Trying another approach:"},
            {"type": "tool_call", "id": "tool:stale:1", "name": "sandbox_run_python", "arguments": {"code": "print(1)"}},
            {"type": "tool_call", "id": "tool:real:2", "name": "browser_snapshot", "arguments": {}},
            {
                "type": "tool_result",
                "tool_call_id": "tool:real:2",
                "name": "browser_snapshot",
                "content": [{"type": "output_text", "text": "ok"}],
            },
        ]

        finalized = finalize_completed_assistant_content(content)

        self.assertEqual(unresolved_tool_call_ids(finalized), [])
        self.assertEqual(
            finalized,
            [
                {"type": "output_text", "text": "Trying another approach:"},
                {"type": "tool_call", "id": "tool:real:2", "name": "browser_snapshot", "arguments": {}},
                {
                    "type": "tool_result",
                    "tool_call_id": "tool:real:2",
                    "name": "browser_snapshot",
                    "content": [{"type": "output_text", "text": "ok"}],
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
