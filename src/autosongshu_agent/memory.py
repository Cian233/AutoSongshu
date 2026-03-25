from __future__ import annotations

import json
import re
from collections import Counter
from copy import deepcopy
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .message_blocks import assistant_preview_text, normalize_message_content
from .models import Finding

_ABSOLUTE_URL_PATTERN = re.compile(r"https?://[^\s\"'<>\\)]+", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().split())


def _truncate(text: str, limit: int = 320) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return f"{value[: limit - 3]}..."


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = _normalize_text(raw)
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _merge_priority_strings(primary: list[str], secondary: list[str], *, limit: int = 8) -> list[str]:
    return _dedupe_strings([*primary, *secondary])[:limit]


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for raw in _ABSOLUTE_URL_PATTERN.findall(str(text or "")):
        candidate = raw.rstrip(".,;:!?)]}>'\"")
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def _user_text_preview(content: list[dict[str, Any]]) -> str:
    text = "\n\n".join(
        str(part.get("text") or "").strip()
        for part in content
        if str(part.get("type") or "").strip().lower() == "input_text"
        and str(part.get("text") or "").strip()
    )
    return _truncate(text, 600)


class MemoryNote(BaseModel):
    statement: str
    evidence: list[str] = Field(default_factory=list)

    def normalized_statement(self) -> str:
        return _normalize_text(self.statement)

    def normalized_evidence(self) -> list[str]:
        return _dedupe_strings(self.evidence)


class SessionHandoffCard(BaseModel):
    task: str = ""
    status: str = ""
    current_focus: str = ""
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
            sections.append("Instructions:\n" + "\n".join(f"- {item}" for item in self.instructions))
        if self.status.strip():
            sections.append(f"Current status:\n{self.status.strip()}")
        if self.current_focus.strip():
            sections.append(f"Current focus:\n{self.current_focus.strip()}")
        if self.discoveries:
            sections.append("Discoveries:\n" + "\n".join(f"- {item}" for item in self.discoveries))
        if self.accomplished:
            sections.append("Accomplished:\n" + "\n".join(f"- {item}" for item in self.accomplished))
        if self.relevant_files:
            sections.append("Relevant files and directories:\n" + "\n".join(f"- {item}" for item in self.relevant_files))
        if self.target_urls:
            sections.append("Target URLs:\n" + "\n".join(f"- {item}" for item in self.target_urls))
        if self.confirmed_facts:
            sections.append("Confirmed facts:\n" + "\n".join(f"- {item}" for item in self.confirmed_facts))
        if self.open_questions:
            sections.append("Open questions:\n" + "\n".join(f"- {item}" for item in self.open_questions))
        if self.avoid_repeating:
            sections.append("Do not repeat unchanged:\n" + "\n".join(f"- {item}" for item in self.avoid_repeating))
        if self.next_steps:
            sections.append("Next best steps:\n" + "\n".join(f"- {item}" for item in self.next_steps))
        sections.append(
            "Preserve the primary goal. Treat short follow-up messages as deltas or instructions, not as a brand-new task."
        )
        sections.append(
            "If the tool, script, payload, URL, or argument set has not changed and there is no new evidence, do not retry it unchanged."
        )
        return "\n\n".join(section for section in sections if section.strip()).strip()


class LayeredConversationMemory(BaseModel):
    summary: str = ""
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
        sections: list[str] = []
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
            sections.append("Next priorities:\n" + "\n".join(f"- {item}" for item in self.next_focus if str(item).strip()))
        return "\n\n".join(section for section in sections if section.strip()).strip()


class MemorySynthesisPayload(BaseModel):
    summary: str = ""
    stable_conclusions: list[MemoryNote] = Field(default_factory=list)
    active_leads: list[MemoryNote] = Field(default_factory=list)
    dead_ends: list[MemoryNote] = Field(default_factory=list)
    next_focus: list[str] = Field(default_factory=list)
    recent_progress: str = ""
    handoff: SessionHandoffCard | None = None


def _render_notes(title: str, notes: list[MemoryNote]) -> str:
    lines = [f"{title}:"]
    for note in notes:
        statement = note.normalized_statement()
        if not statement:
            continue
        lines.append(f"- {statement}")
        evidence = note.normalized_evidence()
        if evidence:
            lines.append(f"  Evidence: {'; '.join(evidence)}")
    return "\n".join(lines)


