"""State management modules - Three-layer architecture."""

from .store import Store, create_store
from .bootstrap import (
    SessionState,
    get_session_id,
    set_session_id,
    get_cwd,
    set_cwd,
    get_total_cost,
    add_to_total_cost,
    init_session,
    get_project_root,
    get_model_usage,
    reset_state,
)
from .context import (
    ToolUseContext,
    create_subagent_context,
    AbortController,
    FileStateCache,
)
from .app_state import AppState, get_default_app_state
from .on_change import on_change_app_state, create_on_change_handler
from .selectors import (
    get_active_agent_for_input,
    get_model_for_request,
    get_permission_mode,
    is_thinking_enabled,
    should_show_progress_bar,
)

__all__ = [
    # Store
    "Store",
    "create_store",
    # Session state
    "SessionState",
    "get_session_id",
    "set_session_id",
    "init_session",
    "get_cwd",
    "set_cwd",
    "get_project_root",
    "get_total_cost",
    "add_to_total_cost",
    "get_model_usage",
    "reset_state",
    # Context
    "ToolUseContext",
    "create_subagent_context",
    "AbortController",
    "FileStateCache",
    # AppState
    "AppState",
    "get_default_app_state",
    # OnChange
    "on_change_app_state",
    "create_on_change_handler",
    # Selectors
    "get_active_agent_for_input",
    "get_model_for_request",
    "get_permission_mode",
    "is_thinking_enabled",
    "should_show_progress_bar",
]
