"""User interaction tools.

Ported from claw-code's AskUserQuestion and SendUserMessage tools.
Allows the agent to ask clarifying questions and send messages to the user.
"""
from __future__ import annotations

import json
from typing import Any

from agentscope.tool import ToolResponse

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _tool_response, _error_response

registry.create_group(
    "interaction",
    description="用户交互工具：向用户提问、发送消息。",
    risk_level=ToolRiskLevel.LOW,
)


@registry.register(
    "interaction",
    description="向用户提问并等待回答。适用于需要用户确认、选择方案或提供额外信息的场景。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=False,
)
def ask_user(
    runtime: PentestRuntime,
    question: str,
    options: str = "",
    multi_select: bool = False,
) -> ToolResponse:
    """Ask the user a question and wait for their response.

    Args:
        question: The question to ask the user.
        options: JSON array of option strings. If empty, user can provide free-text response.
        multi_select: If true, user can select multiple options.
    """
    try:
        parsed_options: list[str] = []
        if options.strip():
            try:
                parsed_options = json.loads(options)
                if not isinstance(parsed_options, list):
                    parsed_options = [str(parsed_options)]
            except json.JSONDecodeError:
                parsed_options = [o.strip() for o in options.split(",") if o.strip()]

        # Store the question in runtime for the frontend to pick up
        question_data = {
            "type": "ask_user",
            "question": question,
            "options": parsed_options,
            "multi_select": multi_select,
            "timestamp": __import__("time").time(),
        }

        # Write to artifacts for persistence
        runtime.artifacts.write_json("pending_question.json", question_data)

        # Also emit via SSE if possible
        if hasattr(runtime, "_emit_event"):
            runtime._emit_event("user.question", **question_data)

        return _tool_response({
            "ok": True,
            "message": f"已向用户提问: {question}",
            "question": question,
            "options": parsed_options,
            "waiting_for_response": True,
        })
    except Exception as exc:
        return _error_response(exc)


@registry.register(
    "interaction",
    description="向用户发送消息。适用于需要主动通知用户某些信息（如发现重要漏洞、需要等待等）。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=False,
)
def send_message(
    runtime: PentestRuntime,
    message: str,
    level: str = "info",
) -> ToolResponse:
    """Send a message to the user.

    Args:
        message: The message content to send.
        level: Message level: "info", "warning", "success", "error".
    """
    try:
        level = str(level).strip().lower()
        if level not in {"info", "warning", "success", "error"}:
            level = "info"

        message_data = {
            "type": "send_message",
            "message": message,
            "level": level,
            "timestamp": __import__("time").time(),
        }

        runtime.artifacts.write_json("last_message.json", message_data)

        if hasattr(runtime, "_emit_event"):
            runtime._emit_event("user.message", **message_data)

        return _tool_response({
            "ok": True,
            "message": message,
            "level": level,
        })
    except Exception as exc:
        return _error_response(exc)
