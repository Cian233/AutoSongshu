"""
Fork Subagent - Share context with parent agent.

Inspired by claw-code's tools/AgentTool/forkSubagent.ts

Key concept:
- Fresh agent: New context, no history
- Fork agent: Inherit parent's context and share prompt cache

Fork is more efficient for tasks that can reuse parent's context.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


FORK_BOILERPLATE_TAG = "fork-boilerplate"


@dataclass
class ForkDirective:
    """Directive for a forked subagent."""

    agent_type: str
    task: str
    share_abort_controller: bool = False
    share_set_app_state: bool = False


def build_forked_messages(
    directive: str,
    assistant_message: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Build messages for a forked subagent.

    Key insight: All fork messages should be byte-identical except the final directive.
    This maximizes prompt cache hit rate.

    Structure:
    [...history, assistant(all_tool_uses), user(placeholder_results..., directive)]

    Only the directive differs between fork siblings.
    """
    # Get all tool_use blocks from assistant message
    content = assistant_message.get("content", [])
    tool_use_blocks = [block for block in content if block.get("type") == "tool_use"]

    # Create placeholder tool results
    tool_result_blocks = [
        {
            "type": "tool_result",
            "tool_use_id": block["id"],
            "content": [
                {"type": "text", "text": "Fork started — processing in background"}
            ],
        }
        for block in tool_use_blocks
    ]

    # Create the fork directive message
    fork_directive = f"""
<{FORK_BOILERPLATE_TAG}>
This is a forked subagent context.
Agent type: general-purpose
Task: {directive}
</{FORK_BOILERPLATE_TAG}>
""".strip()

    # Build the user message with all tool results + directive
    user_message = {
        "role": "user",
        "content": [
            *tool_result_blocks,
            {"type": "text", "text": fork_directive},
        ],
    }

    # Return assistant (with new UUID) + user message
    return [
        {**assistant_message, "id": f"msg_{uuid.uuid4().hex[:8]}"},
        user_message,
    ]


def is_in_fork_child(messages: list[dict[str, Any]]) -> bool:
    """
    Check if current context is a fork child.

    Used to prevent recursive forking.
    """
    for message in messages:
        if message.get("role") != "user":
            continue

        content = message.get("content", [])
        if isinstance(content, str):
            if FORK_BOILERPLATE_TAG in content:
                return True
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    if FORK_BOILERPLATE_TAG in block.get("text", ""):
                        return True

    return False


__all__ = [
    "ForkDirective",
    "build_forked_messages",
    "is_in_fork_child",
    "FORK_BOILERPLATE_TAG",
]