def _dedupe_notes(notes: list[MemoryNote]) -> list[MemoryNote]:
    deduped: list[MemoryNote] = []
    seen: set[str] = set()
    for note in notes:
        statement = note.normalized_statement()
        if not statement:
            continue
        key = statement.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(MemoryNote(statement=statement, evidence=note.normalized_evidence()))
    return deduped


def sync_validated_findings(findings: list[Finding] | list[dict[str, Any]]) -> list[MemoryNote]:
    notes: list[MemoryNote] = []
    for raw in findings:
        finding = raw if isinstance(raw, Finding) else Finding.model_validate(raw)
        if str(finding.status or "").strip().lower() != "validated":
            continue
        title = _normalize_text(finding.title)
        summary = _normalize_text(finding.summary)
        if not title and not summary:
            continue
        statement = title if not summary else f"{title}: {summary}"
        evidence: list[str] = []
        if finding.url:
            evidence.append(f"URL: {finding.url}")
        evidence.extend(_truncate(item, 220) for item in finding.evidence if _normalize_text(item))
        notes.append(MemoryNote(statement=statement, evidence=evidence))
    return _dedupe_notes(notes)


def completed_messages_after_anchor(
    messages: list[Any],
    anchor_message_id: str | None,
    *,
    skip_message_ids: set[str] | None = None,
) -> list[Any]:
    skipped = skip_message_ids or set()
    completed = [
        message
        for message in messages
        if getattr(message, "status", "") == "completed" and getattr(message, "id", "") not in skipped
    ]
    if not anchor_message_id:
        return completed
    for index, message in enumerate(completed):
        if getattr(message, "id", "") == anchor_message_id:
            return completed[index + 1 :]
    return completed


