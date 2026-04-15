from __future__ import annotations

import asyncio
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agentscope.message import Msg, TextBlock
from agentscope.tool import ToolResponse

from autosongshu_agent.agent import PentestConversationSession
from autosongshu_agent.runtime import PerTurnToolCallCache
from autosongshu_agent.tools import _ToolExecutionPolicy, _wrap_registered_tool


def _response_text(response: ToolResponse) -> str:
    if not response.content:
        return ""
    first = response.content[0]
    if isinstance(first, dict):
        return str(first.get("text") or "")
    return str(first.text)


def _tool_response(text: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=text)])


class _StaticReplyAgent:
    def set_msg_queue_enabled(self, *_args, **_kwargs) -> None:
        return None

    async def __call__(self, _msg: Msg) -> Msg:
        return Msg(name="AutoSongshu", role="assistant", content="Completed.")

    async def interrupt(self) -> None:
        return None


class _RecordingReplyAgent(_StaticReplyAgent):
    def __init__(self) -> None:
        self.received_contents: list[str] = []

    async def __call__(self, msg: Msg) -> Msg:
        self.received_contents.append(str(msg.content))
        return await super().__call__(msg)


class _CountingTurnCache:
    def __init__(self) -> None:
        self.reset_count = 0

    def reset_turn(self) -> None:
        self.reset_count += 1


class ToolDedupeTests(unittest.TestCase):
    def test_read_only_tool_reuses_cached_response_for_identical_arguments(self) -> None:
        runtime = SimpleNamespace(tool_call_cache=PerTurnToolCallCache())
        calls: list[str] = []

        def browser_snapshot(runtime: Any, url: str = "") -> ToolResponse:
            calls.append(url)
            return _tool_response(f"snapshot:{url}:{len(calls)}")

        wrapped = _wrap_registered_tool(browser_snapshot, runtime, policy=_ToolExecutionPolicy())

        first = wrapped(url="https://example.test")
        second = wrapped(url="https://example.test")
        third = wrapped(url="https://example.test/admin")

        self.assertEqual(calls, ["https://example.test", "https://example.test/admin"])
        self.assertEqual(_response_text(first), "snapshot:https://example.test:1")
        self.assertEqual(_response_text(second), "snapshot:https://example.test:1")
        self.assertEqual(_response_text(third), "snapshot:https://example.test/admin:2")

    def test_mutating_tool_invalidates_previous_cache_but_caches_its_own_result(self) -> None:
        runtime = SimpleNamespace(tool_call_cache=PerTurnToolCallCache())
        counters = {"snapshot": 0, "navigate": 0}

        def browser_snapshot(runtime: Any) -> ToolResponse:
            counters["snapshot"] += 1
            return _tool_response(f"snapshot:{counters['snapshot']}")

        def browser_navigate(runtime: Any, url: str) -> ToolResponse:
            counters["navigate"] += 1
            return _tool_response(f"navigate:{url}:{counters['navigate']}")

        snapshot = _wrap_registered_tool(browser_snapshot, runtime, policy=_ToolExecutionPolicy())
        navigate = _wrap_registered_tool(
            browser_navigate,
            runtime,
            policy=_ToolExecutionPolicy(invalidates_cache=True),
        )

        self.assertEqual(_response_text(snapshot()), "snapshot:1")
        self.assertEqual(_response_text(snapshot()), "snapshot:1")
        self.assertEqual(_response_text(navigate("https://example.test")), "navigate:https://example.test:1")
        self.assertEqual(_response_text(navigate("https://example.test")), "navigate:https://example.test:1")
        self.assertEqual(_response_text(snapshot()), "snapshot:2")
        self.assertEqual(counters, {"snapshot": 2, "navigate": 1})

    def test_send_async_resets_tool_cache_for_each_outer_turn(self) -> None:
        cache = _CountingTurnCache()
        session = object.__new__(PentestConversationSession)
        session.agent = _StaticReplyAgent()
        session.runtime = SimpleNamespace(
            tool_call_cache=cache,
            persist_runtime_logs=lambda: None,
            artifacts=SimpleNamespace(session_dir=Path("artifacts/test-session")),
        )
        session.config = SimpleNamespace(
            agent=SimpleNamespace(loop_guard_enabled=False, turn_timeout_sec=30),
        )
        session.skill_report = None
        session._interrupt_lock = threading.RLock()
        session._active_loop = None
        session._interrupt_requested = False
        session.cost_tracker = SimpleNamespace(add_usage=lambda **kwargs: None)
        session.trajectory_recorder = SimpleNamespace(
            start_session=lambda **kwargs: None,
            end_session=lambda **kwargs: None,
        )

        first = asyncio.run(session.send_async("First task"))
        second = asyncio.run(session.send_async("Second task"))

        self.assertEqual(first.assistant_message, "Completed.")
        self.assertEqual(second.assistant_message, "Completed.")
        self.assertEqual(cache.reset_count, 2)

    def test_send_async_does_not_duplicate_memory_context_in_user_message(self) -> None:
        session = object.__new__(PentestConversationSession)
        session.agent = _RecordingReplyAgent()
        session.runtime = SimpleNamespace(
            persist_runtime_logs=lambda: None,
            artifacts=SimpleNamespace(session_dir=Path("artifacts/test-session")),
        )
        session.config = SimpleNamespace(
            agent=SimpleNamespace(loop_guard_enabled=False, turn_timeout_sec=30),
        )
        session.skill_report = None
        session._interrupt_lock = threading.RLock()
        session._active_loop = None
        session._interrupt_requested = False
        session._memory_context = "MEMORY_CONTEXT_SHOULD_NOT_BE_IN_USER_MESSAGE"
        session.cost_tracker = SimpleNamespace(add_usage=lambda **kwargs: None)
        session.trajectory_recorder = SimpleNamespace(
            start_session=lambda **kwargs: None,
            end_session=lambda **kwargs: None,
        )

        reply = asyncio.run(session.send_async("Continue current task"))

        self.assertEqual(reply.assistant_message, "Completed.")
        self.assertEqual(len(session.agent.received_contents), 1)
        prepared_content = session.agent.received_contents[0]
        self.assertIn("Continue current task", prepared_content)
        self.assertNotIn(
            "MEMORY_CONTEXT_SHOULD_NOT_BE_IN_USER_MESSAGE",
            prepared_content,
        )


if __name__ == "__main__":
    unittest.main()
