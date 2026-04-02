from __future__ import annotations

from agentscope.tool import Toolkit

from ..runtime import PentestRuntime
from .registry import registry, _ToolExecutionPolicy, _wrap_registered_tool

# Import all tool modules so they register themselves
from . import browser
from . import http
from . import skills
from . import findings
from . import knowledge
from . import sandbox

def register_default_tools(toolkit: Toolkit, runtime: PentestRuntime) -> None:
    """Register all default tools to the given toolkit."""
    registry.register_all_to_toolkit(toolkit, runtime)

__all__ = ["register_default_tools", "_ToolExecutionPolicy", "_wrap_registered_tool"]
