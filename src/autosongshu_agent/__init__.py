"""
AUTOsongshu Agent - Authorized web pentest agent.

New architecture (Phase 1-4 refactoring):
- core/: Three-layer state management
- tools/: buildTool pattern + registry
- prompts/: Section-based caching
- agent/: Agent definitions + Fork support
"""

# Core infrastructure (NEW)
from .core import (
    Store,
    create_store,
    ToolUseContext,
    create_subagent_context,
    AppState,
    get_default_app_state,
    ToolPermissionContext,
    ToolRiskLevel,
)

# Tools system (NEW - except result types which use existing)
from .tools import (
    Tool,
    build_tool,
    ToolDef,
    PermissionResult,
    ToolRegistry,
)

# Agent system (NEW)
from .agent.definition import (
    BuiltInAgentDefinition,
    CustomAgentDefinition,
    AgentDefinition,
    get_agent_model,
)

from .agent.built_in import (
    EXPLORE_AGENT,
    PLAN_AGENT,
    VERIFICATION_AGENT,
    get_builtin_agents,
)

# Prompts (NEW)
from .prompts import (
    system_prompt_section,
    DANGEROUS_uncached_section,
    resolve_sections,
    clear_section_cache,
)

# Existing exports (backward compatibility)
from .agent import PentestCoordinator
from .config import AppConfig, load_config

# Legacy exports (existing implementations with full functionality)
from .tool_result import ToolExecutionResult, ToolBatchResult
from .turn_result import StopReason, TurnResult, AgentExecutionResult
from .budget import BudgetConfig, BudgetCheckResult, BudgetTracker

# build_system_prompt is imported directly in modules that need it
# to avoid circular import with prompts/ package

__all__ = [
    # NEW: Core infrastructure
    "Store",
    "create_store",
    "ToolUseContext",
    "create_subagent_context",
    "AppState",
    "get_default_app_state",
    "ToolPermissionContext",
    "ToolRiskLevel",
    # NEW: Tools system
    "Tool",
    "build_tool",
    "ToolDef",
    "PermissionResult",
    "ToolRegistry",
    # NEW: Agent system
    "BuiltInAgentDefinition",
    "CustomAgentDefinition",
    "AgentDefinition",
    "get_agent_model",
    "EXPLORE_AGENT",
    "PLAN_AGENT",
    "VERIFICATION_AGENT",
    "get_builtin_agents",
    # NEW: Prompts
    "system_prompt_section",
    "DANGEROUS_uncached_section",
    "resolve_sections",
    "clear_section_cache",
    # Existing
    "AppConfig",
    "PentestCoordinator",
    "load_config",
    "ToolExecutionResult",
    "ToolBatchResult",
    "StopReason",
    "TurnResult",
    "AgentExecutionResult",
    "BudgetConfig",
    "BudgetCheckResult",
    "BudgetTracker",
]
