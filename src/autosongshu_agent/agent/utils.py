from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import Any

from agentscope.message import Msg

from ..message_blocks import (
    assistant_content_from_blocks,
    assistant_preview_text,
    normalize_content_item,
    unresolved_tool_call_ids,
)
from ..utils import stable_fingerprint, tool_call_signature, tool_result_signature
from .prompts import (
    _CONTINUATION_HINT_PATTERNS,
    _SANDBOX_SCRIPT_MUTATION_TOOLS,
)


def _make_agentscope_output_safe(agent):
    agent._disable_console_output = True
    return agent


def _parse_skill_command(user_message: str):
    from .coordinator import SkillCommand

    lines = user_message.strip().splitlines()
    requested_names: list[str] = []
    consume_until = 0

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            consume_until = index + 1
            continue
        if not line.lower().startswith("/skill "):
            break
        consume_until = index + 1
        names_text = line[7:].strip()
        if names_text:
            requested_names.extend(
                part.strip() for part in names_text.split(",") if part.strip()
            )

    remaining_message = "\n".join(lines[consume_until:]).strip()
    return SkillCommand(
        requested_names=requested_names, remaining_message=remaining_message
    )


def _build_skill_routing_hint(user_message: str, skill_report) -> str | None:
    lowered = user_message.lower()
    available = {skill.name.lower(): skill for skill in skill_report.loaded}
    hints: list[str] = []
    if "sqlmap-sqli" in available and any(
        keyword in lowered
        for keyword in (
            "sql injection",
            "sqli",
            "union select",
            "database error",
            "sql syntax",
            "\u6ce8\u5165",
            "sql \u6f0f\u6d1e",
            "sql\u6f0f\u6d1e",
        )
    ):
        hints.append(
            "- SQL injection verification tasks: prefer the packaged `sqlmap-sqli` workflow."
        )
    if "dirsearch-recon" in available and any(
        keyword in lowered
        for keyword in (
            "dirsearch",
            "directory",
            "content discovery",
            "hidden file",
            "hidden path",
            "\u8def\u5f84",
            "\u76ee\u5f55",
            "\u679a\u4e3e",
        )
    ):
        hints.append(
            "- Path discovery tasks: prefer the packaged `dirsearch-recon` workflow."
        )
    if "nmap-recon" in available and any(
        keyword in lowered
        for keyword in (
            "nmap",
            "port scan",
            "port scanning",
            "service enumeration",
            "host discovery",
            "\u7aef\u53e3",
            "\u4e3b\u673a",
            "\u670d\u52a1\u679a\u4e3e",
        )
    ):
        hints.append(
            "- Host, port, and service tasks: prefer the packaged `nmap-recon` workflow."
        )
    if not hints:
        return None
    return "\n".join(
        [
            "Contextual scripted-skill routing hint for this turn:",
            *hints,
            "Prefer the matching packaged skill before writing ad-hoc sandbox code.",
        ]
    )


def _augment_user_message(
    user_message: str, extra_sections: list[str] | None = None
) -> str:
    from .prompts import _EXECUTION_CONTRACT

    sections = [user_message.rstrip()]
    if extra_sections:
        sections.extend(
            section.strip() for section in extra_sections if section and section.strip()
        )
    sections.append(_EXECUTION_CONTRACT)
    return "\n\n".join(section for section in sections if section)


def _prepare_user_message(
    user_message: str,
    skill_report=None,
    memory_context: str | None = None,
) -> str:
    command = _parse_skill_command(user_message)
    extra_sections: list[str] = []
    message_text = command.remaining_message or user_message.strip()
    if memory_context and memory_context.strip():
        extra_sections.append(memory_context.strip())
    if skill_report is not None and skill_report.turn_hint:
        extra_sections.append(skill_report.turn_hint)
    if skill_report is not None:
        routing_hint = _build_skill_routing_hint(message_text, skill_report)
        if routing_hint:
            extra_sections.append(routing_hint)
    if command.requested_names and skill_report is not None:
        selection = skill_report.build_turn_selection(command.requested_names)
        if selection.prompt:
            extra_sections.append(selection.prompt)
        if not command.remaining_message:
            if selection.activated:
                message_text = "Continue the current task and prioritize the explicitly requested local skills above."
            elif selection.blocked or selection.missing:
                message_text = "Continue the current task from the existing context, and briefly explain why the explicitly requested local skills are not available before proceeding."
    return _augment_user_message(message_text, extra_sections=extra_sections)


