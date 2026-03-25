from __future__ import annotations

import asyncio
import threading
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from agentscope.message import Msg

from autosongshu_agent.agent import ConversationReply, PentestConversationSession
from autosongshu_agent.chat_manager import (
    ChatSessionManager,
    ChatSessionState,
    should_force_stream_flush,
)
from autosongshu_agent.skills import SkillLoadReport


class _InterruptibleDummyAgent:
    def __init__(self) -> None:
        self._reply_task: asyncio.Task[Msg] | None = None
        self.interrupt_calls = 0

    async def __call__(self, _msg: Msg) -> Msg:
        self._reply_task = asyncio.current_task()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return Msg(
                "AutoSongshu",
                "I noticed that you have interrupted me. What can I do for you?",
                "assistant",
            )
        finally:
            self._reply_task = None
        return Msg("AutoSongshu", "completed", "assistant")

    async def interrupt(self, _msg: Msg | list[Msg] | None = None) -> None:
        self.interrupt_calls += 1
        if self._reply_task is not None and not self._reply_task.done():
            self._reply_task.cancel()

    async def observe(self, _messages: list[Msg]) -> None:
        return None

    def set_msg_queue_enabled(
        self, _enabled: bool, queue: asyncio.Queue | None = None
    ) -> None:
        _ = queue


class _ConversationRecorder:
    def __init__(self) -> None:
        self.interrupt_calls = 0

    def interrupt(self) -> bool:
        self.interrupt_calls += 1
        return True

    def close(self) -> None:
        return None


class _StreamingConversation:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            compaction=SimpleNamespace(min_turns=1, retain_recent_turns=0),
        )
        self.runtime = SimpleNamespace(
            artifacts=SimpleNamespace(session_dir=Path("artifacts/test-session"))
        )

    def send(self, _content: str, stream_callback=None) -> ConversationReply:
        if stream_callback is not None:
            stream_callback(
                {
                    "content": "",
                    "last": False,
                    "blocks": [
                        {"type": "text", "text": "Navigating to the target now."},
                        {
                            "type": "tool_use",
                            "id": "tool:1",
                            "name": "browser_navigate",
                            "input": {"url": "https://example.test"},
                        },
                    ],
                },
            )
            stream_callback(
                {
                    "content": "",
                    "last": False,
                    "blocks": [
                        {
                            "type": "text",
                            "text": "Navigation finished and returned HTTP 200.",
                        },
                        {
                            "type": "tool_use",
                            "id": "tool:1",
                            "name": "browser_navigate",
                            "input": {"url": "https://example.test"},
                        },
                        {
                            "type": "tool_result",
                            "id": "tool:1",
                            "name": "browser_navigate",
                            "output": [{"type": "text", "text": "HTTP 200"}],
                        },
                    ],
                },
            )
        return ConversationReply(
            assistant_message="Completed.",
            artifact_dir="artifacts/test-session",
            blocks=[{"type": "text", "text": "Completed."}],
        )

    def close(self) -> None:
        return None


class _DelayedMemoryConversation:
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            compaction=SimpleNamespace(min_turns=1, retain_recent_turns=0),
        )
        self.runtime = SimpleNamespace(
            artifacts=SimpleNamespace(session_dir=Path("artifacts/test-session"))
        )
        self.refresh_started = threading.Event()
        self.refresh_release = threading.Event()
        self.send_calls: list[str] = []
        self.second_send_started = threading.Event()

    def send(self, content: str, stream_callback=None) -> ConversationReply:
        _ = stream_callback
        self.send_calls.append(content)
        if len(self.send_calls) >= 2:
            self.second_send_started.set()
        return ConversationReply(
            assistant_message="Completed.",
            artifact_dir="artifacts/test-session",
            blocks=[{"type": "text", "text": "Completed."}],
        )

    def refresh_memory(self, *, existing_memory, transcript_payload, anchor_message_id):
        _ = (existing_memory, transcript_payload, anchor_message_id)
        self.refresh_started.set()
        released = self.refresh_release.wait(timeout=3)
        if not released:
            raise TimeoutError("refresh_memory did not finish in time")
        return existing_memory

    def rebuild_context(self, *args, **kwargs) -> None:
        _ = (args, kwargs)

    def interrupt(self) -> bool:
        return True

    def close(self) -> None:
        return None


class PentestConversationInterruptTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_interrupt_is_applied_when_send_starts(self) -> None:
        session = object.__new__(PentestConversationSession)
        session.agent = _InterruptibleDummyAgent()
        session.runtime = SimpleNamespace(
            artifacts=SimpleNamespace(session_dir=Path("artifacts/test-session")),
            persist_runtime_logs=lambda: None,
        )
        session.skill_report = SkillLoadReport(configured_directories=[])
        session._interrupt_lock = threading.RLock()
        session._active_loop = None
        session._interrupt_requested = False

        self.assertFalse(session.interrupt())

        reply = await session.send_async("interrupt this run")

        self.assertIn("interrupted me", reply.assistant_message.lower())
        self.assertEqual(session.agent.interrupt_calls, 1)
        self.assertIsNone(session._active_loop)
        self.assertFalse(session._interrupt_requested)


class ChatSessionManagerInterruptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = ChatSessionManager(project_root=Path(self.temp_dir.name))
        self.addCleanup(self.manager.shutdown)

    def test_interrupt_session_marks_running_session_interrupting(self) -> None:
        conversation = _ConversationRecorder()
        session = ChatSessionState(
            session_id="chat-0001",
            title="Interrupt test",
            config_path="E:/config.yaml",
            status="running",
            future=Future(),
            conversation=conversation,
        )
        self.manager.chat_sessions[session.session_id] = session

        detail = self.manager.interrupt_session(session.session_id)

        self.assertEqual(detail["status"], "interrupting")
        self.assertEqual(session.status, "interrupting")
        self.assertTrue(session.interrupt_requested)
        self.assertEqual(conversation.interrupt_calls, 1)

    def test_interrupt_session_rejects_idle_session(self) -> None:
        session = ChatSessionState(
            session_id="chat-0002",
            title="Idle test",
            config_path="E:/config.yaml",
            status="idle",
        )
        self.manager.chat_sessions[session.session_id] = session

        with self.assertRaises(RuntimeError):
            self.manager.interrupt_session(session.session_id)

    def test_should_force_stream_flush_for_tool_events(self) -> None:
        self.assertTrue(should_force_stream_flush({"last": True, "blocks": []}))
        self.assertTrue(
            should_force_stream_flush(
                {
                    "last": False,
                    "blocks": [{"type": "tool_use", "name": "browser_navigate"}],
                }
            ),
        )
        self.assertTrue(
            should_force_stream_flush(
                {
                    "last": False,
                    "blocks": [{"type": "tool_result", "name": "browser_navigate"}],
                }
            ),
        )
        self.assertFalse(
            should_force_stream_flush(
                {"last": False, "blocks": [{"type": "text", "text": "working"}]}
            )
        )

    def test_stream_partial_updates_emit_running_session_summary(self) -> None:
        session = ChatSessionState(
            session_id="chat-0003",
            title="Streaming test",
            config_path="E:/config.yaml",
        )
        self.manager.chat_sessions[session.session_id] = session
        self.manager._ensure_conversation_ready = lambda *_args, **_kwargs: (
            _StreamingConversation()
        )

        events: list[dict[str, object]] = []
        listener_id = self.manager.add_listener(events.append)
        self.addCleanup(self.manager.remove_listener, listener_id)

        detail = self.manager.enqueue_message(
            session.session_id, "Inspect the home page"
        )
        self.assertEqual(detail["status"], "running")

        future = self.manager.chat_sessions[session.session_id].future
        self.assertIsNotNone(future)
        future.result(timeout=3)

        running_session_events = [
            event
            for event in events
            if event.get("type") == "session.upsert"
            and event.get("session", {}).get("status") == "running"
        ]

        self.assertGreaterEqual(len(running_session_events), 2)
        self.assertTrue(
            any(
                event.get("session", {}).get("last_message")
                == "Navigating to the target now."
                for event in running_session_events
            )
        )

    def test_second_turn_can_queue_while_post_turn_cleanup_finishes(self) -> None:
        session = ChatSessionState(
            session_id="chat-0004",
            title="Cleanup lock test",
            config_path="E:/config.yaml",
        )
        conversation = _DelayedMemoryConversation()
        self.manager.chat_sessions[session.session_id] = session
        self.manager._should_auto_compact_session = lambda *_args, **_kwargs: True
        self.manager._ensure_conversation_ready = lambda current_session, **_kwargs: (
            setattr(current_session, "conversation", conversation) or conversation
        )

        detail = self.manager.enqueue_message(session.session_id, "First turn")
        self.assertEqual(detail["status"], "running")
        self.assertTrue(conversation.refresh_started.wait(timeout=2))
        self.assertEqual(conversation.send_calls, ["First turn"])

        next_detail = self.manager.enqueue_message(
            session.session_id, "Second turn too early"
        )
        self.assertEqual(next_detail["status"], "running")
        self.assertFalse(conversation.second_send_started.wait(timeout=0.2))
        self.assertTrue(self.manager.chat_sessions[session.session_id].is_compacting)

        conversation.refresh_release.set()
        self.assertTrue(conversation.second_send_started.wait(timeout=2))
        self.assertEqual(
            conversation.send_calls, ["First turn", "Second turn too early"]
        )

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            current_session = self.manager.chat_sessions[session.session_id]
            if current_session.status == "idle" and not current_session.is_compacting:
                break
            time.sleep(0.02)
        self.assertEqual(self.manager.chat_sessions[session.session_id].status, "idle")
        self.assertFalse(self.manager.chat_sessions[session.session_id].is_compacting)


if __name__ == "__main__":
    unittest.main()
