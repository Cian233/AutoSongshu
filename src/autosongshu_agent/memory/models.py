from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ..utils import dedupe_strings, normalize_text, truncate_text


# ── Model Pricing Table (USD per 1M tokens) ──────────────────────
# Sources: OpenAI, Anthropic, Google pricing pages (2025-06).
MODEL_PRICING: dict[str, dict[str, float]] = {
    # OpenAI models
    "gpt-4.1-mini": {"input": 1.50, "output": 6.00, "cache_read": 0.375, "cache_write": 1.50},
    "gpt-4.1": {"input": 2.00, "output": 8.00, "cache_read": 0.50, "cache_write": 2.00},
    "gpt-4.1-nano": {"input": 0.10, "output": 0.40, "cache_read": 0.025, "cache_write": 0.10},
    "gpt-4o": {"input": 2.50, "output": 10.00, "cache_read": 1.25, "cache_write": 2.50},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075, "cache_write": 0.15},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00, "cache_read": 5.00, "cache_write": 10.00},
    "gpt-4": {"input": 30.00, "output": 60.00, "cache_read": 15.00, "cache_write": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50, "cache_read": 0.25, "cache_write": 0.50},
    "o1": {"input": 15.00, "output": 60.00, "cache_read": 7.50, "cache_write": 15.00},
    "o1-mini": {"input": 3.00, "output": 12.00, "cache_read": 1.50, "cache_write": 3.00},
    "o3-mini": {"input": 1.10, "output": 4.40, "cache_read": 0.55, "cache_write": 1.10},
    # Anthropic models
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-5-haiku-20241022": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_write": 1.25},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_write": 18.75},
    # Google models
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00, "cache_read": 0.625, "cache_write": 1.25},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60, "cache_read": 0.075, "cache_write": 0.15},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40, "cache_read": 0.025, "cache_write": 0.10},
}

# Fallback pricing when model is not in the table
_DEFAULT_PRICING = {"input": 2.00, "output": 8.00, "cache_read": 1.00, "cache_write": 2.00}


def _match_model_pricing(model_name: str) -> dict[str, float]:
    """Find the best pricing match for a model name (exact or prefix)."""
    name = (model_name or "").strip().lower()
    if not name:
        return _DEFAULT_PRICING
    # Exact match
    if name in MODEL_PRICING:
        return MODEL_PRICING[name]
    # Prefix match (e.g. "gpt-4.1-mini-2025-04-14" -> "gpt-4.1-mini")
    for key, pricing in MODEL_PRICING.items():
        if name.startswith(key) or key.startswith(name):
            return pricing
    return _DEFAULT_PRICING


