"""
ToolUseContext - Runtime context for tool execution - Layer 3 of the three-layer architecture.

This is the "messenger" that connects all state layers. It's passed to every tool
execution and provides access to:
- AppState (via get_app_state/set_app_state)
- Session state (via bootstrap getters)
- Execution runtime (abort signal, file cache, etc.)

Inspired by claw-code's Tool.ts:158-254 and utils/forkedAgent.ts:345-462
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AbortController:
    """Simple abort controller for cancellation."""

    _aborted: bool = False

    def abort(self) -> None:
        """Signal abort."""
        self._aborted = True

    @property
    def is_aborted(self) -> bool:
        """Check if aborted."""
        return self._aborted


@dataclass
class FileStateCache:
    """
    LRU cache for file state.
    Each tool execution has its own cache instance.
    """

    _cache: dict[str, Any] = field(default_factory=dict)
    _max_size: int = 100

    def get(self, key: str) -> Any | None:
        return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        if len(self._cache) >= self._max_size:
            # Remove oldest entry (simple FIFO, not true LRU)
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[key] = value

    def clear(self) -> None:
        self._cache.clear()

    def copy(self) -> "FileStateCache":
        """Create a shallow copy."""
        new_cache = FileStateCache(_max_size=self._max_size)
        new_cache._cache = self._cache.copy()
        return new_cache


@dataclass
class ToolUseContext:
    """
    Runtime context for tool execution.

    Design principles:
    - Default isolation, explicit sharing (for subagents)
    - get_app_state/set_app_state can be stubbed (for async agents)
    - set_app_state_for_tasks always penetrates to root store
    """

    # Options (tools, commands, models, etc.)
    options: dict[str, Any] = field(default_factory=dict)

    # Abort controller for cancellation
    abort_controller: AbortController = field(default_factory=AbortController)

    # File state cache (LRU)
    read_file_state: FileStateCache = field(default_factory=FileStateCache)

    # AppState access - can be stubbed for async agents
    get_app_state: Callable[[], dict[str, Any]] = field(
        default_factory=lambda: lambda: {}
    )
    set_app_state: Callable[[Callable[[dict], dict]], None] = field(
        default_factory=lambda: lambda _: None
    )

    # Task-level setter - ALWAYS penetrates to root store
    # Even when set_app_state is no-op, this must reach root to avoid zombie processes
    set_app_state_for_tasks: Callable[[Callable[[dict], dict]], None] | None = None

    # Agent info
    agent_id: str = field(default_factory=lambda: f"agent-{uuid.uuid4().hex[:8]}")
    agent_type: str | None = None

    # Messages for context
    messages: list[dict[str, Any]] = field(default_factory=list)

    # Nested memory triggers (for agent isolation)
    nested_memory_triggers: set[str] = field(default_factory=set)

    # UI callbacks - subagents don't control parent UI
    add_notification: Callable[[dict], None] | None = None
    set_tool_jsx: Callable[[Any], None] | None = None

    # Attribution tracking (functionally composable, safe to share)
    update_attribution_state: Callable[[Callable[[dict], dict]], None] = field(
        default=lambda _: None
    )

    # Query tracking
    query_tracking: dict[str, Any] = field(
        default_factory=lambda: {"chain_id": uuid.uuid4().hex, "depth": 0}
    )


def create_subagent_context(
    parent_context: ToolUseContext,
    overrides: dict[str, Any] | None = None,
) -> ToolUseContext:
    """
    Create an isolated context for subagents.

    Default isolation + explicit opt-in sharing:
    - readFileState: cloned (subagent shouldn't pollute parent cache)
    - getAppState: wrapped to set shouldAvoidPermissionPrompts
    - setAppState: default no-op, opt-in to share
    - setAppStateForTasks: ALWAYS shared (task registration must reach root)
    - UI callbacks: None (subagent can't control parent UI)

    Inspired by claw-code's utils/forkedAgent.ts:345-462
    """
    overrides = overrides or {}

    # AbortController: new child controller linked to parent
    parent_abort = parent_context.abort_controller
    child_abort = overrides.get("abort_controller")
    if child_abort is None:
        # Create child that aborts when parent aborts
        child_abort = AbortController(_aborted=parent_abort.is_aborted)

    # getAppState: wrap to set shouldAvoidPermissionPrompts for non-interactive agents
    get_app_state = overrides.get("get_app_state")
    if get_app_state is None:
        if overrides.get("share_abort_controller"):
            # Interactive agent shares parent state
            get_app_state = parent_context.get_app_state
        else:
            # Non-interactive agent: wrap to avoid permission prompts
            def wrapped_get_app_state() -> dict[str, Any]:
                state = parent_context.get_app_state()
                if state.get("tool_permission_context", {}).get(
                    "should_avoid_permission_prompts"
                ):
                    return state
                return {
                    **state,
                    "tool_permission_context": {
                        **state.get("tool_permission_context", {}),
                        "should_avoid_permission_prompts": True,
                    },
                }

            get_app_state = wrapped_get_app_state

    # setAppState: default no-op, opt-in to share
    share_set_app_state = overrides.get("share_set_app_state", False)
    set_app_state = (
        parent_context.set_app_state if share_set_app_state else lambda _: None
    )

    # setAppStateForTasks: ALWAYS penetrates to root store
    # Task registration/kill must reach root to avoid zombie processes
    set_app_state_for_tasks = (
        parent_context.set_app_state_for_tasks or parent_context.set_app_state
    )

    return ToolUseContext(
        # Isolated state
        read_file_state=parent_context.read_file_state.copy(),
        nested_memory_triggers=set(),  # Fresh set
        abort_controller=child_abort,
        # AppState access
        get_app_state=get_app_state,
        set_app_state=set_app_state,
        set_app_state_for_tasks=set_app_state_for_tasks,
        # Agent info
        agent_id=overrides.get("agent_id", f"agent-{uuid.uuid4().hex[:8]}"),
        agent_type=overrides.get("agent_type"),
        # Messages
        messages=overrides.get("messages", parent_context.messages),
        # Options
        options=overrides.get("options", parent_context.options),
        # UI callbacks - None for subagents
        add_notification=None,
        set_tool_jsx=None,
        # Attribution - always shared (functionally composable)
        update_attribution_state=parent_context.update_attribution_state,
        # Query tracking - new chain, increment depth
        query_tracking={
            "chain_id": uuid.uuid4().hex,
            "depth": parent_context.query_tracking.get("depth", 0) + 1,
        },
    )
