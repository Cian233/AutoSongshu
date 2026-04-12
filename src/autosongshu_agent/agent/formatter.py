from __future__ import annotations

from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg


def _strip_thinking_blocks(msg: Msg) -> Msg:
    """Return a copy of *msg* with any ``thinking`` blocks removed.

    Some providers (e.g. non-Anthropic OpenAI-compatible endpoints)
    reject messages that contain thinking blocks, so we strip them
    before formatting.
    """
    if isinstance(msg.content, str):
        return msg

    filtered_blocks = [
        block
        for block in msg.content
        if str(block.get("type") or "").strip().lower() != "thinking"
    ]

    return Msg(
        name=msg.name,
        content=filtered_blocks,
        role=msg.role,
        metadata=msg.metadata,
        timestamp=msg.timestamp,
        invocation_id=msg.invocation_id,
    )


class SafeOpenAIChatFormatter(OpenAIChatFormatter):
    """Extended formatter that strips ``thinking`` blocks which some
    providers reject.

    All core formatting (tool_calls, tool results, image blocks,
    truncation, etc.) is delegated to the parent
    :class:`OpenAIChatFormatter`.

    Image viewing is handled by the ``view_image`` tool -- when the
    model decides it needs to see an image, it calls the tool which
    returns an ``image_url`` content block.  The parent formatter
    passes these blocks through to the LLM API unchanged.
    """

    async def _format(self, msgs: list[Msg]) -> list[dict]:
        sanitized = [_strip_thinking_blocks(msg) for msg in msgs]
        return await super()._format(sanitized)


__all__ = ["SafeOpenAIChatFormatter"]
