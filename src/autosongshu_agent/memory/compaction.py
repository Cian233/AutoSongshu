from __future__ import annotations

import re
from typing import Any


_FILE_EXTENSION_PATTERN = re.compile(r"\.[a-zA-Z0-9]{1,6}$")
_PENDING_PATTERNS = (
    "todo",
    "next",
    "pending",
    "follow up",
    "remaining",
    "待办",
    "下一步",
    "后续",
    "继续",
)


def _truncate_summary(text: str, max_chars: int) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars <= 1:
        return value[:max_chars]
    return f"{value[: max_chars - 1]}…"


def _strip_tag_block(content: str, tag: str) -> str:
    value = str(content or "")
    start = f"<{tag}>"
    end = f"</{tag}>"
    start_index = value.find(start)
    end_index = value.find(end)
    if start_index >= 0 and end_index > start_index:
        return value[:start_index] + value[end_index + len(end) :]
    return value


def _extract_tag_block(content: str, tag: str) -> str | None:
    value = str(content or "")
    start = f"<{tag}>"
    end = f"</{tag}>"
    start_index = value.find(start)
    if start_index < 0:
        return None
    start_index += len(start)
    end_index = value.find(end, start_index)
    if end_index <= start_index:
        return None
    return value[start_index:end_index]


def format_compact_summary(summary: str) -> str:
    without_analysis = _strip_tag_block(summary, "analysis")
    extracted = _extract_tag_block(without_analysis, "summary")
    if extracted is None:
        return without_analysis.strip()
    return without_analysis.replace(
        f"<summary>{extracted}</summary>",
        "Summary:\n" + extracted.strip(),
    ).strip()


def estimate_transcript_tokens(transcript_payload: list[dict[str, Any]]) -> int:
    total = 0
    for entry in transcript_payload:
        text = str(entry.get("text") or "")
        total += len(text) // 4 + 1
        for activity in entry.get("tool_activity") or []:
            total += len(str(activity.get("name") or "")) // 4 + 1
            if isinstance(activity.get("arguments"), dict):
                total += len(str(activity.get("arguments") or "")) // 4 + 1
            total += len(str(activity.get("result_preview") or "")) // 4 + 1
    return total


