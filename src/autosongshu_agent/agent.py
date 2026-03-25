from __future__ import annotations

import asyncio
import contextlib
import difflib
import hashlib
import json
import re
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import agentscope
from agentscope.agent import ReActAgent
from agentscope.message import Msg
from agentscope.model import OpenAIChatModel
from agentscope.plan import PlanNotebook
from agentscope.tool import Toolkit

from .config import AppConfig
from .formatter import SafeOpenAIChatFormatter
from .memory import (
    LayeredConversationMemory,
    MemorySynthesisPayload,
    SessionHandoffCard,
    build_memory_fallback,
    now_iso as memory_now_iso,
    sync_validated_findings,
)
from .message_blocks import (
    assistant_content_from_blocks,
    assistant_preview_text,
    normalize_content_item,
    unresolved_tool_call_ids,
)
from .prompts import build_system_prompt
from .runtime import PentestRuntime
from .skills import SkillLoadReport, SkillRegistry, SkillRuntimeContext
from .tools import register_default_tools


@dataclass
class RunResult:
    final_message: str
    artifact_dir: str


@dataclass
class ConversationReply:
    assistant_message: str
    artifact_dir: str
    blocks: list[dict[str, Any]] | None = None


@dataclass
class SkillCommand:
    requested_names: list[str] = field(default_factory=list)
    remaining_message: str = ""


_EXECUTION_CONTRACT = "\n".join(
    [
        "Execution contract:",
        "- Prefer advancing the task with real tools instead of stopping at recommendations.",
        "- Knowledge retrieval policy: when a turn involves hypothesis, root-cause analysis, remediation strategy, or reusable methodology, proactively consider `knowledge_search` before final conclusions.",
        "- Trigger `knowledge_search` when you hit a new endpoint/module, a new vulnerability class, uncertain root cause, conflicting clues, or explicit user requests about strategy/experience reuse.",
        "- Compose retrieval queries as concise intent strings: target/context + vulnerability/symptom + objective. If the first search is weak, rewrite the query and retry once with a different focus.",
        "- Do not repeat identical `knowledge_search` queries unchanged in the same context.",
        "- If a matching local scripted skill is already loaded, prefer `list_skill_scripts` and `run_skill_script` before writing ad-hoc sandbox code.",
        "- Only prioritize `sandbox_status`, `sandbox_install_packages`, and `sandbox_run_python` when no suitable local skill exists, the existing skill is clearly insufficient, or the operator explicitly asks for a custom script.",
        "- The `ok` field returned by `sandbox_run_python` only means the Python process exited with status code 0. Always interpret stdout and stderr before claiming success.",
        "- If the same tool name with the exact same arguments was already executed and there is no new evidence or state change, do not call it again unchanged.",
        "- If the exact same Python code or script was just executed without any new inputs or edits, do not rerun the same `sandbox_run_python` payload unchanged.",
        "- When iterating on an existing sandbox payload or helper script, first inspect it with `sandbox_read_file(include_line_numbers=True)`, then prefer `sandbox_edit_file` for one precise change or `sandbox_multiedit_file` for several ordered precise changes before `sandbox_run_python(script_path=...)`.",
        "- Use `sandbox_write_file` only to create a new sandbox file or to intentionally replace the whole file. Do not use `sandbox_edit_file` as a disguised full rewrite.",
        "- For `sandbox_write_file.content`, `sandbox_edit_file.new_text`, `sandbox_multiedit_file.edits[*].new_text`, and `sandbox_run_python(code=...)`, send raw code or raw file text only. Never wrap it in markdown fences or mix in plans, explanations, or thought-process notes.",
        "- If explanation is needed, put it in the assistant message instead of inside the sandbox file. Keep code comments sparse and purely technical.",
        "- If output contains `HTTPSConnectionPool`, `SSLError`, `CERTIFICATE_VERIFY_FAILED`, or `unable to get local issuer certificate`, first treat it as a likely TLS certificate-chain issue. On authorized targets, it is acceptable to retry explicitly with `verify=False` and explain why.",
        "- When the task clearly matches SQL injection, directory discovery, or host and port enumeration, prefer the existing packaged skill first, then consider custom sandbox code.",
        "- If you think a script, fuzzer, or custom request flow is needed, first check whether a local skill already covers it. Do not stop at a suggestion when you can execute the next step.",
    ],
).strip()

