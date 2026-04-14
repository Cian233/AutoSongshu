"""Memory management module with claw-code-style improvements.

This module provides:
- TranscriptStore: Message history with sliding window compaction
- TokenBudgetTracker: Accurate token counting with tiktoken
- ContextWindowManager: Budget-aware context management
- CompactionStrategy: Smart message compression

Key design: Compacted messages are MARKED but NOT DELETED.
Users can still view the full history while the model only sees active messages.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from .models import LayeredConversationMemory, MemoryNote, SessionHandoffCard
from .compaction import select_messages_for_compaction, CompactionStrategy


@dataclass
class TranscriptEntry:
    """Single entry in the transcript store."""

    role: str
    content: str
    token_count: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    metadata: dict[str, Any] = field(default_factory=dict)
    compacted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "token_count": self.token_count,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "compacted": self.compacted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranscriptEntry":
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            token_count=data.get("token_count", 0),
            timestamp=data.get("timestamp", ""),
            metadata=data.get("metadata", {}),
            compacted=data.get("compacted", False),
        )


@dataclass
class CompactedRange:
    """Represents a range of compacted messages."""

    start_index: int
    end_index: int
    token_count: int
    turn_count: int
    summary: str = ""
    compacted_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_index": self.start_index,
            "end_index": self.end_index,
            "token_count": self.token_count,
            "turn_count": self.turn_count,
            "summary": self.summary,
            "compacted_at": self.compacted_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CompactedRange":
        return cls(
            start_index=data.get("start_index", 0),
            end_index=data.get("end_index", 0),
            token_count=data.get("token_count", 0),
            turn_count=data.get("turn_count", 0),
            summary=data.get("summary", ""),
            compacted_at=data.get("compacted_at", ""),
        )


@dataclass
class TranscriptStore:
    """Message history store with compaction support.

    Similar to claw-code's TranscriptStore but with token-aware compaction.
    Compacted messages are MARKED but NOT DELETED - users can still view them.
    """

    entries: list[TranscriptEntry] = field(default_factory=list)
    flushed: bool = False
    compacted_ranges: list[CompactedRange] = field(default_factory=list)
    total_tokens_compacted: int = 0

    def append(
        self,
        role: str,
        content: str,
        token_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        entry = TranscriptEntry(
            role=role,
            content=content,
            token_count=token_count,
            metadata=metadata or {},
        )
        self.entries.append(entry)
        self.flushed = False

    def compact(self, keep_last: int = 10, keep_first: int = 1) -> int:
        """Mark entries as compacted but keep them in the store.

        Returns the number of entries marked as compacted.
        """
        if len(self.entries) <= keep_first + keep_last:
            return 0

        start_index = keep_first
        end_index = len(self.entries) - keep_last

        entries_to_compact = self.entries[start_index:end_index]
        if not entries_to_compact:
            return 0

        tokens_compacted = sum(e.token_count for e in entries_to_compact)
        turns_compacted = sum(1 for e in entries_to_compact if e.role == "user")

        for entry in entries_to_compact:
            entry.compacted = True

        self.compacted_ranges.append(
            CompactedRange(
                start_index=start_index,
                end_index=end_index,
                token_count=tokens_compacted,
                turn_count=turns_compacted,
                summary=f"Compacted {len(entries_to_compact)} messages ({turns_compacted} turns, ~{tokens_compacted} tokens)",
            )
        )

        self.total_tokens_compacted += tokens_compacted
        return len(entries_to_compact)

    def compact_by_tokens(
        self,
        max_tokens: int,
        keep_first: int = 1,
        keep_last_n_turns: int = 4,
    ) -> int:
        """Compact by token budget, marking entries as compacted.

        Returns the number of entries marked as compacted.
        """
        active_entries = [e for e in self.entries if not e.compacted]
        total_tokens = sum(e.token_count for e in active_entries)
        if total_tokens <= max_tokens:
            return 0

        first_entries = active_entries[:keep_first]
        remaining = active_entries[keep_first:]

        assistant_indices = [
            i for i, e in enumerate(remaining) if e.role == "assistant"
        ]

        if len(assistant_indices) <= keep_last_n_turns:
            return 0

        keep_from_index = assistant_indices[-keep_last_n_turns]
        entries_to_compact = remaining[:keep_from_index]

        if not entries_to_compact:
            return 0

        tokens_compacted = sum(e.token_count for e in entries_to_compact)
        turns_compacted = sum(1 for e in entries_to_compact if e.role == "user")

        for entry in entries_to_compact:
            entry.compacted = True

        start_idx = (
            self.entries.index(entries_to_compact[0]) if entries_to_compact else 0
        )
        end_idx = (
            self.entries.index(entries_to_compact[-1]) + 1 if entries_to_compact else 0
        )

        self.compacted_ranges.append(
            CompactedRange(
                start_index=start_idx,
                end_index=end_idx,
                token_count=tokens_compacted,
                turn_count=turns_compacted,
                summary=f"Compacted {len(entries_to_compact)} messages ({turns_compacted} turns, ~{tokens_compacted} tokens)",
            )
        )

        self.total_tokens_compacted += tokens_compacted
        return len(entries_to_compact)

    def active_entries(self) -> list[TranscriptEntry]:
        """Return entries that are NOT compacted (sent to model)."""
        return [e for e in self.entries if not e.compacted]

    def compacted_entries(self) -> list[TranscriptEntry]:
        """Return entries that ARE compacted (hidden from model but visible to user)."""
        return [e for e in self.entries if e.compacted]

    def total_tokens(self) -> int:
        """Total tokens of ALL entries."""
        return sum(e.token_count for e in self.entries)

    def active_tokens(self) -> int:
        """Total tokens of ACTIVE (non-compacted) entries."""
        return sum(e.token_count for e in self.entries if not e.compacted)

    def message_count(self) -> int:
        return len(self.entries)

    def active_message_count(self) -> int:
        return len([e for e in self.entries if not e.compacted])

    def turn_count(self) -> int:
        return sum(1 for e in self.entries if e.role == "user")

    def active_turn_count(self) -> int:
        return sum(1 for e in self.entries if e.role == "user" and not e.compacted)

    def replay(self) -> tuple[TranscriptEntry, ...]:
        """Replay ALL entries."""
        return tuple(self.entries)

    def replay_active(self) -> tuple[TranscriptEntry, ...]:
        """Replay only active (non-compacted) entries."""
        return tuple(e for e in self.entries if not e.compacted)

    def replay_as_strings(self) -> tuple[str, ...]:
        return tuple(e.content for e in self.entries)

    def get_compaction_summary(self) -> dict[str, Any]:
        """Return summary of compaction state."""
        return {
            "total_messages": len(self.entries),
            "active_messages": len([e for e in self.entries if not e.compacted]),
            "compacted_messages": len([e for e in self.entries if e.compacted]),
            "total_tokens": self.total_tokens(),
            "active_tokens": self.active_tokens(),
            "compacted_tokens": self.total_tokens_compacted,
            "compaction_count": len(self.compacted_ranges),
            "compacted_ranges": [r.to_dict() for r in self.compacted_ranges],
        }

    def flush(self) -> None:
        self.flushed = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [e.to_dict() for e in self.entries],
            "flushed": self.flushed,
            "compacted_ranges": [r.to_dict() for r in self.compacted_ranges],
            "total_tokens_compacted": self.total_tokens_compacted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranscriptStore":
        entries = [TranscriptEntry.from_dict(e) for e in data.get("entries", [])]
        ranges = [CompactedRange.from_dict(r) for r in data.get("compacted_ranges", [])]
        return cls(
            entries=entries,
            flushed=data.get("flushed", False),
            compacted_ranges=ranges,
            total_tokens_compacted=data.get("total_tokens_compacted", 0),
        )


class TokenBudgetTracker:
    """Tracks token usage with real token counting.

    Uses tiktoken for accurate token counting when available,
    falls back to word-based estimation.
    """

    def __init__(
        self,
        model_name: str = "gpt-4",
        context_window: int = 128000,
        reserved_tokens: int = 8000,
    ) -> None:
        self.model_name = model_name
        self.context_window = context_window
        self.reserved_tokens = reserved_tokens
        self._encoder = None
        self._init_encoder()

    def _init_encoder(self) -> None:
        try:
            import tiktoken

            if (
                "gpt-4" in self.model_name.lower()
                or "gpt-3.5" in self.model_name.lower()
            ):
                self._encoder = tiktoken.encoding_for_model(self.model_name)
            else:
                self._encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoder = None

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self._encoder is not None:
            return len(self._encoder.encode(text))
        return max(1, int(len(text) / 2.5))

    def count_messages_tokens(self, messages: list[dict[str, Any]]) -> int:
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.count_tokens(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text", "")
                        total += self.count_tokens(text)
            total += 6
        return total

    def available_budget(self, used_tokens: int) -> int:
        return max(0, self.context_window - self.reserved_tokens - used_tokens)

    def should_compact(
        self,
        used_tokens: int,
        threshold_ratio: float = 0.75,
    ) -> bool:
        budget = self.context_window - self.reserved_tokens
        return used_tokens > budget * threshold_ratio


class TokenCounter:
    """Accurate token counter with tiktoken support and caching.

    Uses tiktoken for precise token counting when available,
    falls back to character-based estimation otherwise.
    Caches token counts for efficiency.
    """

    def __init__(
        self,
        model_name: str = "gpt-4",
        cache_max_size: int = 10000,
    ) -> None:
        self.model_name = model_name
        self._cache_max_size = cache_max_size
        self._encoder = None
        self._cache: dict[str, int] = {}
        self._cache_order: list[str] = []
        self._init_encoder()

    def _init_encoder(self) -> None:
        try:
            import tiktoken

            if (
                "gpt-4" in self.model_name.lower()
                or "gpt-3.5" in self.model_name.lower()
            ):
                self._encoder = tiktoken.encoding_for_model(self.model_name)
            else:
                self._encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoder = None

    def count(self, text: str) -> int:
        """Count tokens in text with caching.

        Args:
            text: Text to count tokens for.

        Returns:
            Token count.
        """
        if not text:
            return 0

        if text in self._cache:
            return self._cache[text]

        token_count = self._count_tokens(text)

        self._cache[text] = token_count
        self._cache_order.append(text)

        if len(self._cache) > self._cache_max_size:
            oldest = self._cache_order.pop(0)
            self._cache.pop(oldest, None)

        return token_count

    def _count_tokens(self, text: str) -> int:
        """Count tokens using tiktoken or fallback estimation."""
        if self._encoder is not None:
            return len(self._encoder.encode(text))

        text_length = len(text)
        if text_length == 0:
            return 0

        cjk_ratio = self._estimate_cjk_ratio(text)
        if cjk_ratio > 0.3:
            chars_per_token = 1.8
        elif cjk_ratio > 0.1:
            chars_per_token = 2.2
        else:
            chars_per_token = 3.5

        return max(1, int(text_length / chars_per_token))

    def _estimate_cjk_ratio(self, text: str) -> float:
        """Estimate the ratio of CJK characters in text."""
        cjk_count = 0
        sample_size = min(len(text), 500)
        for char in text[:sample_size]:
            code_point = ord(char)
            if (
                (0x4E00 <= code_point <= 0x9FFF)
                or (0x3400 <= code_point <= 0x4DBF)
                or (0x20000 <= code_point <= 0x2A6DF)
                or (0x3040 <= code_point <= 0x309F)
                or (0x30A0 <= code_point <= 0x30FF)
            ):
                cjk_count += 1
        return cjk_count / max(sample_size, 1)

    def count_messages(self, messages: list[dict[str, Any]]) -> int:
        """Count tokens for a list of messages.

        Args:
            messages: List of message dicts with 'content' field.

        Returns:
            Total token count including per-message overhead.
        """
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.count(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text", "")
                        total += self.count(text)
            total += 6
        return total

    def clear_cache(self) -> None:
        """Clear the token count cache."""
        self._cache.clear()
        self._cache_order.clear()

    @property
    def cache_size(self) -> int:
        """Current cache size."""
        return len(self._cache)

    @property
    def has_tiktoken(self) -> bool:
        """Whether tiktoken is available."""
        return self._encoder is not None


@dataclass
class ContextWindowConfig:
    """Configuration for context window management."""

    max_tokens: int = 120000
    reserved_tokens: int = 8000
    compact_after_tokens: int = 90000
    compact_after_turns: int = 12
    keep_first_turns: int = 1
    keep_last_turns: int = 4
    summarization_threshold_tokens: int = 100000
    compaction_strategy: CompactionStrategy = CompactionStrategy.HYBRID


@dataclass
class CompactionResult:
    """Result of a compaction operation."""

    entries_marked_compacted: int
    tokens_saved: int
    summary: str = ""
    anchor_message_id: str | None = None
    compacted_range: CompactedRange | None = None


class ContextWindowManager:
    """Manages context window budget and triggers compaction.

    Inspired by claw-code's QueryEnginePort but with token-aware management.
    Compacted messages are marked but preserved for user viewing.
    """

    def __init__(
        self,
        config: ContextWindowConfig | None = None,
        tokenizer: TokenBudgetTracker | None = None,
    ) -> None:
        self.config = config or ContextWindowConfig()
        self.tokenizer = tokenizer or TokenBudgetTracker()
        self.transcript = TranscriptStore()
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.compaction_count: int = 0
        self._last_compaction_turn: int = 0

    def add_message(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        token_count = self.tokenizer.count_tokens(content)
        self.transcript.append(role, content, token_count, metadata)

        if role == "user":
            self.total_input_tokens += token_count
        else:
            self.total_output_tokens += token_count

        return token_count

    def current_usage(self) -> dict[str, Any]:
        compaction_summary = self.transcript.get_compaction_summary()
        return {
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "transcript_tokens": self.transcript.total_tokens(),
            "active_transcript_tokens": self.transcript.active_tokens(),
            "transcript_entries": self.transcript.message_count(),
            "active_transcript_entries": self.transcript.active_message_count(),
            "turn_count": self.transcript.turn_count(),
            "active_turn_count": self.transcript.active_turn_count(),
            "available_budget": self.tokenizer.available_budget(
                self.transcript.active_tokens()
            ),
            "should_compact": self.should_compact(),
            "compaction_summary": compaction_summary,
        }

    def should_compact(self) -> bool:
        if self.transcript.active_turn_count() > self.config.compact_after_turns:
            return True

        if self.transcript.active_tokens() > self.config.compact_after_tokens:
            return True

        return self.tokenizer.should_compact(self.transcript.active_tokens())

    def compact_if_needed(self) -> CompactionResult | None:
        if not self.should_compact():
            return None

        if (
            self.transcript.active_turn_count()
            <= self.config.keep_first_turns + self.config.keep_last_turns
        ):
            return None

        removed = self.transcript.compact_by_tokens(
            max_tokens=self.config.compact_after_tokens,
            keep_first=self.config.keep_first_turns,
            keep_last_n_turns=self.config.keep_last_turns,
        )

        if removed > 0:
            self.compaction_count += 1
            self._last_compaction_turn = self.transcript.active_turn_count()

        last_range = (
            self.transcript.compacted_ranges[-1]
            if self.transcript.compacted_ranges
            else None
        )

        return CompactionResult(
            entries_marked_compacted=removed,
            tokens_saved=self.transcript.total_tokens_compacted,
            summary=f"Marked {removed} messages as compacted. Users can still view them.",
            compacted_range=last_range,
        )

    def compact_with_importance(
        self,
        *,
        model_client: Any | None = None,
        importance_threshold: float = 0.6,
    ) -> CompactionResult | None:
        """Compact messages using importance-based selection.

        Unlike :meth:`compact_if_needed` which uses simple positional
        heuristics, this method scores each message by content value
        (findings, tool calls, recency) and only compacts low-importance
        messages.  When the configured strategy is ``HYBRID`` or
        ``LLM_DRIVEN``, an LLM client can be supplied to produce a
        semantic summary of the compacted messages.

        Args:
            model_client: Optional LLM client for semantic summarization.
            importance_threshold: Messages scoring below this are compacted.

        Returns:
            A :class:`CompactionResult` if compaction was performed, else
            ``None``.
        """
        if not self.should_compact():
            return None

        active = self.transcript.active_entries()
        if len(active) <= self.config.keep_first_turns + self.config.keep_last_turns:
            return None

        # Build lightweight dicts for importance scoring
        active_msgs: list[dict[str, Any]] = []
        turn_counter = 0
        for i, entry in enumerate(active):
            if entry.role == "user":
                turn_counter += 1
            active_msgs.append({
                "index": i,
                "role": entry.role,
                "content": entry.content,
                "turn_number": turn_counter,
            })

        keep_msgs, compact_msgs = select_messages_for_compaction(
            active_msgs,
            keep_count=self.config.keep_last_turns + self.config.keep_first_turns,
            importance_threshold=importance_threshold,
        )

        if not compact_msgs:
            return None

        # Mark compacted entries in the transcript store
        compact_indices = {m["index"] for m in compact_msgs}
        entries_to_compact = [active[idx] for idx in sorted(compact_indices) if idx < len(active)]

        if not entries_to_compact:
            return None

        tokens_compacted = sum(e.token_count for e in entries_to_compact)
        turns_compacted = sum(1 for e in entries_to_compact if e.role == "user")

        for entry in entries_to_compact:
            entry.compacted = True

        # Build semantic summary when LLM is available and strategy allows it
        summary_text = ""
        if model_client is not None and self.config.compaction_strategy in (
            CompactionStrategy.LLM_DRIVEN,
            CompactionStrategy.HYBRID,
        ):
            try:
                # Import here to avoid circular imports at module level
                from .compaction import build_semantic_compact_summary

                compact_dicts = [
                    {"role": e.role, "content": e.content}
                    for e in entries_to_compact
                ]
                summary_text = self._run_sync(
                    build_semantic_compact_summary(
                        compact_dicts,
                        model_client=model_client,
                    )
                )
            except Exception:
                summary_text = ""

        start_idx = (
            self.transcript.entries.index(entries_to_compact[0])
            if entries_to_compact
            else 0
        )
        end_idx = (
            self.transcript.entries.index(entries_to_compact[-1]) + 1
            if entries_to_compact
            else 0
        )

        range_summary = summary_text or (
            f"Compacted {len(entries_to_compact)} messages "
            f"({turns_compacted} turns, ~{tokens_compacted} tokens) "
            f"via importance scoring"
        )

        self.transcript.compacted_ranges.append(
            CompactedRange(
                start_index=start_idx,
                end_index=end_idx,
                token_count=tokens_compacted,
                turn_count=turns_compacted,
                summary=range_summary,
            )
        )

        self.transcript.total_tokens_compacted += tokens_compacted
        self.compaction_count += 1
        self._last_compaction_turn = self.transcript.active_turn_count()

        last_range = self.transcript.compacted_ranges[-1] if self.transcript.compacted_ranges else None

        return CompactionResult(
            entries_marked_compacted=len(entries_to_compact),
            tokens_saved=self.transcript.total_tokens_compacted,
            summary=f"Importance-based compaction: {len(entries_to_compact)} messages marked.",
            compacted_range=last_range,
        )

    @staticmethod
    def _run_sync(coro: Any) -> str:
        """Helper to run an async coroutine from sync context.

        If an event loop is already running, create a new thread with its
        own loop.  Otherwise, use ``asyncio.run``.
        """
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return asyncio.run(coro)

    def get_context_for_model(
        self,
        system_prompt: str,
        memory: LayeredConversationMemory | None = None,
        pinned_context: str | None = None,
    ) -> list[dict[str, str]]:
        """Get messages to send to model - only ACTIVE (non-compacted) entries."""
        messages: list[dict[str, str]] = []

        system_content = system_prompt
        if memory and not memory.is_empty():
            memory_content = memory.render_for_model()
            if memory_content.strip():
                system_content += f"\n\n{memory_content}"
        if pinned_context and pinned_context.strip():
            system_content += f"\n\n{pinned_context}"

        messages.append({"role": "system", "content": system_content})

        for entry in self.transcript.replay_active():
            messages.append(
                {
                    "role": entry.role,
                    "content": entry.content,
                }
            )

        return messages

    def get_full_history(self) -> list[TranscriptEntry]:
        """Get ALL entries including compacted ones - for user viewing."""
        return list(self.transcript.replay())

    def get_compacted_history(self) -> list[TranscriptEntry]:
        """Get only compacted entries - for user viewing."""
        return self.transcript.compacted_entries()

    def estimate_context_tokens(
        self,
        system_prompt: str,
        memory: LayeredConversationMemory | None = None,
        pinned_context: str | None = None,
    ) -> int:
        total = self.tokenizer.count_tokens(system_prompt)

        if memory and not memory.is_empty():
            memory_content = memory.render_for_model()
            total += self.tokenizer.count_tokens(memory_content)

        if pinned_context:
            total += self.tokenizer.count_tokens(pinned_context)

        total += self.transcript.active_tokens()

        return total

    def reset(self) -> None:
        self.transcript = TranscriptStore()
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.compaction_count = 0
        self._last_compaction_turn = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": {
                "max_tokens": self.config.max_tokens,
                "reserved_tokens": self.config.reserved_tokens,
                "compact_after_tokens": self.config.compact_after_tokens,
                "compact_after_turns": self.config.compact_after_turns,
            },
            "transcript": self.transcript.to_dict(),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "compaction_count": self.compaction_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextWindowManager":
        config_data = data.get("config", {})
        config = ContextWindowConfig(
            max_tokens=config_data.get("max_tokens", 120000),
            reserved_tokens=config_data.get("reserved_tokens", 8000),
            compact_after_tokens=config_data.get("compact_after_tokens", 90000),
            compact_after_turns=config_data.get("compact_after_turns", 12),
        )
        manager = cls(config=config)
        manager.transcript = TranscriptStore.from_dict(data.get("transcript", {}))
        manager.total_input_tokens = data.get("total_input_tokens", 0)
        manager.total_output_tokens = data.get("total_output_tokens", 0)
        manager.compaction_count = data.get("compaction_count", 0)
        return manager


__all__ = [
    "TranscriptEntry",
    "TranscriptStore",
    "CompactedRange",
    "TokenBudgetTracker",
    "TokenCounter",
    "ContextWindowConfig",
    "ContextWindowManager",
    "CompactionResult",
]