def _collect_tool_names(transcript_payload: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for entry in transcript_payload:
        for activity in entry.get("tool_activity") or []:
            name = str(activity.get("name") or "").strip()
            if name:
                names.append(name)
    unique = sorted({name for name in names if name})
    return unique


def _collect_recent_user_requests(
    transcript_payload: list[dict[str, Any]], limit: int = 3
) -> list[str]:
    items: list[str] = []
    for entry in reversed(transcript_payload):
        if str(entry.get("role") or "").strip().lower() != "user":
            continue
        text = _truncate_summary(str(entry.get("text") or ""), 160)
        if not text:
            continue
        items.append(text)
        if len(items) >= limit:
            break
    items.reverse()
    return items


def infer_pending_work(transcript_payload: list[dict[str, Any]], limit: int = 3) -> list[str]:
    items: list[str] = []
    for entry in reversed(transcript_payload):
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if not any(pattern in lowered for pattern in _PENDING_PATTERNS):
            continue
        items.append(_truncate_summary(text, 160))
        if len(items) >= limit:
            break
    items.reverse()
    return items


def _has_interesting_extension(candidate: str) -> bool:
    value = str(candidate or "").strip()
    if not value:
        return False
    if "/" not in value and "\\" not in value:
        return False
    return bool(_FILE_EXTENSION_PATTERN.search(value))


def collect_key_files(transcript_payload: list[dict[str, Any]], limit: int = 8) -> list[str]:
    candidates: list[str] = []
    for entry in transcript_payload:
        for token in str(entry.get("text") or "").split():
            candidate = token.strip(",.:;)(\"'`")
            if _has_interesting_extension(candidate):
                candidates.append(candidate.replace("\\", "/"))
    unique = sorted({item for item in candidates if item})
    return unique[:limit]


def infer_current_work(transcript_payload: list[dict[str, Any]]) -> str:
    for entry in reversed(transcript_payload):
        text = _truncate_summary(str(entry.get("text") or ""), 200)
        if text:
            return text
    return ""


def summarize_timeline(transcript_payload: list[dict[str, Any]], limit: int = 40) -> list[str]:
    lines: list[str] = []
    for entry in transcript_payload:
        role = str(entry.get("role") or "").strip().lower() or "assistant"
        if role not in {"user", "assistant", "tool", "system"}:
            role = "assistant"
        text = _truncate_summary(str(entry.get("text") or ""), 160)
        if text:
            lines.append(f"  - {role}: {text}")
        tool_activity = entry.get("tool_activity") or []
        if tool_activity:
            tool_names = [
                str(item.get("name") or "").strip()
                for item in tool_activity
                if str(item.get("name") or "").strip()
            ]
            if tool_names:
                unique_tools = ", ".join(sorted({name for name in tool_names})[:8])
                lines.append(f"    tools: {unique_tools}")
        if len(lines) >= limit:
            break
    return lines[:limit]


def build_compact_summary(transcript_payload: list[dict[str, Any]]) -> str:
    user_messages = sum(
        1 for entry in transcript_payload if str(entry.get("role") or "").strip().lower() == "user"
    )
    assistant_messages = sum(
        1
        for entry in transcript_payload
        if str(entry.get("role") or "").strip().lower() == "assistant"
    )
    tool_messages = sum(
        1
        for entry in transcript_payload
        for part in entry.get("content") or []
        if str(part.get("type") or "").strip().lower() in {"tool_call", "tool_result"}
    )

    tool_names = _collect_tool_names(transcript_payload)
    recent_user_requests = _collect_recent_user_requests(transcript_payload, limit=3)
    pending_work = infer_pending_work(transcript_payload, limit=3)
    key_files = collect_key_files(transcript_payload, limit=8)
    current_work = infer_current_work(transcript_payload)

    lines: list[str] = [
        "<summary>",
        "Conversation summary:",
        f"- Scope: 已压缩 {len(transcript_payload)} 条早期消息（user={user_messages}, assistant={assistant_messages}, tool={tool_messages}）。",
    ]
    if tool_names:
        lines.append(f"- Tools mentioned: {', '.join(tool_names)}.")
    if recent_user_requests:
        lines.append("- Recent user requests:")
        lines.extend([f"  - {item}" for item in recent_user_requests])
    if pending_work:
        lines.append("- Pending work:")
        lines.extend([f"  - {item}" for item in pending_work])
    if key_files:
        lines.append(f"- Key files referenced: {', '.join(key_files)}.")
    if current_work:
        lines.append(f"- Current work: {current_work}")

    lines.append("- Key timeline:")
    lines.extend(summarize_timeline(transcript_payload))
    lines.append("</summary>")
    return "\n".join(lines).strip()


def get_compact_continuation_message(
    summary: str,
    *,
    suppress_follow_up_questions: bool = True,
    recent_messages_preserved: bool = True,
) -> str:
    base = (
        "这是一次从上一段对话中接续的会话，原因是上下文长度已超限。下面的摘要覆盖了更早的对话部分。\n\n"
        + format_compact_summary(summary)
    )
    if recent_messages_preserved:
        base += "\n\n最近的消息已原样保留。"
    if suppress_follow_up_questions:
        base += "\n请从中断处继续推进任务，不要再向用户追问已给出的信息；直接恢复执行，不要对摘要进行复述或额外寒暄。"
    return base.strip()


__all__ = [
    "build_compact_summary",
    "collect_key_files",
    "estimate_transcript_tokens",
    "format_compact_summary",
    "get_compact_continuation_message",
    "infer_pending_work",
]

