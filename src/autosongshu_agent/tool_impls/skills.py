from __future__ import annotations

from typing import Any

from agentscope.tool import ToolResponse

from ..runtime import PentestRuntime
from .registry import registry
from .utils import _error_response, _parse_json_list, _tool_response

registry.create_group(
    "skill-scripts",
    description="List and run bundled scripts that live under available local skills.",
    active=True,
    notes="Use these tools instead of re-implementing deterministic skill helper logic from scratch.",
)

@registry.register("skill-scripts")
def list_skill_scripts(runtime: PentestRuntime, skill_name: str = "") -> ToolResponse:
    """List bundled scripts under available skills, including on-demand manual skills, or only for a specific skill when skill_name is provided."""
    try:
        return _tool_response(runtime.skill_scripts.list_scripts(skill_name=skill_name))
    except Exception as exc:
        return _error_response(exc)

@registry.register("skill-scripts", dedupe=False, invalidates_cache=True, requires_approval=True)
def run_skill_script(
    runtime: PentestRuntime,
    skill_name: str,
    script_name: str,
    args_json: str = "[]",
    timeout_sec: int = 300,
    max_output_chars: int = 20000,
) -> ToolResponse:
    """Run a bundled script from an available skill. script_name accepts either a filename or a relative path under scripts/."""
    try:
        return _tool_response(
            runtime.skill_scripts.run(
                skill_name=skill_name,
                script_name=script_name,
                args=_parse_json_list(args_json),
                timeout_sec=timeout_sec,
                max_output_chars=max_output_chars,
            ),
        )
    except Exception as exc:
        return _error_response(exc)
