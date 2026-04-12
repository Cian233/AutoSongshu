from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any

from agentscope.tool import Toolkit

from ..runtime import PentestRuntime
from .registry import registry, _ToolExecutionPolicy, _wrap_registered_tool

# ── Auto-discover and import all tool modules ─────────────────────
# Any new .py file added to this directory will be automatically
# imported at package load time, triggering its @registry.register()
# decorators.  No manual `from . import xxx` lines needed.
#
# Files that are NOT tool modules (e.g. registry.py, utils.py,
# __init__.py, __pycache__) are excluded by name.

_THIS_DIR = Path(__file__).resolve().parent
_EXCLUDED_MODULES = {
    "__init__",
    "registry",
    "utils",
}

for _module_info in pkgutil.iter_modules([str(_THIS_DIR)]):
    if _module_info.name not in _EXCLUDED_MODULES:
        importlib.import_module(f".{_module_info.name}", __package__)


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