def build_memory_transcript_payload(messages: list[Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in messages:
        role = str(getattr(message, "role", "assistant"))
        content = normalize_message_content(deepcopy(getattr(message, "content", []) or []), role=role)
        payload.append(
            {
                "id": str(getattr(message, "id", "")),
                "role": role,
                "status": str(getattr(message, "status", "")),
                "content": content,
                "text": assistant_preview_text(content) if role == "assistant" else _user_text_preview(content),
                "tool_activity": _tool_activity_digest(content) if role == "assistant" else [],
            },
        )
    return payload


def _tool_activity_digest(content: list[dict[str, Any]]) -> list[dict[str, Any]]:
    call_counter: Counter[str] = Counter()
    result_counter: Counter[str] = Counter()
    result_samples: dict[str, str] = {}

    for part in content:
        part_type = str(part.get("type") or "").strip().lower()
        if part_type == "tool_call":
            key = f"{part.get('name') or 'tool'}::{_stable_json(part.get('arguments') or {})}"
            call_counter[key] += 1
            continue

        if part_type == "tool_result":
            result_text = _truncate(
                "\n".join(
                    str(item.get("text") or "").strip()
                    for item in part.get("content") or []
                    if str(item.get("type") or "").strip().lower() == "output_text"
                    and str(item.get("text") or "").strip()
                ),
                280,
            )
            key = f"{part.get('name') or 'tool'}::{result_text}"
            result_counter[key] += 1
            result_samples.setdefault(key, result_text)

    digest: list[dict[str, Any]] = []
    for key, count in sorted(call_counter.items()):
        name, serialized_arguments = key.split("::", 1)
        digest.append(
            {
                "type": "tool_call",
                "name": name,
                "arguments": json.loads(serialized_arguments),
                "count": count,
            },
        )
    for key, count in sorted(result_counter.items()):
        name, _sample = key.split("::", 1)
        digest.append(
            {
                "type": "tool_result",
                "name": name,
                "result_preview": result_samples.get(key, ""),
                "count": count,
            },
        )
    return digest


def _dead_end_notes_from_transcript(transcript_payload: list[dict[str, Any]]) -> list[MemoryNote]:
    notes: list[MemoryNote] = []
    for entry in transcript_payload:
        if str(entry.get("role") or "").strip().lower() != "assistant":
            continue
        for activity in entry.get("tool_activity") or []:
            count = int(activity.get("count") or 0)
            if count <= 1:
                continue
            tool_name = str(activity.get("name") or "tool")
            if str(activity.get("type") or "").strip().lower() == "tool_call":
                arguments_preview = _truncate(_stable_json(activity.get("arguments") or {}), 220)
                notes.append(
                    MemoryNote(
                        statement=f"Repeated identical tool call with unchanged arguments: {tool_name}",
                        evidence=[f"Arguments: {arguments_preview}", f"Repeat count: {count}"],
                    ),
                )
                continue
            result_preview = _truncate(str(activity.get("result_preview") or ""), 220)
            notes.append(
                MemoryNote(
                    statement=f"Repeated identical tool result: {tool_name}",
                    evidence=[f"Result preview: {result_preview or 'empty result'}", f"Repeat count: {count}"],
                ),
            )
    return notes


_FILE_ARGUMENT_KEYS = frozenset(
    {
        "path",
        "script_path",
        "file",
        "file_path",
        "directory",
        "dir",
        "output_path",
        "workspace_dir",
        "root_dir",
    }
)


def _normalize_file_hint(value: Any) -> str:
    candidate = str(value or "").strip().replace("\\", "/")
    if not candidate:
        return ""
    if candidate.startswith(("http://", "https://")):
        return ""
    if len(candidate) > 220:
        return ""
    return candidate


def _extract_relevant_files_from_transcript(transcript_payload: list[dict[str, Any]]) -> list[str]:
    hints: list[str] = []
    for entry in transcript_payload:
        for part in entry.get("content") or []:
            if str(part.get("type") or "").strip().lower() != "tool_call":
                continue
            arguments = part.get("arguments") if isinstance(part.get("arguments"), dict) else {}
            for key in _FILE_ARGUMENT_KEYS:
                if key not in arguments:
                    continue
                normalized = _normalize_file_hint(arguments.get(key))
                if normalized:
                    hints.append(normalized)
    return _dedupe_strings(hints)[:10]


def _instruction_hints_from_transcript(transcript_payload: list[dict[str, Any]], *, limit: int = 6) -> list[str]:
    user_texts = [
        _truncate(str(entry.get("text") or ""), 220)
        for entry in transcript_payload
        if str(entry.get("role") or "").strip().lower() == "user" and _normalize_text(str(entry.get("text") or ""))
    ]
    return _dedupe_strings(user_texts)[-limit:]


def _discovery_hints_from_transcript(transcript_payload: list[dict[str, Any]], *, limit: int = 4) -> list[str]:
    assistant_texts = [
        _truncate(str(entry.get("text") or ""), 220)
        for entry in transcript_payload
        if str(entry.get("role") or "").strip().lower() == "assistant" and _normalize_text(str(entry.get("text") or ""))
    ]
    return _dedupe_strings(assistant_texts)[-limit:]


def _accomplished_hints_from_transcript(transcript_payload: list[dict[str, Any]]) -> list[str]:
    tool_names: list[str] = []
    for entry in transcript_payload:
        if str(entry.get("role") or "").strip().lower() != "assistant":
            continue
        for activity in entry.get("tool_activity") or []:
            name = _normalize_text(str(activity.get("name") or ""))
            if name:
                tool_names.append(name)
    unique_names = _dedupe_strings(tool_names)
    if not unique_names:
        return []
    return [f"Recently executed or inspected via tools: {', '.join(unique_names[:8])}"]


def _build_handoff_card(
    existing_handoff: SessionHandoffCard,
    *,
    task: str = "",
    status: str = "",
    current_focus: str = "",
    instructions: list[str] | None = None,
    discoveries: list[str] | None = None,
    accomplished: list[str] | None = None,
    relevant_files: list[str] | None = None,
    target_urls: list[str] | None = None,
    confirmed_facts: list[str] | None = None,
    open_questions: list[str] | None = None,
    avoid_repeating: list[str] | None = None,
    next_steps: list[str] | None = None,
) -> SessionHandoffCard:
    return SessionHandoffCard(
        task=_normalize_text(task) or existing_handoff.task,
        status=_normalize_text(status) or existing_handoff.status,
        current_focus=_normalize_text(current_focus) or existing_handoff.current_focus,
        instructions=_merge_priority_strings(list(instructions or []), list(existing_handoff.instructions or [])),
        discoveries=_merge_priority_strings(list(discoveries or []), list(existing_handoff.discoveries or [])),
        accomplished=_merge_priority_strings(list(accomplished or []), list(existing_handoff.accomplished or [])),
        relevant_files=_merge_priority_strings(list(relevant_files or []), list(existing_handoff.relevant_files or []), limit=10),
        target_urls=_merge_priority_strings(list(target_urls or []), list(existing_handoff.target_urls or []), limit=10),
        confirmed_facts=_merge_priority_strings(list(confirmed_facts or []), list(existing_handoff.confirmed_facts or []), limit=10),
        open_questions=_merge_priority_strings(list(open_questions or []), list(existing_handoff.open_questions or []), limit=10),
        avoid_repeating=_merge_priority_strings(list(avoid_repeating or []), list(existing_handoff.avoid_repeating or []), limit=10),
        next_steps=_merge_priority_strings(list(next_steps or []), list(existing_handoff.next_steps or [])),
        updated_at=now_iso(),
    )


def build_memory_fallback(
    existing_memory: LayeredConversationMemory,
    transcript_payload: list[dict[str, Any]],
    validated_findings: list[MemoryNote],
    anchor_message_id: str | None,
) -> LayeredConversationMemory:
    updated = existing_memory.model_copy(deep=True)
    updated.validated_findings = _dedupe_notes(validated_findings)

    assistant_entries = [item for item in transcript_payload if str(item.get("role") or "").strip().lower() == "assistant"]
    user_entries = [item for item in transcript_payload if str(item.get("role") or "").strip().lower() == "user"]

    latest_assistant = assistant_entries[-1] if assistant_entries else None
    latest_user = user_entries[-1] if user_entries else None
    latest_assistant_text = _normalize_text(str((latest_assistant or {}).get("text") or ""))
    latest_user_text = _normalize_text(str((latest_user or {}).get("text") or ""))
    original_task = _normalize_text(existing_memory.handoff.task)
    if not original_task and user_entries:
        original_task = _normalize_text(str(user_entries[0].get("text") or ""))

    if latest_assistant_text:
        updated.recent_progress = _truncate(latest_assistant_text, 420)

    updated.dead_ends = _dedupe_notes([*updated.dead_ends, *_dead_end_notes_from_transcript(transcript_payload)])

    if not updated.summary.strip():
        if updated.validated_findings:
            updated.summary = f"Currently confirmed {len(updated.validated_findings)} validated findings."
        elif latest_assistant_text:
            updated.summary = _truncate(latest_assistant_text, 220)

    if not updated.next_focus and latest_user_text:
        updated.next_focus = [_truncate(f"Continue from the latest user objective: {latest_user_text}", 220)]

    target_urls: list[str] = []
    for entry in transcript_payload:
        target_urls.extend(_extract_urls(str(entry.get("text") or "")))
    for note in updated.validated_findings:
        for evidence in note.normalized_evidence():
            target_urls.extend(_extract_urls(evidence))

    confirmed_facts = [note.normalized_statement() for note in [*updated.stable_conclusions, *updated.validated_findings]]
    open_questions = [note.normalized_statement() for note in updated.active_leads]
    avoid_repeating = [note.normalized_statement() for note in updated.dead_ends]
    next_steps = [item.strip() for item in updated.next_focus if str(item).strip()]
    instructions = _instruction_hints_from_transcript(transcript_payload)
    discoveries = _merge_priority_strings(
        [*confirmed_facts, *_discovery_hints_from_transcript(transcript_payload)],
        [],
        limit=8,
    )
    accomplished = _accomplished_hints_from_transcript(transcript_payload)
    relevant_files = _extract_relevant_files_from_transcript(transcript_payload)

    updated.handoff = _build_handoff_card(
        existing_memory.handoff,
        task=original_task or updated.summary,
        status=updated.summary,
        current_focus=latest_user_text or updated.recent_progress or latest_assistant_text,
        instructions=instructions,
        discoveries=discoveries,
        accomplished=accomplished,
        relevant_files=relevant_files,
        target_urls=target_urls,
        confirmed_facts=confirmed_facts,
        open_questions=open_questions,
        avoid_repeating=avoid_repeating,
        next_steps=next_steps,
    )

    updated.anchor_message_id = anchor_message_id or updated.anchor_message_id
    updated.updated_at = now_iso()
    return updated
