from __future__ import annotations

from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import Msg


def _strip_thinking_blocks(msg: Msg) -> Msg:
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
    async def _format(self, msgs: list[Msg]) -> list[dict]:
        sanitized_msgs = [_strip_thinking_blocks(msg) for msg in msgs]
        return await super()._format(sanitized_msgs)


__all__ = ["SafeOpenAIChatFormatter"]
