"""
UI package - User interface components.

Provides reusable UI components for CLI and Web interfaces.
"""

from .hooks import (
    StateSubscription,
    use_app_state,
    use_selector,
    StateBridge,
    get_global_bridge,
    init_global_bridge,
)
from .model_selector import (
    ModelOption,
    format_model_display_name,
    get_model_options,
    ModelSelectorUI,
    ChannelSelectorUI,
)
from .permissions import (
    PermissionRequest,
    PermissionDecision,
    PermissionPromptUI,
    PermissionRulesUI,
    SessionStatusUI,
)

__all__ = [
    # Hooks
    "StateSubscription",
    "use_app_state",
    "use_selector",
    "StateBridge",
    "get_global_bridge",
    "init_global_bridge",
    # Model selector
    "ModelOption",
    "format_model_display_name",
    "get_model_options",
    "ModelSelectorUI",
    "ChannelSelectorUI",
    # Permissions
    "PermissionRequest",
    "PermissionDecision",
    "PermissionPromptUI",
    "PermissionRulesUI",
    "SessionStatusUI",
]
