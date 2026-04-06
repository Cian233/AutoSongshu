"""
Tools system - buildTool pattern and registry.

This is the NEW tools system (Phase 2).
The OLD tools.py is kept for backward compatibility during migration.
"""

from .base import Tool, build_tool, ToolDef, PermissionResult
from .registry import ToolRegistry, get_all_base_tools, get_tools, assemble_tool_pool
from .execution import partition_tool_calls, run_tools_concurrently, run_tools_serially
from .result import ToolExecutionResult, ToolBatchResult

# Backward compatibility - import from old location during migration
from ..tool_impls import (
    register_default_tools,
    _ToolExecutionPolicy,
    _wrap_registered_tool,
)

__all__ = [
    # Base
    "Tool",
    "build_tool",
    "ToolDef",
    "PermissionResult",
    # Registry
    "ToolRegistry",
    "get_all_base_tools",
    "get_tools",
    "assemble_tool_pool",
    # Execution
    "partition_tool_calls",
    "run_tools_concurrently",
    "run_tools_serially",
    # Result
    "ToolExecutionResult",
    "ToolBatchResult",
    # Backward compatibility
    "register_default_tools",
    "_ToolExecutionPolicy",
    "_wrap_registered_tool",
]
