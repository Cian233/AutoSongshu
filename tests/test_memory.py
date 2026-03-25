from __future__ import annotations

import unittest
from types import SimpleNamespace

from autosongshu_agent.memory import (
    LayeredConversationMemory,
    MemoryNote,
    SessionHandoffCard,
    build_memory_fallback,
    build_memory_transcript_payload,
    completed_messages_after_anchor,
    sync_validated_findings,
)
from autosongshu_agent.models import Finding


class MemoryTests(unittest.TestCase):
    def test_sync_validated_findings_filters_candidates(self) -> None:
        notes = sync_validated_findings(
            [
                Finding(
                    title="SQL injection",
                    severity="high",
                    summary="Confirmed UNION-based injection.",
                    url="https://example.test/search",
                    evidence=["Payload succeeded"],
                    status="validated",
                ),
                Finding(
                    title="Open redirect",
                    severity="medium",
                    summary="Needs more verification.",
                    status="candidate",
                ),
            ],
        )

        self.assertEqual(len(notes), 1)
        self.assertIn("SQL injection", notes[0].statement)
        self.assertNotIn("Open redirect", notes[0].statement)
        self.assertIn("URL: https://example.test/search", notes[0].evidence)

    def test_completed_messages_after_anchor_skips_old_and_pending_messages(self) -> None:
        messages = [
            SimpleNamespace(id="u1", status="completed"),
            SimpleNamespace(id="a1", status="completed"),
            SimpleNamespace(id="u2", status="completed"),
            SimpleNamespace(id="a2", status="completed"),
            SimpleNamespace(id="a3", status="in_progress"),
        ]

        pending = completed_messages_after_anchor(messages, "a1", skip_message_ids={"u2"})

        self.assertEqual([message.id for message in pending], ["a2"])

    def test_build_memory_transcript_payload_includes_tool_activity_digest(self) -> None:
        message = SimpleNamespace(
            id="a1",
            role="assistant",
            status="completed",
            content=[
                {"type": "tool_call", "id": "tool:1", "name": "sandbox_run_python", "arguments": {"code": "print(1)"}},
                {"type": "tool_call", "id": "tool:2", "name": "sandbox_run_python", "arguments": {"code": "print(1)"}},
                {
                    "type": "tool_result",
                    "tool_call_id": "tool:1",
                    "name": "sandbox_run_python",
                    "content": [{"type": "output_text", "text": "ok"}],
                },
                {
                    "type": "tool_result",
                    "tool_call_id": "tool:2",
                    "name": "sandbox_run_python",
                    "content": [{"type": "output_text", "text": "ok"}],
                },
                {"type": "output_text", "text": "Still blocked."},
            ],
        )

        payload = build_memory_transcript_payload([message])

        self.assertEqual(payload[0]["id"], "a1")
        self.assertEqual(payload[0]["text"], "Still blocked.")
        self.assertEqual(
            payload[0]["tool_activity"],
            [
                {
                    "type": "tool_call",
                    "name": "sandbox_run_python",
                    "arguments": {"code": "print(1)"},
                    "count": 2,
                },
                {
                    "type": "tool_result",
                    "name": "sandbox_run_python",
                    "result_preview": "ok",
                    "count": 2,
                },
            ],
        )

    def test_build_memory_fallback_records_repeated_tool_paths_and_handoff(self) -> None:
        updated = build_memory_fallback(
            LayeredConversationMemory(handoff=SessionHandoffCard(task="Keep testing target")),
            transcript_payload=[
                {
                    "id": "u1",
                    "role": "user",
                    "status": "completed",
                    "text": "Try the script again on https://example.test/flag",
                    "content": [],
                },
                {
                    "id": "a1",
                    "role": "assistant",
                    "status": "completed",
                    "text": "Repeated the same script and got the same result.",
                    "content": [
                        {
                            "type": "tool_call",
                            "name": "sandbox_run_python",
                            "arguments": {"script_path": "exploit.py"},
                        },
                    ],
                    "tool_activity": [
                        {
                            "type": "tool_call",
                            "name": "sandbox_run_python",
                            "arguments": {"code": "print(1)"},
                            "count": 2,
                        },
                    ],
                },
            ],
            validated_findings=[MemoryNote(statement="Confirmed issue", evidence=["stdout shows success"])],
            anchor_message_id="a1",
        )

        self.assertEqual(updated.anchor_message_id, "a1")
        self.assertEqual(updated.summary, "Currently confirmed 1 validated findings.")
        self.assertEqual(updated.recent_progress, "Repeated the same script and got the same result.")
        self.assertEqual(updated.next_focus, ["Continue from the latest user objective: Try the script again on https://example.test/flag"])
        self.assertTrue(
            any("Repeated identical tool call with unchanged arguments" in note.statement for note in updated.dead_ends)
        )
        self.assertEqual(updated.handoff.task, "Keep testing target")
        self.assertIn("Try the script again on https://example.test/flag", updated.handoff.instructions)
        self.assertIn("https://example.test/flag", updated.handoff.target_urls)
        self.assertIn("exploit.py", updated.handoff.relevant_files)
        self.assertTrue(any("Repeated the same script and got the same result." in item for item in updated.handoff.discoveries))
        self.assertTrue(any("sandbox_run_python" in item for item in updated.handoff.accomplished))
        self.assertTrue(any("Confirmed issue" in item for item in updated.handoff.confirmed_facts))
        self.assertTrue(any("Repeated identical tool call with unchanged arguments" in item for item in updated.handoff.avoid_repeating))

    def test_handoff_render_for_model_uses_opencode_style_sections(self) -> None:
        memory = LayeredConversationMemory(
            summary="Investigated the login flow.",
            recent_progress="Confirmed the token rotates after login.",
            handoff=SessionHandoffCard(
                task="Assess the login flow for auth issues",
                instructions=["Keep scope on https://example.test/login", "Continue from the latest CSRF lead"],
                discoveries=["Login issues a rotating CSRF token"],
                accomplished=["Recently executed or inspected via tools: browser_navigate, browser_get_html"],
                relevant_files=["csrf_probe.py"],
                target_urls=["https://example.test/login"],
                next_steps=["Compare token handling across tabs"],
            ),
        )

        rendered = memory.render_for_model()

        self.assertIn("Goal:", rendered)
        self.assertIn("Instructions:", rendered)
        self.assertIn("Discoveries:", rendered)
        self.assertIn("Accomplished:", rendered)
        self.assertIn("Relevant files and directories:", rendered)
        self.assertIn("Summary:", rendered)


if __name__ == "__main__":
    unittest.main()