def _looks_like_incomplete_action_intro(assistant_message: str) -> bool:
    stripped = assistant_message.strip()
    if not stripped:
        return False
    last_paragraph = re.split(r"\n\s*\n", stripped)[-1].strip()
    if not last_paragraph:
        return False
    lowered = last_paragraph.lower()
    if lowered.endswith((":", "\uff1a", "...", "\u2026")):
        return True
    return bool(
        re.match(
            r"^(?:\u8ba9\u6211|\u6211\u6765|\u63a5\u4e0b\u6765\u6211|\u73b0\u5728\u8ba9\u6211|\u6211\u518d\u8bd5\u8bd5|let me|next i(?:'| wi)ll|i(?:'| wi)ll)",
            last_paragraph,
            flags=re.IGNORECASE,
        )
    )


def _normalized_tool_block_type(block: dict[str, Any]) -> str:
    return str(block.get("type") or "").strip().lower()


def _tool_block_arguments(block: dict[str, Any]) -> dict[str, Any]:
    raw_arguments = block.get("input", block.get("arguments"))
    return raw_arguments if isinstance(raw_arguments, dict) else {}


def _normalize_sandbox_relative_path(candidate: Any) -> str:
    value = str(candidate or "").strip().replace("\\", "/")
    if not value or value == ".":
        return ""
    return value


def _same_sandbox_relative_path(left: str, right: str) -> bool:
    return (
        _normalize_sandbox_relative_path(left).lower()
        == _normalize_sandbox_relative_path(right).lower()
    )


def _has_unrun_python_script_mutation(blocks: list[dict[str, Any]]) -> bool:
    latest_mutated_path = ""
    latest_mutation_index = -1
    latest_matching_run_index = -1

    for index, block in enumerate(blocks):
        block_type = _normalized_tool_block_type(block)
        if block_type not in {"tool_use", "tool_call"}:
            continue

        name = str(block.get("name") or "").strip().lower()
        arguments = _tool_block_arguments(block)
        if name in _SANDBOX_SCRIPT_MUTATION_TOOLS:
            path = _normalize_sandbox_relative_path(arguments.get("path"))
            if path.lower().endswith(".py"):
                latest_mutated_path = path
                latest_mutation_index = index
                latest_matching_run_index = -1
            continue

        if name != "sandbox_run_python" or not latest_mutated_path:
            continue

        script_path = _normalize_sandbox_relative_path(arguments.get("script_path"))
        if script_path and _same_sandbox_relative_path(
            script_path, latest_mutated_path
        ):
            latest_matching_run_index = index

    return (
        latest_mutation_index >= 0 and latest_matching_run_index < latest_mutation_index
    )


def _should_force_tool_continuation(
    assistant_message: str,
    blocks: list[dict[str, Any]] | None = None,
) -> bool:
    if blocks and unresolved_tool_call_ids(blocks):
        return True
    normalized_blocks = [normalize_content_item(block) for block in blocks or []]
    has_tool_activity = any(
        _normalized_tool_block_type(block) in {"tool_use", "tool_call", "tool_result"}
        for block in normalized_blocks
    )
    has_output_text = bool(
        assistant_preview_text(normalized_blocks).strip()
        or (not normalized_blocks and assistant_message.strip())
    )
    if has_tool_activity and not has_output_text:
        return True
    if normalized_blocks and _has_unrun_python_script_mutation(normalized_blocks):
        return True
    lowered = assistant_message.lower()
    if any(pattern in lowered for pattern in _CONTINUATION_HINT_PATTERNS):
        return True
    return _looks_like_incomplete_action_intro(assistant_message)


@dataclass(frozen=True)
class _LoopGuardSnapshot:
    tool_call_signatures: tuple[str, ...] = ()
    tool_result_signatures: tuple[str, ...] = ()
    output_text: str = ""