_CONTINUATION_PROMPT = "\n".join(
    [
        "Do not stop at a recommendation layer. Continue executing the task now.",
        "- If you are about to output a strategy, root-cause explanation, exploit path, or remediation advice without enough direct evidence, call `knowledge_search` first.",
        "- If a previous `knowledge_search` result is weak or mismatched, reformulate the query and retry once before giving up.",
        "- If a matching local scripted skill exists, use it before falling back to `sandbox_*` tools.",
        "- Only enter `sandbox_status`, `sandbox_install_packages`, or `sandbox_run_python` when the local skill path is insufficient.",
        "- If a sandbox script already exists, inspect it with `sandbox_read_file(include_line_numbers=True)` and modify it with `sandbox_edit_file` or `sandbox_multiedit_file` instead of rewriting the entire file.",
        "- Any `sandbox_write_file`, `sandbox_edit_file`, `sandbox_multiedit_file`, or `sandbox_run_python(code=...)` payload must be raw file content only, without markdown fences or explanatory prose.",
        "- After `sandbox_write_file`, `sandbox_edit_file`, or `sandbox_multiedit_file` changes a Python script you intend to verify, immediately follow with `sandbox_run_python(script_path=...)` in the same turn unless a confirmed blocker prevents execution.",
        "- If the previous output still says things like 'let me try', 'let me continue', or 'next I will', skip the transition phrase and actually perform the next step.",
        "- If the blocker looks like TLS certificate validation on an authorized target, handle it explicitly instead of repeating the same request unchanged.",
        "- Stop only if you have reached a real blocker and clearly explain the confirmed evidence, the blocker, and the single best next step.",
    ],
).strip()

_MEMORY_SYSTEM_PROMPT = "\n".join(
    [
        "You are AutoSongshu's compact and handoff synthesizer.",
        "Do not replay raw history. Produce an OpenCode-style compact handoff card so the next turn can continue the same task without forgetting scope, targets, blockers, and proven dead ends.",
        "",
        "Output requirements:",
        "1. Fill `handoff.task` with the primary goal. Preserve the original user objective whenever possible; do not replace it with a short follow-up delta.",
        "2. Fill `handoff.instructions` with the important user/system/developer instructions and the latest delta that future turns must keep following.",
        "3. Fill `handoff.status` with the current progress state and `handoff.current_focus` with the single most important thing to continue now.",
        "4. Fill `handoff.discoveries` with the most important confirmed discoveries or observations.",
        "5. Fill `handoff.accomplished` with concrete completed steps, checks, or tool flows.",
        "6. Fill `handoff.relevant_files` with important scripts, files, paths, or directories that future turns should reuse or inspect.",
        "7. Keep exact relevant target URLs in `handoff.target_urls`.",
        "8. Keep only high-confidence facts in `handoff.confirmed_facts` and unresolved but important questions in `handoff.open_questions`.",
        "9. Record tools, scripts, payloads, argument sets, and paths that must not be retried unchanged in `handoff.avoid_repeating`.",
        "10. Keep only the highest-value next actions in `handoff.next_steps`.",
        "11. Still fill `summary`, `stable_conclusions`, `active_leads`, `dead_ends`, `next_focus`, and `recent_progress`, but the handoff card is the primary artifact.",
        "12. Do not preserve large HTML, full code, full JSON, or long logs; keep only high-signal decision-making context.",
        "13. Default to Simplified Chinese unless the user explicitly asks for another language.",
    ],
).strip()

