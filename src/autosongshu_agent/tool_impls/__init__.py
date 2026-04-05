from __future__ import annotations

from typing import Any

from agentscope.tool import Toolkit

from ..runtime import PentestRuntime
from .registry import registry, _ToolExecutionPolicy, _wrap_registered_tool

from . import browser
from . import http
from . import skills
from . import findings
from . import knowledge
from . import sandbox


def register_default_tools(
    toolkit: Toolkit,
    runtime: PentestRuntime,
    permission_interceptor: Any | None = None,
) -> None:
    registry.register_all_to_toolkit(
        toolkit,
        runtime,
        permission_interceptor=permission_interceptor,
    )


__all__ = ["register_default_tools", "_ToolExecutionPolicy", "_wrap_registered_tool"]