@dataclass
class _StreamLoopGuard:
    last_snapshot: _LoopGuardSnapshot | None = None
    repeated_branch_signature: str | None = None
    triggered_reason: str | None = None

    def reset(self) -> None:
        self.last_snapshot = None
        self.repeated_branch_signature = None
        self.triggered_reason = None

    def consume_triggered_reason(self) -> str | None:
        reason = self.triggered_reason
        self.triggered_reason = None
        return reason

    def observe(self, event: dict[str, Any]) -> str | None:
        if self.triggered_reason is not None:
            return self.triggered_reason
        snapshot = _extract_loop_guard_snapshot(list(event.get("blocks") or []))
        previous = self.last_snapshot
        self.last_snapshot = snapshot
        if previous is None:
            self.repeated_branch_signature = None
            return None

        previous_results = previous.tool_result_signatures
        current_results = snapshot.tool_result_signatures
        previous_branch = _latest_branch_signature(previous)
        current_branch = _latest_branch_signature(snapshot)

        if len(current_results) > len(previous_results):
            self.repeated_branch_signature = (
                current_branch
                if current_branch and current_branch == previous_branch
                else None
            )
            return None
        if (
            len(current_results) < len(previous_results)
            or current_results != previous_results
        ):
            self.repeated_branch_signature = None
            return None
        if snapshot.tool_call_signatures != previous.tool_call_signatures:
            return None
        if not self.repeated_branch_signature:
            return None
        if snapshot.output_text == previous.output_text:
            return None
        if previous.output_text and _output_introduces_new_evidence(
            previous.output_text, snapshot.output_text
        ):
            self.repeated_branch_signature = None
            return None

        self.triggered_reason = "The agent repeated the same tool branch without producing new evidence or a new actionable direction."
        return self.triggered_reason