_CONTINUATION_HINT_PATTERNS = (
    "\u5efa\u8bae\u5c1d\u8bd5",
    "\u53ef\u4ee5\u5c1d\u8bd5\u4f7f\u7528",
    "\u53ef\u4ee5\u4f7f\u7528\u6d4f\u89c8\u5668\u5de5\u5177",
    "\u53ef\u4ee5\u4f7f\u7528\u6c99\u7bb1",
    "\u53ef\u4ee5\u5199\u811a\u672c",
    "\u5efa\u8bae\u4f7f\u7528\u5176\u4ed6\u5de5\u5177",
    "\u7531\u4e8e\u5de5\u5177\u9650\u5236",
    "\u53d7\u5de5\u5177\u9650\u5236",
    "\u5f53\u524d\u73af\u5883\u65e0\u6cd5",
    "\u65e0\u6cd5\u52a8\u6001\u5206\u6790",
    "\u9700\u8981\u4f7f\u7528\u6d4f\u89c8\u5668\u5de5\u5177",
    "\u9700\u8981\u501f\u52a9\u5176\u4ed6\u5de5\u5177",
    "\u540e\u7eed\u53ef\u4ee5\u7ee7\u7eed",
    "could try using",
    "tool limitation",
    "unable to continue",
    "use the sandbox",
)

_LOOP_GUARD_META_TOOLS = frozenset({"create_plan", "update_subtask_state"})
_SANDBOX_SCRIPT_MUTATION_TOOLS = frozenset(
    {"sandbox_write_file", "sandbox_edit_file", "sandbox_multiedit_file"}
)


def _make_agentscope_output_safe(agent: ReActAgent) -> ReActAgent:
    agent._disable_console_output = True
    return agent


def _parse_skill_command(user_message: str) -> SkillCommand:
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


