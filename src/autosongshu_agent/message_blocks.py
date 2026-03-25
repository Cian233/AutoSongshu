from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from uuid import uuid4

TEXT_PART_TYPES = {"input_text", "output_text", "reasoning"}
THINKING_FIELD_NAMES = ("thinking_text", "thinking", "text", "content")


def normalize_content_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        dumped = item.model_dump()
        if isinstance(dumped, dict):
            return dumped
        return {"type": "text", "text": str(dumped)}
    if hasattr(item, "dict"):
        dumped = item.dict()
        if isinstance(dumped, dict):
            return dumped
        return {"type": "text", "text": str(dumped)}
    return {"type": "text", "text": str(item)}


def normalize_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return deepcopy(raw_arguments)
    return {"value": raw_arguments}


def _fallback_tool_call_id(name: str, raw_arguments: Any) -> str:
    serialized_arguments = json.dumps(
        normalize_tool_arguments(raw_arguments),
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return f"tool_call:{name}:{serialized_arguments}"


def normalize_tool_result_content(raw_output: Any) -> list[dict[str, Any]]:
    outputs = raw_output if isinstance(raw_output, list) else [raw_output]
    items: list[dict[str, Any]] = []
    for output in outputs:
        if output is None:
            continue
        normalized = normalize_content_item(output)
        output_type = str(normalized.get("type") or "").strip().lower()
        if output_type in {"text", "output_text"}:
            items.append(
                {"type": "output_text", "text": str(normalized.get("text") or "")}
            )
            continue
        items.append(
            {
                "type": "output_text",
                "text": json.dumps(output, ensure_ascii=False, indent=2, default=str),
            },
        )
    return items


def _first_text_value(payload: dict[str, Any], field_names: tuple[str, ...]) -> str:
    for field_name in field_names:
        value = payload.get(field_name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _append_part(parts: list[dict[str, Any]], part: dict[str, Any]) -> None:
    part_type = str(part.get("type") or "").strip().lower()
    if part_type in TEXT_PART_TYPES:
        text = str(part.get("text") or "").strip()
        if not text:
            return
        if parts and str(parts[-1].get("type") or "").strip().lower() == part_type:
            previous_text = str(parts[-1].get("text") or "").strip()
            if text == previous_text or previous_text.startswith(text):
                return
            if text.startswith(previous_text):
                parts[-1]["text"] = text
                return
        parts.append({"type": part_type, "text": text})
        return

    if parts:
        previous = parts[-1]
        previous_type = str(previous.get("type") or "").strip().lower()
        if part_type == previous_type == "tool_call" and str(
            previous.get("id") or ""
        ) == str(part.get("id") or ""):
            parts[-1] = deepcopy(part)
            return
        if (
            part_type == previous_type == "tool_result"
            and str(previous.get("tool_call_id") or "")
            == str(part.get("tool_call_id") or "")
            and str(previous.get("name") or "") == str(part.get("name") or "")
        ):
            parts[-1] = deepcopy(part)
            return

    parts.append(deepcopy(part))


def _match_score(existing: dict[str, Any], incoming: dict[str, Any]) -> int:
    existing_type = str(existing.get("type") or "").strip().lower()
    incoming_type = str(incoming.get("type") or "").strip().lower()
    if existing_type != incoming_type:
        return 0

    if existing_type in TEXT_PART_TYPES:
        existing_text = str(existing.get("text") or "").strip()
        incoming_text = str(incoming.get("text") or "").strip()
        if not existing_text or not incoming_text:
            return 0
        if existing_text == incoming_text:
            return 400 + len(existing_text)
        if existing_text.startswith(incoming_text) or incoming_text.startswith(
            existing_text
        ):
            return 300 + min(len(existing_text), len(incoming_text))
        return 0

    if existing_type == "tool_call":
        existing_id = str(existing.get("id") or "").strip()
        incoming_id = str(incoming.get("id") or "").strip()
        if existing_id and incoming_id and existing_id == incoming_id:
            return 500
        existing_name = str(existing.get("name") or "").strip()
        incoming_name = str(incoming.get("name") or "").strip()
        if existing_name and incoming_name and existing_name == incoming_name:
            existing_is_fallback = existing_id.startswith("tool_call:")
            incoming_is_fallback = incoming_id.startswith("tool_call:")
            if (existing_is_fallback or incoming_is_fallback) and (
                not existing_id or not incoming_id or existing_id != incoming_id
            ):
                return 400
        return 0

    if existing_type == "tool_result":
        existing_tool_call_id = str(existing.get("tool_call_id") or "").strip()
        incoming_tool_call_id = str(incoming.get("tool_call_id") or "").strip()
        existing_name = str(existing.get("name") or "").strip()
        incoming_name = str(incoming.get("name") or "").strip()
        if (
            existing_tool_call_id
            and incoming_tool_call_id
            and existing_tool_call_id == incoming_tool_call_id
        ):
            if existing_name == incoming_name:
                return 500
        return 0

    return 100 if existing == incoming else 0


def _find_best_match_index(
    parts: list[dict[str, Any]],
    incoming: dict[str, Any],
    start_index: int = 0,
) -> int | None:
    best_index: int | None = None
    best_score = 0
    for index in range(max(0, start_index), len(parts)):
        score = _match_score(parts[index], incoming)
        if score <= best_score:
            continue
        best_index = index
        best_score = score
        if score >= 500:
            break
    return best_index


def _find_insertion_anchor(
    merged: list[dict[str, Any]],
    incoming_parts: list[dict[str, Any]],
    *,
    next_part_index: int,
    cursor: int,
) -> int | None:
    for future_part in incoming_parts[next_part_index:]:
        match_index = _find_best_match_index(merged, future_part, start_index=cursor)
        if match_index is not None:
            return match_index
    return None


def compact_assistant_content(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted: list[dict[str, Any]] = []
    for part in parts:
        match_index = _find_best_match_index(compacted, part, start_index=0)
        if match_index is not None:
            compacted[match_index] = _merge_part(compacted[match_index], part)
            continue
        _append_part(compacted, part)
    return compacted


def normalize_message_part(part: Any, role: str | None = None) -> dict[str, Any] | None:
    normalized = normalize_content_item(part)
    part_type = str(normalized.get("type") or "").strip().lower()
    normalized_role = str(role or "").strip().lower()

    if normalized_role == "user":
        text = _first_text_value(normalized, ("text", "content"))
        if not text:
            return None
        return {"type": "input_text", "text": text}

    if part_type in {"reasoning", "thinking", "thinking_text"}:
        text = _first_text_value(normalized, THINKING_FIELD_NAMES)
        if not text:
            return None
        return {"type": "reasoning", "text": text}

    if part_type in {"input_text", "output_text", "text", "progress_text"}:
        text = _first_text_value(normalized, ("text", "content"))
        if not text:
            return None
        target_type = "input_text" if normalized_role == "user" else "output_text"
        return {"type": target_type, "text": text}

    if part_type in {"tool_call", "tool_use"}:
        name = str(normalized.get("name") or "tool")
        arguments = normalize_tool_arguments(
            normalized.get("arguments", normalized.get("input"))
        )
        return {
            "type": "tool_call",
            "id": str(normalized.get("id") or _fallback_tool_call_id(name, arguments)),
            "name": name,
            "arguments": arguments,
        }

    if part_type == "tool_result":
        return {
            "type": "tool_result",
            "tool_call_id": str(
                normalized.get("tool_call_id") or normalized.get("id") or ""
            ),
            "name": str(normalized.get("name") or ""),
            "content": normalize_tool_result_content(
                normalized.get("content", normalized.get("output")),
            ),
        }

    text = _first_text_value(normalized, ("text", "content"))
    if not text:
        return None
    return {"type": "output_text", "text": text}


def _as_items(content: Any) -> list[Any]:
    if content is None:
        return []
    if isinstance(content, list):
        return content
    return [content]


def normalize_message_content(
    content: list[dict[str, Any]] | list[Any], role: str | None = None
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for item in _as_items(content):
        normalized = normalize_message_part(item, role=role)
        if normalized is None:
            continue
        _append_part(parts, normalized)
    if str(role or "").strip().lower() == "assistant":
        return compact_assistant_content(parts)
    return parts


def unresolved_tool_call_ids(content: list[dict[str, Any]] | list[Any]) -> list[str]:
    parts = normalize_message_content(_as_items(content), role="assistant")
    resolved_ids = {
        str(part.get("tool_call_id") or "").strip()
        for part in parts
        if str(part.get("type") or "").strip().lower() == "tool_result"
        and str(part.get("tool_call_id") or "").strip()
    }
    return [
        str(part.get("id") or "").strip()
        for part in parts
        if str(part.get("type") or "").strip().lower() == "tool_call"
        and str(part.get("id") or "").strip()
        and str(part.get("id") or "").strip() not in resolved_ids
    ]


def finalize_completed_assistant_content(
    content: list[dict[str, Any]] | list[Any],
) -> list[dict[str, Any]]:
    parts = normalize_message_content(_as_items(content), role="assistant")
    unresolved_ids = set(unresolved_tool_call_ids(parts))
    if not unresolved_ids:
        return parts
    return [
        part
        for part in parts
        if not (
            str(part.get("type") or "").strip().lower() == "tool_call"
            and str(part.get("id") or "").strip() in unresolved_ids
        )
    ]


def assistant_content_from_blocks(
    blocks: list[dict[str, Any]] | list[Any] | None,
    fallback_text: str = "",
) -> list[dict[str, Any]]:
    parts = normalize_message_content(_as_items(blocks), role="assistant")
    if not parts and str(fallback_text or "").strip():
        parts.append({"type": "output_text", "text": str(fallback_text).strip()})
    return parts


def assistant_preview_text(
    blocks: list[dict[str, Any]] | list[Any] | None, fallback_text: str = ""
) -> str:
    parts = assistant_content_from_blocks(blocks, fallback_text="")
    values = [
        str(part.get("text") or "").strip()
        for part in parts
        if str(part.get("type") or "").strip().lower() == "output_text"
        and str(part.get("text") or "").strip()
    ]
    if values:
        return "\n\n".join(values).strip()
    return str(fallback_text or "").strip()


def message_text(content: list[dict[str, Any]] | list[Any]) -> str:
    parts = normalize_message_content(_as_items(content))
    values = [
        str(part.get("text") or "").strip()
        for part in parts
        if str(part.get("type") or "").strip().lower() in {"input_text", "output_text"}
        and str(part.get("text") or "").strip()
    ]
    return "\n\n".join(values).strip()


def _parts_match(existing: dict[str, Any], incoming: dict[str, Any]) -> bool:
    return _match_score(existing, incoming) > 0


def _merge_part(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing_type = str(existing.get("type") or "").strip().lower()
    if existing_type in TEXT_PART_TYPES:
        existing_text = str(existing.get("text") or "").strip()
        incoming_text = str(incoming.get("text") or "").strip()
        if incoming_text.startswith(existing_text):
            return {"type": existing_type, "text": incoming_text}
        return deepcopy(
            existing if len(existing_text) >= len(incoming_text) else incoming
        )
    if existing_type == "tool_call":
        merged = deepcopy(incoming)
        existing_id = str(existing.get("id") or "").strip()
        incoming_id = str(incoming.get("id") or "").strip()
        if existing_id and (not incoming_id or existing_id != incoming_id):
            merged["id"] = existing_id
        return merged
    return deepcopy(incoming)


def merge_assistant_content(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = normalize_message_content(existing, role="assistant")
    incoming_parts = normalize_message_content(incoming, role="assistant")
    cursor = 0
    for part_index, part in enumerate(incoming_parts):
        found_index = _find_best_match_index(merged, part, start_index=cursor)
        if found_index is not None:
            merged[found_index] = _merge_part(merged[found_index], part)
            cursor = found_index + 1
            continue

        anchor_index = _find_insertion_anchor(
            merged,
            incoming_parts,
            next_part_index=part_index + 1,
            cursor=cursor,
        )
        if anchor_index is None:
            merged.append(deepcopy(part))
            cursor = len(merged)
            continue

        merged.insert(anchor_index, deepcopy(part))
        cursor = anchor_index + 1

    return compact_assistant_content(merged)


def part_to_agent_block(part: dict[str, Any]) -> dict[str, Any]:
    part_type = str(part.get("type") or "").strip().lower()
    if part_type == "reasoning":
        text = str(part.get("text") or "")
        return {"type": "thinking", "thinking": text, "thinking_text": text}
    if part_type == "output_text":
        return {"type": "text", "text": str(part.get("text") or "")}
    if part_type == "tool_call":
        return {
            "type": "tool_use",
            "id": str(part.get("id") or uuid4().hex),
            "name": str(part.get("name") or "tool"),
            "input": deepcopy(part.get("arguments") or {}),
        }
    if part_type == "tool_result":
        output = []
        for item in part.get("content") or []:
            if str(item.get("type") or "").strip().lower() == "output_text":
                output.append({"type": "text", "text": str(item.get("text") or "")})
                continue
            output.append(
                {
                    "type": "text",
                    "text": json.dumps(item, ensure_ascii=False, default=str),
                }
            )
        return {
            "type": "tool_result",
            "id": str(part.get("tool_call_id") or ""),
            "name": str(part.get("name") or ""),
            "output": output,
        }
    return {"type": "text", "text": json.dumps(part, ensure_ascii=False, default=str)}
