from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


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


def estimate_transcript_tokens(text: str, chars_per_token: float = 3.0) -> int:
    """Estimate token count for a text string.

    Uses a conservative chars-per-token ratio. For more accurate counting,
    use TokenBudgetTracker.count_tokens() which leverages tiktoken when available.
    """
    return max(1, int(len(text) / chars_per_token))


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


def _extract_discoveries(
    transcript_payload: list[dict[str, Any]],
    limit: int = 8,
) -> list[str]:
    """Extract key findings from assistant messages in the transcript."""
    discoveries: list[str] = []
    _discovery_keywords = [
        "发现", "漏洞", "vulnerability", "finding", "confirmed",
        "validated", "成功", "success", "检测到", "identified",
        "exploit", "注入", "injection", "xss", "sql injection",
        "ssrf", "rce", "认证", "auth", "权限", "permission",
    ]
    for entry in reversed(transcript_payload):
        if len(discoveries) >= limit:
            break
        role = str(entry.get("role") or "").strip().lower()
        if role != "assistant":
            continue
        content_parts = entry.get("content") or []
        if isinstance(content_parts, str):
            content_parts = [{"type": "text", "text": content_parts}]
        for part in content_parts:
            if not isinstance(part, dict):
                continue
            text = str(part.get("text") or "").strip()
            if not text or len(text) < 10:
                continue
            # Check if this text contains a discovery keyword
            text_lower = text.lower()
            if any(kw in text_lower for kw in _discovery_keywords):
                # Truncate to first sentence or 120 chars
                sentence_end = min(
                    text.find("。"),
                    text.find("."),
                    text.find("\n"),
                    120,
                )
                if sentence_end <= 0:
                    sentence_end = min(120, len(text))
                snippet = text[:sentence_end].strip()
                if snippet and snippet not in discoveries:
                    discoveries.append(snippet)
    return discoveries


def build_compact_summary(transcript_payload: list[dict[str, Any]]) -> str:
    """Build a structured XML summary of compacted messages.

    Inspired by OpenCode's compaction template, the summary uses fixed
    sections (Goal, Discoveries, Accomplished, Files) to ensure critical
    context dimensions are never omitted, even when information is sparse.
    """
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
    recent_user_requests = _collect_recent_user_requests(transcript_payload, limit=5)
    pending_work = infer_pending_work(transcript_payload, limit=5)
    key_files = collect_key_files(transcript_payload, limit=12)
    current_work = infer_current_work(transcript_payload)

    lines: list[str] = [
        "<summary>",
        f"已压缩 {len(transcript_payload)} 条早期消息（user={user_messages}, assistant={assistant_messages}, tool={tool_messages}）。",
        "",
        "## Goal（用户目标）",
    ]

    # Goal section — always present, even if empty
    goal_items = recent_user_requests[:3] if recent_user_requests else ["（未明确记录）"]
    for item in goal_items:
        lines.append(f"- {item}")

    lines.append("")
    lines.append("## Discoveries（关键发现）")

    # Extract findings from assistant messages
    discoveries = _extract_discoveries(transcript_payload, limit=8)
    if discoveries:
        for item in discoveries:
            lines.append(f"- {item}")
    else:
        lines.append("- （无明确发现记录）")

    lines.append("")
    lines.append("## Accomplished（已完成 / 进行中 / 待完成）")

    if current_work:
        lines.append(f"- 当前工作: {current_work}")
    if pending_work:
        for item in pending_work:
            lines.append(f"- 待完成: {item}")
    if not current_work and not pending_work:
        lines.append("- （未明确记录）")

    lines.append("")
    lines.append("## Tools & Files（工具与文件）")

    if tool_names:
        lines.append(f"- 使用的工具: {', '.join(tool_names)}")
    if key_files:
        lines.append(f"- 关键文件: {', '.join(key_files)}")

    lines.append("")
    lines.append("## Timeline（时间线）")
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
    "build_semantic_compact_summary",
    "collect_key_files",
    "CompactionStrategy",
    "estimate_transcript_tokens",
    "format_compact_summary",
    "get_compact_continuation_message",
    "infer_pending_work",
    "MessageImportance",
    "score_message_importance",
    "select_messages_for_compaction",
]


# ── Compaction Strategy Enum ──────────────────────────────────────

class CompactionStrategy(str, enum.Enum):
    """Available compaction strategies."""

    RULE_BASED = "rule_based"
    LLM_DRIVEN = "llm_driven"
    HYBRID = "hybrid"


# ── Message Importance Scoring ────────────────────────────────────

@dataclass
class MessageImportance:
    """Importance score and metadata for a conversation message."""

    message_index: int
    score: float = 0.5
    role: str = ""
    has_findings: bool = False
    has_tool_calls: bool = False
    is_recent: bool = False
    is_system: bool = False
    turn_number: int = 0