def _normalize_loop_guard_text(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _extract_loop_guard_snapshot(
    blocks: list[dict[str, Any]] | None,
) -> _LoopGuardSnapshot:
    normalized_blocks = [normalize_content_item(block) for block in blocks or []]
    tool_calls: list[str] = []
    tool_results: list[str] = []
    for block in normalized_blocks:
        block_type = str(block.get("type") or "").strip().lower()
        if block_type == "tool_use":
            signature = tool_call_signature(block)
            if signature:
                tool_calls.append(signature)
            continue
        if block_type == "tool_result":
            signature = tool_result_signature(block)
            if signature:
                tool_results.append(signature)
    return _LoopGuardSnapshot(
        tool_call_signatures=tuple(tool_calls),
        tool_result_signatures=tuple(tool_results),
        output_text=_normalize_loop_guard_text(
            assistant_preview_text(normalized_blocks)
        ),
    )


def _latest_branch_signature(snapshot: _LoopGuardSnapshot) -> str | None:
    if not snapshot.tool_result_signatures:
        return None
    latest_result = snapshot.tool_result_signatures[-1]
    latest_call = (
        snapshot.tool_call_signatures[-1] if snapshot.tool_call_signatures else ""
    )
    return f"{latest_call}|{latest_result}"


def _output_introduces_new_evidence(previous_text: str, current_text: str) -> bool:
    previous = _normalize_loop_guard_text(previous_text)
    current = _normalize_loop_guard_text(current_text)
    if not current:
        return False
    if not previous:
        return True
    if current == previous:
        return False
    if current.startswith(previous):
        added = current[len(previous) :].strip()
        return len(added) >= 24
    if previous.startswith(current):
        return False
    similarity = difflib.SequenceMatcher(None, previous, current).ratio()
    return similarity < 0.72 and abs(len(current) - len(previous)) >= 12


def _build_loop_guard_recovery_prompt(reason: str) -> str:
    return (
        "Stop retrying the same tool inputs in this turn. "
        f"Reason: {reason} "
        "Do not call the same tool with the same arguments again unless you have new evidence or changed inputs. "
        "Summarize the last confirmed evidence, the current blocker, and the single most useful next step or missing input."
    )


def _extract_response_blocks(content: object) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(content, list):
        blocks = content
    elif isinstance(content, dict):
        blocks = [content]
    else:
        blocks = [{"type": "text", "text": str(content)}]

    normalized_blocks = assistant_content_from_blocks(blocks)
    assistant_message = assistant_preview_text(normalized_blocks)
    if not assistant_message and normalized_blocks:
        tool_names = [
            str(block.get("name", "")).strip()
            for block in normalized_blocks
            if str(block.get("type") or "").strip().lower() == "tool_call"
            and str(block.get("name", "")).strip()
        ]
        if tool_names:
            assistant_message = f"This turn executed {len(tool_names)} tool calls: {', '.join(tool_names[:4])}"
    return assistant_message, normalized_blocks


def _build_stream_event(msg: Msg, last: bool) -> dict[str, Any]:
    assistant_message, blocks = _extract_response_blocks(msg.content)
    return {
        "role": msg.role,
        "name": msg.name,
        "content": assistant_message,
        "blocks": blocks,
        "last": last,
        "timestamp": msg.timestamp,
    }


def _response_state_signature(
    assistant_message: str,
    blocks: list[dict[str, Any]] | None = None,
) -> str:
    snapshot = _extract_loop_guard_snapshot(blocks or [])
    payload = {
        "tool_calls": snapshot.tool_call_signatures,
        "tool_results": snapshot.tool_result_signatures,
        "unresolved": sorted(unresolved_tool_call_ids(blocks or [])),
        "text": snapshot.output_text or _normalize_loop_guard_text(assistant_message),
        "needs_continuation": _should_force_tool_continuation(
            assistant_message, blocks
        ),
    }
    return stable_fingerprint(payload)


def _continuation_made_progress(
    previous_message: str,
    previous_blocks: list[dict[str, Any]] | None,
    current_message: str,
    current_blocks: list[dict[str, Any]] | None,
) -> bool:
    if not _should_force_tool_continuation(current_message, current_blocks):
        return True

    previous_snapshot = _extract_loop_guard_snapshot(previous_blocks or [])
    current_snapshot = _extract_loop_guard_snapshot(current_blocks or [])
    previous_unresolved = set(unresolved_tool_call_ids(previous_blocks or []))
    current_unresolved = set(unresolved_tool_call_ids(current_blocks or []))

    if previous_unresolved and not current_unresolved:
        return True
    if len(current_snapshot.tool_result_signatures) > len(
        previous_snapshot.tool_result_signatures
    ):
        return True
    if len(current_snapshot.tool_call_signatures) > len(
        previous_snapshot.tool_call_signatures
    ):
        return True
    if set(current_snapshot.tool_result_signatures) - set(
        previous_snapshot.tool_result_signatures
    ):
        return True
    if set(current_snapshot.tool_call_signatures) - set(
        previous_snapshot.tool_call_signatures
    ):
        return True

    previous_text = previous_snapshot.output_text or _normalize_loop_guard_text(
        previous_message
    )
    current_text = current_snapshot.output_text or _normalize_loop_guard_text(
        current_message
    )
    if not current_text or not previous_text:
        return False
    if _looks_like_incomplete_action_intro(current_message):
        return False
    return _output_introduces_new_evidence(previous_text, current_text)


async def _continue_response_until_settled(
    *,
    run_agent_turn,
    assistant_message: str,
    blocks: list[dict[str, Any]] | None,
    continuation_prompt: str,
) -> tuple[str, list[dict[str, Any]]]:
    current_message = assistant_message
    current_blocks = list(blocks or [])
    seen_signatures = {_response_state_signature(current_message, current_blocks)}

    while _should_force_tool_continuation(current_message, current_blocks):
        response = await run_agent_turn(continuation_prompt)
        next_message, next_blocks = _extract_response_blocks(response.content)
        next_signature = _response_state_signature(next_message, next_blocks)
        if next_signature in seen_signatures:
            current_message = next_message
            current_blocks = next_blocks
            break
        if not _continuation_made_progress(
            current_message, current_blocks, next_message, next_blocks
        ):
            current_message = next_message
            current_blocks = next_blocks
            break
        seen_signatures.add(next_signature)
        current_message = next_message
        current_blocks = next_blocks

    return current_message, current_blocks


__all__ = [
    "_make_agentscope_output_safe",
    "_parse_skill_command",
    "_build_skill_routing_hint",
    "_augment_user_message",
    "_prepare_user_message",
    "_looks_like_incomplete_action_intro",
    "_normalized_tool_block_type",
    "_tool_block_arguments",
    "_normalize_sandbox_relative_path",
    "_same_sandbox_relative_path",
    "_has_unrun_python_script_mutation",
    "_should_force_tool_continuation",
    "_LoopGuardSnapshot",
    "_StreamLoopGuard",
    "_normalize_loop_guard_text",
    "_extract_loop_guard_snapshot",
    "_latest_branch_signature",
    "_output_introduces_new_evidence",
    "_build_loop_guard_recovery_prompt",
    "_extract_response_blocks",
    "_build_stream_event",
    "_response_state_signature",
    "_continuation_made_progress",
]
