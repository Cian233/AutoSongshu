from __future__ import annotations

import re

_MARKDOWN_HEADING_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$")
_VULN_SECTION_PREFIXES = (
    "漏洞",
    "漏洞点",
    "漏洞成因",
    "根因",
    "触发条件",
    "利用条件",
    "影响范围",
    "影响",
    "复现",
    "验证",
    "证据",
    "修复",
    "缓解",
    "检测",
    "排查",
    "误报",
    "建议",
    "风险",
    "cwe",
    "cvss",
    "finding",
    "root cause",
    "trigger",
    "impact",
    "reproduce",
    "evidence",
    "fix",
    "mitigation",
    "detection",
)


def truncate_text(value: str, limit: int = 320) -> str:
    stripped = str(value or "").strip()
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[: max(1, limit - 1)]}…"


def rough_word_count(text: str) -> int:
    english_words = len(re.findall(r"[A-Za-z0-9_]+", text))
    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    return english_words + cjk_chars


def normalize_text(text: str) -> str:
    normalized = (
        str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    )
    return normalized.strip()


def _split_long_line(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    cursor = 0
    while cursor < len(text):
        chunks.append(text[cursor : cursor + max_chars].strip())
        cursor += max_chars
    return [item for item in chunks if item]


def _normalize_heading_title(raw_line: str) -> str:
    line = str(raw_line or "").strip()
    if not line:
        return ""
    markdown_match = _MARKDOWN_HEADING_PATTERN.match(line)
    if markdown_match:
        line = markdown_match.group(1).strip()
    line = re.sub(r"^[\-\*\d\.\)\(、\s]+", "", line).strip()
    line = re.sub(r"[:：]\s*$", "", line).strip()
    return line


def _looks_like_vuln_section_heading(raw_line: str) -> bool:
    raw_text = str(raw_line or "").strip()
    title = _normalize_heading_title(raw_text)
    if not title:
        return False
    lowered = title.lower()
    if any(lowered.startswith(prefix) for prefix in _VULN_SECTION_PREFIXES):
        return True
    if len(raw_text) <= 24 and raw_text.endswith((":", "：")):
        return True
    return False


def _split_document_sections(body: str) -> list[tuple[str, str]]:
    lines = str(body or "").split("\n")
    sections: list[tuple[str, str]] = []
    current_title = ""
    current_lines: list[str] = []

    for raw_line in lines:
        if _MARKDOWN_HEADING_PATTERN.match(
            raw_line
        ) or _looks_like_vuln_section_heading(raw_line):
            if current_lines:
                chunk_body = normalize_text("\n".join(current_lines))
                if chunk_body:
                    sections.append((current_title, chunk_body))
                current_lines = []
            current_title = _normalize_heading_title(raw_line)
            continue
        current_lines.append(raw_line)

    if current_lines:
        chunk_body = normalize_text("\n".join(current_lines))
        if chunk_body:
            sections.append((current_title, chunk_body))

    if not sections:
        return [("", normalize_text(body))]
    return sections


def _find_split_position(text: str, start: int, max_chars: int) -> int:
    hard_end = min(len(text), start + max_chars)
    if hard_end >= len(text):
        return len(text)

    soft_start = start + int(max_chars * 0.55)
    best = -1

    semantic_boundaries = (
        "\n```",
        "```\n",
        "\n|",
        "|\n",
        "\n- ",
        "\n* ",
        "\n1. ",
        "\n> ",
    )
    for token in semantic_boundaries:
        pos = text.rfind(token, soft_start, hard_end)
        if pos > best:
            best = pos + len(token)

    if best > start + int(max_chars * 0.35):
        return best

    for token in ("\n\n", "\n", "。", "！", "？", "；", ". ", "; ", "，", "、", ", "):
        pos = text.rfind(token, soft_start, hard_end)
        if pos > best:
            best = pos + len(token)

    if best <= start + int(max_chars * 0.35):
        return hard_end
    return best


def _split_with_overlap(text: str, *, max_chars: int, overlap_chars: int) -> list[str]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    if len(normalized) <= max_chars:
        return [normalized]

    chunks: list[str] = []
    cursor = 0
    guard = 0
    safe_overlap = max(0, min(overlap_chars, max_chars // 2))

    while cursor < len(normalized):
        guard += 1
        if guard > 2000:
            break
        split_at = _find_split_position(normalized, cursor, max_chars)
        piece = normalized[cursor:split_at].strip()
        if piece:
            chunks.append(piece)
        if split_at >= len(normalized):
            break
        next_cursor = max(cursor + 1, split_at - safe_overlap)
        if next_cursor <= cursor:
            next_cursor = split_at
        cursor = next_cursor

    return chunks


def chunk_document(
    text: str,
    *,
    max_chars: int = 680,
    overlap_chars: int = 120,
    min_chars: int = 120,
) -> list[str]:
    body = normalize_text(text)
    if not body:
        return []

    sections = _split_document_sections(body)
    normalized_max_chars = max(220, int(max_chars or 680))
    normalized_min_chars = max(40, min(int(min_chars or 120), normalized_max_chars))
    normalized_overlap = max(
        0, min(int(overlap_chars or 120), normalized_max_chars // 2)
    )

    chunks: list[str] = []
    seen: set[str] = set()
    parent_title = ""

    for title, section_body in sections:
        section_text = normalize_text(section_body)
        if not section_text:
            continue

        if title and len(title) <= 30:
            parent_title = title

        pieces = _split_with_overlap(
            section_text,
            max_chars=normalized_max_chars,
            overlap_chars=normalized_overlap,
        )
        if not pieces:
            continue

        for idx, piece in enumerate(pieces):
            chunk_parts = []
            if parent_title and parent_title != title:
                chunk_parts.append(f"[{parent_title}]")
            if title:
                chunk_parts.append(title)
            chunk_parts.append(piece.strip())
            chunk = "\n".join(chunk_parts).strip()

            if not chunk:
                continue

            key = chunk.lower()
            if key in seen:
                continue

            if chunks and len(chunk) < normalized_min_chars:
                merged = f"{chunks[-1]}\n{chunk}".strip()
                if len(merged) <= normalized_max_chars + max(
                    12, normalized_overlap // 2
                ):
                    chunks[-1] = merged
                    seen.add(merged.lower())
                    continue

            chunks.append(chunk)
            seen.add(key)

    return chunks
