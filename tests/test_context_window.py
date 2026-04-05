"""Tests for context window memory management."""

from __future__ import annotations

import pytest

from autosongshu_agent.memory import (
    TranscriptEntry,
    TranscriptStore,
    TokenBudgetTracker,
    ContextWindowConfig,
    ContextWindowManager,
    CompactionResult,
)


class TestTranscriptEntry:
    def test_create_entry(self) -> None:
        entry = TranscriptEntry(
            role="user",
            content="Hello world",
            token_count=3,
        )
        assert entry.role == "user"
        assert entry.content == "Hello world"
        assert entry.token_count == 3
        assert entry.timestamp != ""
        assert entry.metadata == {}

    def test_entry_to_dict(self) -> None:
        entry = TranscriptEntry(
            role="assistant",
            content="Hi there",
            token_count=2,
            metadata={"model": "gpt-4"},
        )
        data = entry.to_dict()
        assert data["role"] == "assistant"
        assert data["content"] == "Hi there"
        assert data["token_count"] == 2
        assert data["metadata"]["model"] == "gpt-4"

    def test_entry_from_dict(self) -> None:
        data = {
            "role": "user",
            "content": "Test",
            "token_count": 1,
            "timestamp": "2024-01-01T00:00:00",
            "metadata": {"key": "value"},
        }
        entry = TranscriptEntry.from_dict(data)
        assert entry.role == "user"
        assert entry.content == "Test"
        assert entry.token_count == 1
        assert entry.timestamp == "2024-01-01T00:00:00"
        assert entry.metadata["key"] == "value"


class TestTranscriptStore:
    def test_append_entry(self) -> None:
        store = TranscriptStore()
        store.append("user", "Hello", token_count=2)
        assert len(store.entries) == 1
        assert store.entries[0].role == "user"
        assert store.entries[0].content == "Hello"
        assert store.flushed is False

    def test_total_tokens(self) -> None:
        store = TranscriptStore()
        store.append("user", "Hello", token_count=2)
        store.append("assistant", "Hi", token_count=1)
        assert store.total_tokens() == 3

    def test_message_count(self) -> None:
        store = TranscriptStore()
        store.append("user", "Hello", token_count=2)
        store.append("assistant", "Hi", token_count=1)
        store.append("user", "Bye", token_count=1)
        assert store.message_count() == 3

    def test_turn_count(self) -> None:
        store = TranscriptStore()
        store.append("user", "Hello", token_count=2)
        store.append("assistant", "Hi", token_count=1)
        store.append("user", "Bye", token_count=1)
        assert store.turn_count() == 2

    def test_replay(self) -> None:
        store = TranscriptStore()
        store.append("user", "Hello", token_count=2)
        store.append("assistant", "Hi", token_count=1)
        entries = store.replay()
        assert len(entries) == 2
        assert entries[0].content == "Hello"

    def test_replay_as_strings(self) -> None:
        store = TranscriptStore()
        store.append("user", "Hello", token_count=2)
        store.append("assistant", "Hi", token_count=1)
        strings = store.replay_as_strings()
        assert strings == ("Hello", "Hi")

    def test_flush(self) -> None:
        store = TranscriptStore()
        store.append("user", "Hello", token_count=2)
        store.flush()
        assert store.flushed is True

    def test_compact_keep_last(self) -> None:
        store = TranscriptStore()
        for i in range(15):
            store.append("user", f"Message {i}", token_count=2)
        removed = store.compact(keep_last=5, keep_first=0)
        assert removed == 10
        assert len(store.entries) == 15
        assert store.active_message_count() == 5
        assert store.entries[10].content == "Message 10"
        assert store.entries[10].compacted is False

    def test_compact_keep_first_and_last(self) -> None:
        store = TranscriptStore()
        for i in range(15):
            store.append("user", f"Message {i}", token_count=2)
        removed = store.compact(keep_last=5, keep_first=2)
        assert removed == 8
        assert len(store.entries) == 15
        assert store.active_message_count() == 7
        assert store.entries[0].content == "Message 0"
        assert store.entries[0].compacted is False
        assert store.entries[1].content == "Message 1"
        assert store.entries[1].compacted is False
        assert store.entries[10].content == "Message 10"
        assert store.entries[10].compacted is False

    def test_compact_no_change_if_small(self) -> None:
        store = TranscriptStore()
        for i in range(5):
            store.append("user", f"Message {i}", token_count=2)
        removed = store.compact(keep_last=10)
        assert removed == 0
        assert len(store.entries) == 5

    def test_compact_by_tokens(self) -> None:
        store = TranscriptStore()
        for i in range(20):
            store.append("user", f"Message {i}", token_count=100)
            store.append("assistant", f"Response {i}", token_count=100)
        removed = store.compact_by_tokens(max_tokens=1000, keep_last_n_turns=3)
        assert removed > 0
        assert store.active_tokens() < 4000
        assert len(store.entries) == 40

    def test_to_dict_and_from_dict(self) -> None:
        store = TranscriptStore()
        store.append("user", "Hello", token_count=2)
        store.append("assistant", "Hi", token_count=1)
        store.flush()

        data = store.to_dict()
        restored = TranscriptStore.from_dict(data)

        assert len(restored.entries) == 2
        assert restored.flushed is True
        assert restored.entries[0].content == "Hello"
        assert restored.entries[1].content == "Hi"