def score_message_importance(
    message: dict[str, Any],
    total_messages: int,
    current_turn: int,
) -> MessageImportance:
    """Calculate an importance score for a conversation message.

    Scoring factors:
    - Time decay: recent messages get higher scores (0-0.3)
    - Role weight: assistant messages with findings get higher scores (0-0.2)
    - Content value: messages containing findings, tool results, or decisions (0-0.3)
    - Structural importance: first/last messages in a turn (0-0.2)

    Returns a score between 0.0 (discard first) and 1.0 (keep at all costs).
    """
    idx = message.get("index", 0)
    role = message.get("role", "")
    content = message.get("content", "")

    importance = MessageImportance(
        message_index=idx,
        role=role,
    )

    # Factor 1: Time decay (recent messages are more important)
    recency = idx / max(total_messages - 1, 1)  # 0.0 for oldest, 1.0 for newest
    importance.is_recent = recency > 0.7
    importance.score += recency * 0.3

    # Factor 2: Role weight
    if role == "system":
        importance.is_system = True
        importance.score += 0.2
    elif role == "assistant":
        importance.score += 0.1

    # Factor 3: Content value
    content_lower = content.lower() if isinstance(content, str) else ""
    importance.has_tool_calls = "tool_call" in content_lower or "tool_result" in content_lower
    importance.has_findings = any(
        kw in content_lower
        for kw in ["finding", "vulnerability", "漏洞", "发现", "confirmed", "validated"]
    )
    if importance.has_findings:
        importance.score += 0.25
    if importance.has_tool_calls:
        importance.score += 0.1

    # Factor 4: Structural importance (first/last in turn)
    turn_num = message.get("turn_number", 0)
    importance.turn_number = turn_num
    if turn_num == current_turn:
        importance.score += 0.15

    # Clamp to [0, 1]
    importance.score = min(1.0, max(0.0, importance.score))

    return importance


def select_messages_for_compaction(
    messages: list[dict[str, Any]],
    keep_count: int = 6,
    importance_threshold: float = 0.6,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split messages into 'keep' and 'compact' groups based on importance.

    Args:
        messages: All active messages in the conversation.
        keep_count: Minimum number of messages to keep (most recent).
        importance_threshold: Messages scoring below this are candidates for compaction.

    Returns:
        A tuple of (messages_to_keep, messages_to_compact).
    """
    if len(messages) <= keep_count:
        return messages, []

    current_turn = max(m.get("turn_number", 0) for m in messages) if messages else 0

    scored = [
        (msg, score_message_importance(msg, len(messages), current_turn))
        for msg in messages
    ]

    # Always keep the most recent `keep_count` messages
    recent = scored[-keep_count:]
    candidates = scored[:-keep_count]

    # Among candidates, keep those above threshold
    keep_msgs = [msg for msg, imp in candidates if imp.score >= importance_threshold]
    compact_msgs = [msg for msg, imp in candidates if imp.score < importance_threshold]

    # Add back the recent messages
    keep_msgs.extend(msg for msg, _ in recent)

    # Sort by original index
    keep_msgs.sort(key=lambda m: m.get("index", 0))
    compact_msgs.sort(key=lambda m: m.get("index", 0))

    return keep_msgs, compact_msgs


# ── LLM-Driven Semantic Compaction ────────────────────────────────

async def build_semantic_compact_summary(
    messages_to_compact: list[dict[str, Any]],
    *,
    model_client: Any | None = None,
    max_summary_chars: int = 4000,
) -> str:
    """Generate a semantic summary of messages using an LLM.

    This function attempts to use the configured LLM to produce a
    high-quality summary.  If the LLM is unavailable, it falls back
    to :func:`build_compact_summary`.

    Args:
        messages_to_compact: Messages that should be summarized.
        model_client: An LLM client with a ``chat`` method (optional).
        max_summary_chars: Maximum length of the generated summary.

    Returns:
        A structured summary string.
    """
    if not messages_to_compact:
        return ""

    # Build a text representation of messages to compact
    transcript_text = _format_messages_for_compaction(messages_to_compact)

    if model_client is not None:
        try:
            summary = await _llm_summarize(
                model_client, transcript_text, max_summary_chars
            )
            if summary:
                return summary
        except Exception as exc:
            logger.warning("LLM-driven compaction failed, falling back to rules: %s", exc)

    # Fallback to rule-based compaction
    return build_compact_summary(messages_to_compact)


def _format_messages_for_compaction(
    messages: list[dict[str, Any]],
) -> str:
    """Format messages into a compact text for LLM summarization."""
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if isinstance(content, str) and content:
            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            parts.append(f"[{role}]: {content}")
    return "\n\n".join(parts)


async def _llm_summarize(
    model_client: Any,
    transcript_text: str,
    max_chars: int,
) -> str:
    """Call the LLM to generate a summary of the transcript."""
    prompt = (
        "You are a concise summarizer for a security testing agent. "
        "Summarize the following conversation transcript, focusing on:\n"
        "1. Key findings and vulnerabilities discovered\n"
        "2. Tools used and their results\n"
        "3. Decisions made and reasoning\n"
        "4. Pending work and next steps\n"
        "5. Important URLs, paths, and parameters\n\n"
        f"Transcript:\n{transcript_text}\n\n"
        f"Provide a structured summary in {max_chars // 4} words or less. "
        "Use Simplified Chinese."
    )
    # Attempt to call the model - adapt to different client interfaces
    if hasattr(model_client, "chat"):
        response = await model_client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=max_chars // 4,
        )
        if hasattr(response, "content"):
            return str(response.content)[:max_chars]
        if isinstance(response, dict):
            return str(response.get("content", response.get("text", "")))[:max_chars]
        return str(response)[:max_chars]
    raise ValueError("model_client does not have a compatible chat() method")