def _prepare_user_message(
    user_message: str,
    skill_report: SkillLoadReport | None = None,
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


def _build_skill_routing_hint(
    user_message: str, skill_report: SkillLoadReport
) -> str | None:
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
    sections = [user_message.rstrip()]
    if extra_sections:
        sections.extend(
            section.strip() for section in extra_sections if section and section.strip()
        )
    sections.append(_EXECUTION_CONTRACT)
    return "\n\n".join(section for section in sections if section)


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


def _stable_fingerprint(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(serialized.encode("utf-8")).hexdigest()


def _should_track_loop_guard_tool(tool_name: str) -> bool:
    return str(tool_name or "").strip().lower() not in _LOOP_GUARD_META_TOOLS


def _tool_call_signature(block: dict[str, Any]) -> str | None:
    name = str(block.get("name") or "").strip()
    if not name or not _should_track_loop_guard_tool(name):
        return None
    arguments = block.get("input", block.get("arguments"))
    return f"{name}:{_stable_fingerprint(arguments)}"


def _tool_result_signature(block: dict[str, Any]) -> str | None:
    name = str(block.get("name") or "").strip()
    if not name or not _should_track_loop_guard_tool(name):
        return None
    content = block.get("content", block.get("output"))
    return f"{name}:{_stable_fingerprint(content)}"


def _extract_loop_guard_snapshot(
    blocks: list[dict[str, Any]] | None,
) -> _LoopGuardSnapshot:
    normalized_blocks = [normalize_content_item(block) for block in blocks or []]
    tool_calls: list[str] = []
    tool_results: list[str] = []
    for block in normalized_blocks:
        block_type = str(block.get("type") or "").strip().lower()
        if block_type == "tool_use":
            signature = _tool_call_signature(block)
            if signature:
                tool_calls.append(signature)
            continue
        if block_type == "tool_result":
            signature = _tool_result_signature(block)
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
    return _stable_fingerprint(payload)


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
    run_agent_turn: Callable[[str], Awaitable[Msg]],
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


class _AgentBuilderMixin:
    config: AppConfig
    runtime: PentestRuntime
    skill_report: SkillLoadReport

    def _build_model(self) -> OpenAIChatModel:
        api_key = self.config.model.api_key
        if not api_key and self.config.model.base_url:
            api_key = "EMPTY"
        if not api_key and not self.config.model.base_url:
            raise ValueError(
                "Missing model credentials. Set AUTOSONGSHU_MODEL_API_KEY/model.api_key, "
                "or provide model.base_url for an OpenAI-compatible endpoint.",
            )

        client_kwargs = {"timeout": self.config.model.timeout}
        if self.config.model.base_url:
            client_kwargs["base_url"] = self.config.model.base_url

        generate_kwargs = {
            "temperature": self.config.model.temperature,
            "top_p": self.config.model.top_p,
        }
        if self.config.model.max_tokens is not None:
            generate_kwargs["max_tokens"] = self.config.model.max_tokens

        return OpenAIChatModel(
            model_name=self.config.model.model_name,
            api_key=api_key,
            stream=self.config.model.stream,
            client_kwargs=client_kwargs,
            generate_kwargs=generate_kwargs,
        )

    def _build_memory_model(self) -> OpenAIChatModel:
        api_key = self.config.model.api_key
        if not api_key and self.config.model.base_url:
            api_key = "EMPTY"
        if not api_key and not self.config.model.base_url:
            raise ValueError(
                "Missing model credentials. Set AUTOSONGSHU_MODEL_API_KEY/model.api_key, "
                "or provide model.base_url for an OpenAI-compatible endpoint.",
            )

        client_kwargs = {"timeout": self.config.model.timeout}
        if self.config.model.base_url:
            client_kwargs["base_url"] = self.config.model.base_url

        generate_kwargs = {
            "temperature": min(float(self.config.model.temperature), 0.2),
            "top_p": self.config.model.top_p,
        }
        if self.config.model.max_tokens is not None:
            generate_kwargs["max_tokens"] = self.config.model.max_tokens

        return OpenAIChatModel(
            model_name=self.config.model.model_name,
            api_key=api_key,
            stream=False,
            client_kwargs=client_kwargs,
            generate_kwargs=generate_kwargs,
        )

    def _build_agent(self) -> ReActAgent:
        agentscope.init(
            project="autosongshu-agent",
            name=self.config.engagement.name,
            logging_path=str(self.runtime.artifacts.session_dir / "agentscope"),
            logging_level="INFO",
        )

        toolkit = Toolkit()
        register_default_tools(toolkit, self.runtime)
        skill_report = SkillLoadReport(
            configured_directories=list(self.config.skills.directories)
        )
        skill_prompt: str | None = None

        if self.config.skills.enabled and self.config.skills.directories:
            skill_registry = SkillRegistry(
                self.config.skills.directories,
                context=SkillRuntimeContext.from_runtime(toolkit, self.config),
            )
            skill_report = skill_registry.register(toolkit)
            skill_prompt = skill_report.agent_prompt

        self.skill_report = skill_report
        self.runtime.loaded_skills = skill_report.loaded_paths
        self.runtime.skill_scripts.update_skills(
            skill_report.loaded,
            manual_skills=skill_report.manual_available,
        )
        skill_payload = skill_report.as_dict()
        self.runtime.update_session_metadata(
            {
                "skills": skill_payload,
                "skill_scripts": self.runtime.skill_scripts.describe(),
            },
        )

        plan_notebook = PlanNotebook(max_subtasks=self.config.agent.max_subtasks)
        model = self._build_model()
        formatter = SafeOpenAIChatFormatter()
        sys_prompt = build_system_prompt(self.config)
        if skill_prompt:
            sys_prompt = f"{sys_prompt}\n\n{skill_prompt}"

        return _make_agentscope_output_safe(
            ReActAgent(
                name="AutoSongshu",
                sys_prompt=sys_prompt,
                model=model,
                formatter=formatter,
                toolkit=toolkit,
                plan_notebook=plan_notebook,
                max_iters=self.config.agent.max_iters,
                enable_meta_tool=self.config.agent.enable_meta_tool,
                parallel_tool_calls=self.config.agent.parallel_tool_calls,
                print_hint_msg=False,
            ),
        )


class PentestConversationSession(_AgentBuilderMixin):
    def __init__(
        self,
        config: AppConfig,
        artifact_session_name: str | None = None,
        sandbox_user_id: str | None = None,
    ) -> None:
        self.config = config
        self.runtime = PentestRuntime(
            config,
            artifact_session_name=artifact_session_name,
            sandbox_user_id=sandbox_user_id,
        )
        self._interrupt_lock = threading.RLock()
        self._active_loop: asyncio.AbstractEventLoop | None = None
        self._interrupt_requested = False
        self._memory_context = ""
        self.memory_model = self._build_memory_model()
        self.agent = self._build_agent()

    async def observe_history_async(self, messages: list[Msg]) -> None:
        if not messages:
            return
        await self.agent.observe(messages)

    def observe_history(self, messages: list[Msg]) -> None:
        if not messages:
            return
        asyncio.run(self.observe_history_async(messages))

    def rebuild_context(
        self,
        history_messages: list[Msg],
        *,
        memory: LayeredConversationMemory | None = None,
        pinned_context: str | None = None,
    ) -> None:
        self.agent = self._build_agent()
        context_sections: list[str] = []
        if pinned_context and pinned_context.strip():
            context_sections.append(pinned_context.strip())
        if memory and not memory.is_empty():
            context_sections.append(memory.render_for_model())
        self._memory_context = "\n\n".join(
            section for section in context_sections if section
        ).strip()
        context_messages: list[Msg] = []
        if self._memory_context:
            context_messages.append(
                Msg(name="memory", role="system", content=self._memory_context)
            )
        context_messages.extend(history_messages)
        self.observe_history(context_messages)

    async def refresh_memory_async(
        self,
        *,
        existing_memory: LayeredConversationMemory,
        transcript_payload: list[dict[str, Any]],
        anchor_message_id: str | None,
    ) -> LayeredConversationMemory:
        validated_findings = sync_validated_findings(self.runtime.findings.list())
        if (
            not transcript_payload
            and anchor_message_id == existing_memory.anchor_message_id
            and existing_memory.validated_findings == validated_findings
        ):
            return existing_memory
        if (
            not transcript_payload
            and anchor_message_id == existing_memory.anchor_message_id
        ):
            updated = existing_memory.model_copy(deep=True)
            updated.validated_findings = validated_findings
            updated.updated_at = memory_now_iso()
            self.runtime.artifacts.write_json("memory.json", updated.model_dump())
            self.runtime.update_session_metadata({"memory": updated.model_dump()})
            return updated

        payload = {
            "existing_memory": existing_memory.model_dump(),
            "validated_findings": [item.model_dump() for item in validated_findings],
            "transcript_delta": transcript_payload,
        }
        messages = [
            {"role": "system", "content": _MEMORY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    payload, ensure_ascii=False, indent=2, default=str
                ),
            },
        ]

        try:
            response = await self.memory_model(
                messages, structured_model=MemorySynthesisPayload
            )
            synthesized = MemorySynthesisPayload.model_validate(response.metadata or {})
            updated = LayeredConversationMemory(
                summary=synthesized.summary.strip(),
                stable_conclusions=synthesized.stable_conclusions,
                validated_findings=validated_findings,
                active_leads=synthesized.active_leads,
                dead_ends=synthesized.dead_ends,
                next_focus=[
                    item.strip() for item in synthesized.next_focus if str(item).strip()
                ],
                recent_progress=synthesized.recent_progress.strip(),
                handoff=synthesized.handoff or SessionHandoffCard(),
                anchor_message_id=anchor_message_id
                or existing_memory.anchor_message_id,
                updated_at=memory_now_iso(),
            )
            if updated.is_empty() and (transcript_payload or validated_findings):
                updated = build_memory_fallback(
                    existing_memory,
                    transcript_payload,
                    validated_findings,
                    anchor_message_id,
                )
            elif updated.handoff.is_empty():
                updated.handoff = build_memory_fallback(
                    updated,
                    transcript_payload,
                    validated_findings,
                    anchor_message_id,
                ).handoff
        except Exception:
            updated = build_memory_fallback(
                existing_memory,
                transcript_payload,
                validated_findings,
                anchor_message_id,
            )

        updated.anchor_message_id = anchor_message_id or updated.anchor_message_id
        updated.updated_at = updated.updated_at or memory_now_iso()
        self.runtime.artifacts.write_json("memory.json", updated.model_dump())
        self.runtime.update_session_metadata({"memory": updated.model_dump()})
        return updated

    def refresh_memory(
        self,
        *,
        existing_memory: LayeredConversationMemory,
        transcript_payload: list[dict[str, Any]],
        anchor_message_id: str | None,
    ) -> LayeredConversationMemory:
        return asyncio.run(
            self.refresh_memory_async(
                existing_memory=existing_memory,
                transcript_payload=transcript_payload,
                anchor_message_id=anchor_message_id,
            ),
        )

    async def _stream_agent_messages(
        self,
        queue: asyncio.Queue,
        stop_event: asyncio.Event,
        stream_callback: Callable[[dict[str, Any]], None] | None,
        loop_guard: _StreamLoopGuard | None = None,
    ) -> None:
        while True:
            if stop_event.is_set() and queue.empty():
                return
            try:
                msg, last, _speech = await asyncio.wait_for(queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            event = _build_stream_event(msg, last)
            if loop_guard is not None and loop_guard.observe(event):
                with contextlib.suppress(Exception):
                    await self.agent.interrupt()
            if stream_callback is not None:
                with contextlib.suppress(Exception):
                    stream_callback(event)

    async def send_async(
        self,
        user_message: str,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> ConversationReply:
        stream_queue: asyncio.Queue | None = None
        stop_event: asyncio.Event | None = None
        stream_task: asyncio.Task[None] | None = None
        loop_guard = _StreamLoopGuard()
        agent_config = getattr(getattr(self, "config", None), "agent", None)
        use_loop_guard = getattr(agent_config, "loop_guard_enabled", True)
        loop = asyncio.get_running_loop()
        if hasattr(self.runtime, "tool_call_cache"):
            self.runtime.tool_call_cache.reset_turn()
        with self._interrupt_lock:
            self._active_loop = loop
        if stream_callback is not None or use_loop_guard:
            stream_queue = asyncio.Queue(maxsize=200)
            stop_event = asyncio.Event()
            self.agent.set_msg_queue_enabled(True, queue=stream_queue)
            stream_task = asyncio.create_task(
                self._stream_agent_messages(
                    stream_queue,
                    stop_event,
                    stream_callback,
                    loop_guard=loop_guard if use_loop_guard else None,
                ),
            )

        async def run_agent_turn(
            content: str, *, allow_loop_guard_recovery: bool = True
        ) -> Msg:
            if use_loop_guard:
                loop_guard.reset()
            response_task = asyncio.create_task(
                self.agent(
                    Msg(
                        name="operator",
                        role="user",
                        content=content,
                    ),
                ),
            )
            with self._interrupt_lock:
                interrupt_requested = self._interrupt_requested
            if interrupt_requested:
                await asyncio.sleep(0)
                await self.agent.interrupt()
            response = await response_task
            if use_loop_guard:
                loop_reason = loop_guard.consume_triggered_reason()
                if loop_reason and allow_loop_guard_recovery:
                    return await run_agent_turn(
                        _build_loop_guard_recovery_prompt(loop_reason),
                        allow_loop_guard_recovery=False,
                    )
            return response

        try:
            response = await run_agent_turn(
                _prepare_user_message(
                    user_message,
                    self.skill_report,
                    getattr(self, "_memory_context", ""),
                ),
            )
            assistant_message, blocks = _extract_response_blocks(response.content)
            assistant_message, blocks = await _continue_response_until_settled(
                run_agent_turn=run_agent_turn,
                assistant_message=assistant_message,
                blocks=blocks,
                continuation_prompt=_CONTINUATION_PROMPT,
            )
            self.runtime.persist_runtime_logs()
            return ConversationReply(
                assistant_message=assistant_message,
                artifact_dir=str(self.runtime.artifacts.session_dir),
                blocks=blocks,
            )
        finally:
            if stop_event is not None:
                stop_event.set()
            if stream_queue is not None:
                self.agent.set_msg_queue_enabled(False)
            if stream_task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await stream_task
            with self._interrupt_lock:
                self._active_loop = None
                self._interrupt_requested = False

    def send(
        self,
        user_message: str,
        stream_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> ConversationReply:
        return asyncio.run(
            self.send_async(user_message, stream_callback=stream_callback)
        )

    def interrupt(self) -> bool:
        with self._interrupt_lock:
            self._interrupt_requested = True
            loop = self._active_loop

        if loop is None or loop.is_closed():
            return False
        try:
            asyncio.run_coroutine_threadsafe(self.agent.interrupt(), loop)
        except RuntimeError:
            return False
        return True

    def close(self) -> None:
        self.runtime.close()


class PentestCoordinator(_AgentBuilderMixin):
    def __init__(self, config: AppConfig, sandbox_user_id: str | None = None) -> None:
        self.config = config
        self.runtime = PentestRuntime(config, sandbox_user_id=sandbox_user_id)

    async def run_async(self, goal: str) -> RunResult:
        agent = self._build_agent()
        stream_queue: asyncio.Queue | None = None
        stop_event: asyncio.Event | None = None
        stream_task: asyncio.Task[None] | None = None
        loop_guard = _StreamLoopGuard()
        agent_config = getattr(getattr(self, "config", None), "agent", None)
        use_loop_guard = getattr(agent_config, "loop_guard_enabled", True)
        if hasattr(self.runtime, "tool_call_cache"):
            self.runtime.tool_call_cache.reset_turn()
        prompt = "\n".join(
            [
                f"User goal: {goal}",
                f"Start URL: {self.config.engagement.start_url}",
                "Provide a short plan, execute the assessment within the authorized scope, keep findings updated, and finish with the most important conclusions.",
                "Default to Simplified Chinese unless the user explicitly asks for another language.",
            ]
        )

        async def stream_agent_messages() -> None:
            assert stream_queue is not None
            assert stop_event is not None
            while True:
                if stop_event.is_set() and stream_queue.empty():
                    return
                try:
                    msg, last, _speech = await asyncio.wait_for(
                        stream_queue.get(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue
                if loop_guard.observe(_build_stream_event(msg, last)):
                    with contextlib.suppress(Exception):
                        await agent.interrupt()

        async def run_agent_turn(
            content: str, *, allow_loop_guard_recovery: bool = True
        ) -> Msg:
            if use_loop_guard:
                loop_guard.reset()
            response = await agent(
                Msg(
                    name="operator",
                    role="user",
                    content=content,
                ),
            )
            if use_loop_guard:
                loop_reason = loop_guard.consume_triggered_reason()
                if loop_reason and allow_loop_guard_recovery:
                    return await run_agent_turn(
                        _build_loop_guard_recovery_prompt(loop_reason),
                        allow_loop_guard_recovery=False,
                    )
            return response

        try:
            if use_loop_guard:
                stream_queue = asyncio.Queue(maxsize=200)
                stop_event = asyncio.Event()
                agent.set_msg_queue_enabled(True, queue=stream_queue)
                stream_task = asyncio.create_task(stream_agent_messages())

            response = await run_agent_turn(
                _prepare_user_message(prompt, self.skill_report)
            )
            assistant_message, blocks = _extract_response_blocks(response.content)
            assistant_message, blocks = await _continue_response_until_settled(
                run_agent_turn=run_agent_turn,
                assistant_message=assistant_message,
                blocks=blocks,
                continuation_prompt=_CONTINUATION_PROMPT,
            )
            self.runtime.persist_runtime_logs()
            return RunResult(
                final_message=assistant_message,
                artifact_dir=str(self.runtime.artifacts.session_dir),
            )
        finally:
            if stop_event is not None:
                stop_event.set()
            if stream_queue is not None:
                agent.set_msg_queue_enabled(False)
            if stream_task is not None:
                with contextlib.suppress(asyncio.CancelledError):
                    await stream_task
            self.runtime.close()

    def run(self, goal: str) -> RunResult:
        return asyncio.run(self.run_async(goal))
