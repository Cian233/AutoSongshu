from __future__ import annotations

import unittest

from autosongshu_agent.history import HistoryEvent, HistoryLog


class HistoryEventTests(unittest.TestCase):
    def test_event_creation(self) -> None:
        event = HistoryEvent(title="Test", detail="Test detail")
        self.assertEqual(event.title, "Test")
        self.assertEqual(event.detail, "Test detail")
        self.assertEqual(event.category, "general")
        self.assertIsNotNone(event.timestamp)

    def test_event_with_category(self) -> None:
        event = HistoryEvent(title="Test", detail="Detail", category="tool_call")
        self.assertEqual(event.category, "tool_call")

    def test_event_to_dict(self) -> None:
        event = HistoryEvent(title="Test", detail="Detail", category="custom")
        d = event.to_dict()
        self.assertEqual(d["title"], "Test")
        self.assertEqual(d["detail"], "Detail")
        self.assertEqual(d["category"], "custom")
        self.assertIn("timestamp", d)


class HistoryLogTests(unittest.TestCase):
    def test_empty_log(self) -> None:
        log = HistoryLog()
        self.assertEqual(len(log.events), 0)

    def test_add_event(self) -> None:
        log = HistoryLog()
        event = log.add("Test", "Detail")
        self.assertEqual(len(log.events), 1)
        self.assertEqual(log.events[0], event)

    def test_max_events_limit(self) -> None:
        log = HistoryLog(max_events=5)
        for i in range(10):
            log.add(f"Event {i}", f"Detail {i}")
        self.assertEqual(len(log.events), 5)
        self.assertEqual(log.events[0].title, "Event 5")

    def test_add_tool_call(self) -> None:
        log = HistoryLog()
        event = log.add_tool_call("http_get", {"url": "http://example.com"})
        self.assertEqual(event.category, "tool_call")
        self.assertIn("http_get", event.detail)

    def test_add_tool_result_success(self) -> None:
        log = HistoryLog()
        event = log.add_tool_result("http_get", success=True, summary="200 OK")
        self.assertEqual(event.category, "tool_result")
        self.assertIn("succeeded", event.detail)

    def test_add_tool_result_failure(self) -> None:
        log = HistoryLog()
        event = log.add_tool_result(
            "http_get", success=False, summary="Connection refused"
        )
        self.assertIn("failed", event.detail)

    def test_add_model_call(self) -> None:
        log = HistoryLog()
        event = log.add_model_call("gpt-4", input_tokens=100, output_tokens=50)
        self.assertEqual(event.category, "model")
        self.assertIn("100", event.detail)
        self.assertIn("50", event.detail)

    def test_add_user_message(self) -> None:
        log = HistoryLog()
        event = log.add_user_message("Hello world")
        self.assertEqual(event.category, "user")

    def test_add_assistant_message(self) -> None:
        log = HistoryLog()
        event = log.add_assistant_message("Response text")
        self.assertEqual(event.category, "assistant")

    def test_add_error(self) -> None:
        log = HistoryLog()
        event = log.add_error("Something went wrong", context="http_get")
        self.assertEqual(event.category, "error")
        self.assertIn("http_get", event.detail)

    def test_add_session_event(self) -> None:
        log = HistoryLog()
        event = log.add_session_event("started", "New session started")
        self.assertEqual(event.category, "session")

    def test_clear(self) -> None:
        log = HistoryLog()
        log.add("Test", "Detail")
        log.add("Test2", "Detail2")
        log.clear()
        self.assertEqual(len(log.events), 0)

    def test_get_events_by_category(self) -> None:
        log = HistoryLog()
        log.add("T1", "D1", category="user")
        log.add("T2", "D2", category="tool_call")
        log.add("T3", "D3", category="user")
        user_events = log.get_events_by_category("user")
        self.assertEqual(len(user_events), 2)

    def test_get_recent_events(self) -> None:
        log = HistoryLog()
        for i in range(10):
            log.add(f"Event {i}", f"Detail {i}")
        recent = log.get_recent_events(limit=3)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[-1].title, "Event 9")

    def test_to_dict_list(self) -> None:
        log = HistoryLog()
        log.add("T1", "D1")
        log.add("T2", "D2")
        dicts = log.to_dict_list()
        self.assertEqual(len(dicts), 2)
        self.assertIsInstance(dicts[0], dict)

    def test_as_markdown(self) -> None:
        log = HistoryLog(session_id="test-session")
        log.add("Event 1", "Detail 1", category="user")
        log.add("Event 2", "Detail 2", category="tool_call")
        md = log.as_markdown()
        self.assertIn("# Session History", md)
        self.assertIn("test-session", md)
        self.assertIn("## User", md)
        self.assertIn("## Tool_Call", md)

    def test_as_markdown_empty(self) -> None:
        log = HistoryLog()
        md = log.as_markdown()
        self.assertIn("No events recorded", md)

    def test_summary_dict(self) -> None:
        log = HistoryLog(session_id="my-session")
        log.add("T1", "D1", category="user")
        log.add("T2", "D2", category="user")
        log.add("T3", "D3", category="tool_call")
        summary = log.summary_dict()
        self.assertEqual(summary["session_id"], "my-session")
        self.assertEqual(summary["total_events"], 3)
        self.assertEqual(summary["category_counts"]["user"], 2)
        self.assertEqual(summary["category_counts"]["tool_call"], 1)


if __name__ == "__main__":
    unittest.main()
