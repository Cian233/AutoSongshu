"""Permission management modules."""

from .context import ToolPermissionContext, ToolRiskLevel
from .interceptor import PermissionInterceptor, build_default_permission_context
from .pipeline import (
    PermissionBehavior,
    PermissionMode,
    PermissionDecision,
    PermissionPipeline,
    PermissionRule,
    create_default_pipeline,
)
from .persistence import (
    PersistenceMode as StorePersistenceMode,
    PermissionStore,
    PermissionRuleSource,
    PermissionHistory,
    UserPermissionDecision,
    create_permission_store_with_persistence,
)
from .manager import (
    PermissionManager,
    UserDecision,
    create_permission_manager,
)

__all__ = [
    # Context
    "ToolPermissionContext",
    "ToolRiskLevel",
    # Interceptor
    "PermissionInterceptor",
    "build_default_permission_context",
    # Pipeline
    "PermissionBehavior",
    "PermissionMode",
    "PermissionDecision",
    "PermissionPipeline",
    "PermissionRule",
    "create_default_pipeline",
    # Persistence
    "StorePersistenceMode",
    "PermissionStore",
    "PermissionRuleSource",
    "PermissionHistory",
    "UserPermissionDecision",
    "create_permission_store_with_persistence",
    # Manager
    "PermissionManager",
    "UserDecision",
    "create_permission_manager",
]
