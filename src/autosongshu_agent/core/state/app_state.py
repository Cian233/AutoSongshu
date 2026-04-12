"""
AppState - Single source of truth for UI state.

Layer 2 of the three-layer architecture. Contains all UI-level state
that needs to be reactive (accessible from React components).

Inspired by claw-code's state/AppStateStore.ts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    from ..permissions import ToolPermissionContext
except ImportError:
    # Fallback for circular import
    from dataclasses import dataclass as _dataclass
    from typing import Any

    @dataclass
    class ToolPermissionContext:
        mode: str = "auto"
        deny_names: frozenset = frozenset()
        require_approval_names: frozenset = frozenset()


@dataclass
class AppState:
    """
    Single state tree for the entire application.

    All fields should be immutable (use DeepImmutable pattern in practice).
    Modifications only through store.set_state().
    """

    # User configuration
    settings: dict[str, Any] = field(default_factory=dict)
    verbose: bool = False
    main_loop_model: str | None = None

    # Permission system
    tool_permission_context: ToolPermissionContext = field(
        default_factory=ToolPermissionContext
    )

    # MCP (Model Context Protocol)
    mcp: dict[str, Any] = field(
        default_factory=lambda: {
            "clients": [],
            "tools": [],
            "commands": [],
            "resources": {},
        }
    )

    # Plugin system
    plugins: dict[str, Any] = field(
        default_factory=lambda: {
            "enabled": [],
            "disabled": [],
            "commands": [],
            "errors": [],
        }
    )

    # UI state
    thinking_enabled: bool | None = None
    expanded_view: str = "none"  # "none", "tasks", "teammates"
    footer_selection: Any | None = None

    # Tasks (excluded from DeepImmutable because TaskState contains functions)
    tasks: dict[str, Any] = field(default_factory=dict)

    # Agent registry
    agent_name_registry: dict[str, str] = field(default_factory=dict)

    # Session info
    session_id: str = ""

    # Engagement info
    engagement: dict[str, Any] = field(default_factory=dict)


def get_default_app_state() -> AppState:
    """
    Get default initial AppState.

    Some defaults are dynamically computed (e.g., thinking_enabled based on model).
    """
    return AppState(
        settings={},
        verbose=False,
        main_loop_model=None,
        tool_permission_context=ToolPermissionContext(),
        thinking_enabled=False,
        session_id="",
        engagement={},
    )
