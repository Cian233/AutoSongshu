from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..utils import dedupe_strings, normalize_text, truncate_text


class CostTracker(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost: float = 0.0

    def add_usage(self, input_tokens: int, output_tokens: int, cost: float = 0.0) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_cost += cost


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
                "Recent requests:\n" + "\n".join(f"- {item}" for item in self.recent_requests)
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
    "CostTracker",
    "MemoryNote",
    "SessionHandoffCard",
    "LayeredConversationMemory",
    "MemorySynthesisPayload",
]
