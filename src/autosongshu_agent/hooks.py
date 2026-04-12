"""Hook system for tool execution lifecycle.

Ported from claw-code's hook system. Provides pre-tool-use, post-tool-use,
and post-tool-use-failure hooks for extensibility.

Hooks can:
- Inspect and modify tool arguments before execution
- Inspect tool results after execution
- Deny tool execution based on custom logic
- Collect metrics and audit logs
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("autosongshu.hooks")


class HookEvent(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL_USE_FAILURE = "post_tool_use_failure"


@dataclass
class HookContext:
    """Context passed to hook handlers."""
    event: HookEvent
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: Exception | None = None
    duration_ms: float = 0.0
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # Set by hooks to influence execution
    denied: bool = False
    deny_reason: str = ""
    modified_arguments: dict[str, Any] | None = None


class HookResult:
    """Result from a hook execution."""

    __slots__ = ("denied", "deny_reason", "modified_arguments", "messages")

    def __init__(
        self,
        denied: bool = False,
        deny_reason: str = "",
        modified_arguments: dict[str, Any] | None = None,
        messages: list[str] | None = None,
    ):
        self.denied = denied
        self.deny_reason = deny_reason
        self.modified_arguments = modified_arguments
        self.messages = messages or []


class ToolHook(ABC):
    """Abstract base class for tool hooks."""

    @abstractmethod
    def on_event(self, ctx: HookContext) -> HookResult:
        """Handle a hook event. Return HookResult to influence execution."""
        ...


class FunctionHook(ToolHook):
    """Hook implemented as a simple function."""

    def __init__(self, func: Callable[[HookContext], HookResult]):
        self.func = func
        self.__name__ = getattr(func, "__name__", "function_hook")

    def on_event(self, ctx: HookContext) -> HookResult:
        try:
            return self.func(ctx)
        except Exception as exc:
            logger.warning("FunctionHook %s failed: %s", self.__name__, exc)
            return HookResult()


class AuditLogHook(ToolHook):
    """Built-in hook that logs all tool calls for audit purposes."""

    def on_event(self, ctx: HookContext) -> HookResult:
        if ctx.event == HookEvent.PRE_TOOL_USE:
            logger.info(
                "TOOL_CALL tool=%s args=%s session=%s",
                ctx.tool_name,
                _safe_repr(ctx.arguments),
                ctx.session_id[:8] if ctx.session_id else "-",
            )
        elif ctx.event == HookEvent.POST_TOOL_USE:
            logger.info(
                "TOOL_RESULT tool=%s duration=%.0fms session=%s",
                ctx.tool_name,
                ctx.duration_ms,
                ctx.session_id[:8] if ctx.session_id else "-",
            )
        elif ctx.event == HookEvent.POST_TOOL_USE_FAILURE:
            logger.warning(
                "TOOL_ERROR tool=%s error=%s duration=%.0fms session=%s",
                ctx.tool_name,
                str(ctx.error)[:200] if ctx.error else "unknown",
                ctx.duration_ms,
                ctx.session_id[:8] if ctx.session_id else "-",
            )
        return HookResult()


class HookRunner:
    """Manages and executes tool hooks."""

    def __init__(self) -> None:
        self._hooks: list[ToolHook] = []

    def add_hook(self, hook: ToolHook) -> None:
        self._hooks.append(hook)

    def remove_hook(self, hook: ToolHook) -> bool:
        try:
            self._hooks.remove(hook)
            return True
        except ValueError:
            return False

    def run_pre_tool_use(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session_id: str = "",
    ) -> tuple[bool, str, dict[str, Any] | None]:
        """Run pre-tool-use hooks. Returns (denied, deny_reason, modified_arguments)."""
        if not self._hooks:
            return False, "", None

        ctx = HookContext(
            event=HookEvent.PRE_TOOL_USE,
            tool_name=tool_name,
            arguments=arguments,
            session_id=session_id,
        )

        for hook in self._hooks:
            try:
                result = hook.on_event(ctx)
                if result.denied:
                    return True, result.deny_reason or "Denied by hook", None
                if result.modified_arguments:
                    ctx.arguments = result.modified_arguments
            except Exception as exc:
                logger.warning("Pre-tool hook failed for %s: %s", tool_name, exc)

        return False, "", ctx.arguments if ctx.modified_arguments is None else ctx.modified_arguments

    def run_post_tool_use(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        duration_ms: float,
        session_id: str = "",
    ) -> None:
        """Run post-tool-use hooks."""
        if not self._hooks:
            return

        ctx = HookContext(
            event=HookEvent.POST_TOOL_USE,
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            duration_ms=duration_ms,
            session_id=session_id,
        )

        for hook in self._hooks:
            try:
                hook.on_event(ctx)
            except Exception as exc:
                logger.warning("Post-tool hook failed for %s: %s", tool_name, exc)

    def run_post_tool_use_failure(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        error: Exception,
        duration_ms: float,
        session_id: str = "",
    ) -> None:
        """Run post-tool-use-failure hooks."""
        if not self._hooks:
            return

        ctx = HookContext(
            event=HookEvent.POST_TOOL_USE_FAILURE,
            tool_name=tool_name,
            arguments=arguments,
            error=error,
            duration_ms=duration_ms,
            session_id=session_id,
        )

        for hook in self._hooks:
            try:
                hook.on_event(ctx)
            except Exception as exc:
                logger.warning("Post-tool-failure hook failed for %s: %s", tool_name, exc)

    def list_hooks(self) -> list[str]:
        return [getattr(h, "__name__", type(h).__name__) for h in self._hooks]


def _safe_repr(obj: Any, max_len: int = 200) -> str:
    """Safely repr an object, truncating if too long."""
    try:
        s = repr(obj)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return s
    except Exception:
        return "<unrepresentable>"


# Global hook runner singleton
_global_hook_runner: HookRunner | None = None


def get_hook_runner() -> HookRunner:
    global _global_hook_runner
    if _global_hook_runner is None:
        _global_hook_runner = HookRunner()
        # Always add audit log hook
        _global_hook_runner.add_hook(AuditLogHook())
    return _global_hook_runner


__all__ = [
    "HookEvent",
    "HookContext",
    "HookResult",
    "ToolHook",
    "FunctionHook",
    "AuditLogHook",
    "HookRunner",
    "get_hook_runner",
]
