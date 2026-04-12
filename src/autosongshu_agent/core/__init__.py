"""
Core infrastructure modules - Three-layer architecture.

This is the foundation of the application, consisting of:
- state/: Three-layer state management (Session → AppState → Context)
- config/: Configuration management
- permissions/: Permission and security system
"""

from .state import (
    # Store
    Store,
    create_store,
    # Session state
    SessionState,
    get_session_id,
    set_session_id,
    init_session,
    get_cwd,
    set_cwd,
    get_project_root,
    get_total_cost,
    add_to_total_cost,
    get_model_usage,
    reset_state,
    # Context
    ToolUseContext,
    create_subagent_context,
    AbortController,
    FileStateCache,
    # AppState
    AppState,
    get_default_app_state,
    # OnChange
    on_change_app_state,
    create_on_change_handler,
    # Selectors
    get_active_agent_for_input,
    get_model_for_request,
    get_permission_mode,
    is_thinking_enabled,
    should_show_progress_bar,
)

from .permissions import (
    ToolPermissionContext,
    ToolRiskLevel,
    PermissionInterceptor,
    build_default_permission_context,
)

from .config import (
    AppConfig,
    EngagementConfig,
    AgentConfig,
    ModelConfig,
    load_config,
    ScopePolicy,
    ScopeViolationError,
)

__all__ = [
    # State - Store
    "Store",
    "create_store",
    # State - Session
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
    # State - Context
    "ToolUseContext",
    "create_subagent_context",
    "AbortController",
    "FileStateCache",
    # State - AppState
    "AppState",
    "get_default_app_state",
    # State - OnChange
    "on_change_app_state",
    "create_on_change_handler",
    # State - Selectors
    "get_active_agent_for_input",
    "get_model_for_request",
    "get_permission_mode",
    "is_thinking_enabled",
    "should_show_progress_bar",
    # Permissions
    "ToolPermissionContext",
    "ToolRiskLevel",
    "PermissionInterceptor",
    "build_default_permission_context",
    # Config
    "AppConfig",
    "EngagementConfig",
    "AgentConfig",
    "ModelConfig",
    "load_config",
    "ScopePolicy",
    "ScopeViolationError",
]