def estimate_token_cost(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Estimate USD cost for token usage given a model name."""
    pricing = _match_model_pricing(model_name)
    cost = 0.0
    # Cache read tokens are cheaper
    cost += (cache_read_tokens / 1_000_000) * pricing["cache_read"]
    # Cache creation tokens use cache_write price
    cost += (cache_creation_tokens / 1_000_000) * pricing["cache_write"]
    # Remaining input tokens (non-cached) use input price
    non_cached_input = max(0, input_tokens - cache_read_tokens - cache_creation_tokens)
    cost += (non_cached_input / 1_000_000) * pricing["input"]
    # Output tokens
    cost += (output_tokens / 1_000_000) * pricing["output"]
    return cost


class CostEvent(BaseModel):
    label: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    timestamp: str = Field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )


class CostTracker(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0
    events: list[CostEvent] = Field(default_factory=list)
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cost: float = 0.0,
        label: str = "model_call",
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_cost += cost
        self.cache_creation_input_tokens += cache_creation_input_tokens
        self.cache_read_input_tokens += cache_read_input_tokens
        self.events.append(
            CostEvent(
                label=label,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                cache_creation_input_tokens=cache_creation_input_tokens,
                cache_read_input_tokens=cache_read_input_tokens,
            )
        )

    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def cache_hit_ratio(self) -> float | None:
        """Return cache hit ratio as a float 0-1, or None if no cache data."""
        total_cached = self.cache_creation_input_tokens + self.cache_read_input_tokens
        if total_cached == 0:
            return None
        if self.input_tokens == 0:
            return None
        return self.cache_read_input_tokens / self.input_tokens

    def summary_dict(self, model_name: str = "") -> dict[str, Any]:
        result: dict[str, Any] = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens(),
            "total_cost": self.total_cost,
            "event_count": len(self.events),
        }
        # Cache statistics
        if self.cache_creation_input_tokens > 0 or self.cache_read_input_tokens > 0:
            result["cache_creation_input_tokens"] = self.cache_creation_input_tokens
            result["cache_read_input_tokens"] = self.cache_read_input_tokens
            ratio = self.cache_hit_ratio()
            if ratio is not None:
                result["cache_hit_ratio"] = round(ratio, 4)
        # Estimated cost based on model pricing
        if model_name:
            estimated = estimate_token_cost(
                model_name=model_name,
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                cache_read_tokens=self.cache_read_input_tokens,
                cache_creation_tokens=self.cache_creation_input_tokens,
            )
            result["estimated_cost_usd"] = round(estimated, 4)
        return result

    def as_markdown(self) -> str:
        lines = [
            "# Token Usage Summary",
            "",
            f"- Input Tokens: {self.input_tokens}",
            f"- Output Tokens: {self.output_tokens}",
            f"- Total Tokens: {self.total_tokens()}",
            f"- Total Cost: ${self.total_cost:.4f}",
            f"- Events: {len(self.events)}",
            "",
            "## Event History",
        ]
        for event in self.events[-20:]:
            lines.append(
                f"- [{event.timestamp}] {event.label}: "
                f"{event.input_tokens} in / {event.output_tokens} out"
            )
        return "\n".join(lines)


class MemoryNote(BaseModel):
    statement: str
    evidence: list[str] = Field(default_factory=list)

    def normalized_statement(self) -> str:
        return normalize_text(self.statement)

    def normalized_evidence(self) -> list[str]:
        return dedupe_strings(self.evidence)


class SessionHandoffCard(BaseModel):
    task: str = ""
    status: str = ""
    current_focus: str = ""
    pending_work: list[str] = Field(default_factory=list)
    recent_requests: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    discoveries: list[str] = Field(default_factory=list)
    accomplished: list[str] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    target_urls: list[str] = Field(default_factory=list)
    confirmed_facts: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    avoid_repeating: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    updated_at: str | None = None

    def is_empty(self) -> bool:
        return not any(
            (
                self.task.strip(),
                self.status.strip(),
                self.current_focus.strip(),
                self.pending_work,
                self.recent_requests,
                self.instructions,
                self.discoveries,
                self.accomplished,
                self.relevant_files,
                self.target_urls,
                self.confirmed_facts,
                self.open_questions,
                self.avoid_repeating,
                self.next_steps,
            ),
        )

    def render_for_model(self) -> str:
        sections = [
            "OpenCode-style compact session handoff. Continue the same task from this card instead of re-deriving the context from scratch.",
        ]
        if self.task.strip():
            sections.append(f"Goal:\n{self.task.strip()}")
        if self.instructions:
            sections.append(
                "Instructions:\n" + "\n".join(f"- {item}" for item in self.instructions)
            )
        if self.status.strip():
            sections.append(f"Current status:\n{self.status.strip()}")
        if self.current_focus.strip():
            sections.append(f"Current focus:\n{self.current_focus.strip()}")
        if self.pending_work:
            sections.append(
                "Pending work:\n" + "\n".join(f"- {item}" for item in self.pending_work)
            )
        if self.recent_requests:
            sections.append(
                "Recent requests:\n"
                + "\n".join(f"- {item}" for item in self.recent_requests)
            )
        if self.discoveries:
            sections.append(
                "Discoveries:\n" + "\n".join(f"- {item}" for item in self.discoveries)
            )
        if self.accomplished:
            sections.append(
                "Accomplished:\n" + "\n".join(f"- {item}" for item in self.accomplished)
            )
        if self.relevant_files:
            sections.append(
                "Relevant files and directories:\n"
                + "\n".join(f"- {item}" for item in self.relevant_files)
            )
        if self.target_urls:
            sections.append(
                "Target URLs:\n" + "\n".join(f"- {item}" for item in self.target_urls)
            )
        if self.confirmed_facts:
            sections.append(
                "Confirmed facts:\n"
                + "\n".join(f"- {item}" for item in self.confirmed_facts)
            )
        if self.open_questions:
            sections.append(
                "Open questions:\n"
                + "\n".join(f"- {item}" for item in self.open_questions)
            )
        if self.avoid_repeating:
            sections.append(
                "Do not repeat unchanged:\n"
                + "\n".join(f"- {item}" for item in self.avoid_repeating)
            )
        if self.next_steps:
            sections.append(
                "Next best steps:\n"
                + "\n".join(f"- {item}" for item in self.next_steps)
            )
        sections.append(
            "Preserve the primary goal. Treat short follow-up messages as deltas or instructions, not as a brand-new task."
        )
        sections.append(
            "If the tool, script, payload, URL, or argument set has not changed and there is no new evidence, do not retry it unchanged."
        )
        return "\n\n".join(section for section in sections if section.strip()).strip()


class LayeredConversationMemory(BaseModel):
    summary: str = ""
    continuation: str = ""
    stable_conclusions: list[MemoryNote] = Field(default_factory=list)
    validated_findings: list[MemoryNote] = Field(default_factory=list)
    active_leads: list[MemoryNote] = Field(default_factory=list)
    dead_ends: list[MemoryNote] = Field(default_factory=list)
    next_focus: list[str] = Field(default_factory=list)
    recent_progress: str = ""
    handoff: SessionHandoffCard = Field(default_factory=SessionHandoffCard)
    anchor_message_id: str | None = None
    updated_at: str | None = None

    def is_empty(self) -> bool:
        return not any(
            (
                self.summary.strip(),
                self.continuation.strip(),
                self.recent_progress.strip(),
                self.stable_conclusions,
                self.validated_findings,
                self.active_leads,
                self.dead_ends,
                self.next_focus,
                not self.handoff.is_empty(),
            ),
        )

    def render_for_model(self) -> str:
        from .utils import _render_notes

        sections: list[str] = []
        if self.continuation.strip():
            sections.append(self.continuation.strip())
        if not self.handoff.is_empty():
            sections.append(self.handoff.render_for_model())
        if self.summary.strip() or self.recent_progress.strip():
            sections.append(self.render_handoff_for_model())
        if self.validated_findings:
            findings_lines = ["Validated findings:"]
            for note in self.validated_findings:
                findings_lines.append(f"- {note.normalized_statement()}")
            sections.append("\n".join(findings_lines))

        return "\n\n".join(section for section in sections if section.strip()).strip()

    def render_handoff_for_model(self) -> str:
        from .utils import _render_notes

        sections: list[str] = [
            "Session handoff summary. Continue from the state below instead of restarting the task analysis.",
        ]
        if self.summary.strip():
            sections.append(f"Summary:\n{self.summary.strip()}")
        if self.recent_progress.strip():
            sections.append(f"Recent progress:\n{self.recent_progress.strip()}")
        if self.stable_conclusions:
            sections.append(_render_notes("Confirmed facts", self.stable_conclusions))
        if self.active_leads:
            sections.append(_render_notes("Active leads", self.active_leads))
        if self.dead_ends:
            sections.append(_render_notes("Avoid repeating", self.dead_ends))
        if self.next_focus:
            sections.append(
                "Next priorities:\n"
                + "\n".join(
                    f"- {item}" for item in self.next_focus if str(item).strip()
                )
            )
        return "\n\n".join(section for section in sections if section.strip()).strip()


class MemorySynthesisPayload(BaseModel):
    summary: str = ""
    stable_conclusions: list[MemoryNote] = Field(default_factory=list)
    active_leads: list[MemoryNote] = Field(default_factory=list)
    dead_ends: list[MemoryNote] = Field(default_factory=list)
    next_focus: list[str] = Field(default_factory=list)
    recent_progress: str = ""
    handoff: SessionHandoffCard | None = None


__all__ = [
    "CostEvent",
    "CostTracker",
    "MemoryNote",
    "SessionHandoffCard",
    "LayeredConversationMemory",
    "MemorySynthesisPayload",
    "MODEL_PRICING",
    "estimate_token_cost",
]