class TestTokenBudgetTracker:
    def test_count_tokens_basic(self) -> None:
        tracker = TokenBudgetTracker()
        count = tracker.count_tokens("Hello world this is a test")
        assert count > 0

    def test_count_tokens_empty(self) -> None:
        tracker = TokenBudgetTracker()
        assert tracker.count_tokens("") == 0

    def test_count_messages_tokens(self) -> None:
        tracker = TokenBudgetTracker()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        count = tracker.count_messages_tokens(messages)
        assert count > 0

    def test_available_budget(self) -> None:
        tracker = TokenBudgetTracker(context_window=100000, reserved_tokens=10000)
        budget = tracker.available_budget(used_tokens=50000)
        assert budget == 40000

    def test_should_compact(self) -> None:
        tracker = TokenBudgetTracker(context_window=100000, reserved_tokens=10000)
        assert tracker.should_compact(used_tokens=80000) is True
        assert tracker.should_compact(used_tokens=50000) is False


class TestContextWindowConfig:
    def test_default_config(self) -> None:
        config = ContextWindowConfig()
        assert config.max_tokens == 120000
        assert config.reserved_tokens == 8000
        assert config.compact_after_tokens == 90000
        assert config.compact_after_turns == 12

    def test_custom_config(self) -> None:
        config = ContextWindowConfig(
            max_tokens=200000,
            reserved_tokens=10000,
            compact_after_turns=20,
        )
        assert config.max_tokens == 200000
        assert config.reserved_tokens == 10000
        assert config.compact_after_turns == 20


class TestContextWindowManager:
    def test_add_message(self) -> None:
        manager = ContextWindowManager()
        tokens = manager.add_message("user", "Hello world")
        assert tokens > 0
        assert manager.transcript.message_count() == 1
        assert manager.total_input_tokens > 0

    def test_add_assistant_message(self) -> None:
        manager = ContextWindowManager()
        manager.add_message("user", "Hello")
        manager.add_message("assistant", "Hi there")
        assert manager.total_output_tokens > 0

    def test_current_usage(self) -> None:
        manager = ContextWindowManager()
        manager.add_message("user", "Hello world")
        manager.add_message("assistant", "Hi there")
        usage = manager.current_usage()
        assert usage["transcript_entries"] == 2
        assert usage["turn_count"] == 1
        assert usage["total_tokens"] > 0

    def test_should_compact_by_turns(self) -> None:
        config = ContextWindowConfig(compact_after_turns=5)
        manager = ContextWindowManager(config=config)
        for i in range(10):
            manager.add_message("user", f"Message {i}")
            manager.add_message("assistant", f"Response {i}")
        assert manager.should_compact() is True

    def test_compact_if_needed(self) -> None:
        config = ContextWindowConfig(compact_after_turns=3, compact_after_tokens=100)
        manager = ContextWindowManager(config=config)
        for i in range(10):
            manager.add_message("user", f"Message {i}" * 10)
            manager.add_message("assistant", f"Response {i}" * 10)
        result = manager.compact_if_needed()
        assert result is not None
        assert result.entries_marked_compacted > 0

    def test_compact_not_needed(self) -> None:
        manager = ContextWindowManager()
        manager.add_message("user", "Hello")
        result = manager.compact_if_needed()
        assert result is None

    def test_get_context_for_model(self) -> None:
        manager = ContextWindowManager()
        manager.add_message("user", "Hello")
        manager.add_message("assistant", "Hi")
        messages = manager.get_context_for_model("You are a helpful assistant.")
        assert len(messages) == 3
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[2]["role"] == "assistant"

    def test_estimate_context_tokens(self) -> None:
        manager = ContextWindowManager()
        manager.add_message("user", "Hello")
        tokens = manager.estimate_context_tokens("System prompt")
        assert tokens > 0

    def test_reset(self) -> None:
        manager = ContextWindowManager()
        manager.add_message("user", "Hello")
        manager.add_message("assistant", "Hi")
        manager.reset()
        assert manager.transcript.message_count() == 0
        assert manager.total_input_tokens == 0
        assert manager.total_output_tokens == 0

    def test_to_dict_and_from_dict(self) -> None:
        config = ContextWindowConfig(compact_after_turns=5)
        manager = ContextWindowManager(config=config)
        manager.add_message("user", "Hello")
        manager.add_message("assistant", "Hi")

        data = manager.to_dict()
        restored = ContextWindowManager.from_dict(data)

        assert restored.config.compact_after_turns == 5
        assert restored.transcript.message_count() == 2
        assert restored.total_input_tokens == manager.total_input_tokens
