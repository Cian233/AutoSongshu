from __future__ import annotations

from typing import Any

from agentscope.tool import ToolResponse

from ..runtime import PentestRuntime
from .registry import registry
from .utils import (
    _error_response,
    _parse_json_list,
    _parse_json_object,
    _parse_json_object_list,
    _parse_package_specs,
    _tool_response,
)

registry.create_group(
    "python-sandbox",
    description="Shared per-user Python sandbox for custom test scripts, package installs, and helper automation.",
    active=lambda runtime: runtime.config.sandbox.enabled,
    notes="Prefer this for bulk payload fuzzing, retry loops, custom sessions/cookies/headers, encoding tricks, certificate quirks, and any validation the built-in browser/CDP/HTTP tools cannot finish directly.",
)

@registry.register("python-sandbox")
def sandbox_status(runtime: PentestRuntime) -> ToolResponse:
    """Call this first before using the sandbox. It returns paths, scope metadata, HTTPS/certificate hints, and package mirror settings."""
    try:
        return _tool_response(runtime.sandbox.status(include_packages=False))
    except Exception as exc:
        return _error_response(exc)

@registry.register("python-sandbox")
def sandbox_list_files(runtime: PentestRuntime, pattern: str = "**/*", limit: int = 200) -> ToolResponse:
    """List files in the shared per-user sandbox workspace."""
    try:
        return _tool_response(runtime.sandbox.list_files(pattern=pattern, limit=limit))
    except Exception as exc:
        return _error_response(exc)

@registry.register("python-sandbox", dedupe=False, invalidates_cache=True, requires_approval=True)
def sandbox_write_file(runtime: PentestRuntime, path: str, content: str) -> ToolResponse:
    """Create or intentionally overwrite a UTF-8 text file inside the sandbox workspace. content must be raw file text only: no markdown fences, no narrative explanations, and no thought-process notes. Prefer edit_file or multiedit_file for iterative changes."""
    try:
        return _tool_response(runtime.sandbox.write_file(path=path, content=content))
    except Exception as exc:
        return _error_response(exc)

@registry.register("python-sandbox", dedupe=False, invalidates_cache=True, requires_approval=True)
def sandbox_edit_file(
    runtime: PentestRuntime,
    path: str,
    old_text: str = "",
    new_text: str = "",
    replace_all: bool = False,
    start_line: int = 0,
    end_line: int = 0,
    expected_old_text: str = "",
    max_diff_chars: int = 12000,
) -> ToolResponse:
    """Apply one precise edit to an existing UTF-8 text file. new_text must be raw replacement text only, without markdown fences or explanatory prose. Use exact old_text/new_text replacement or a start_line/end_line replacement with optional expected_old_text verification. This refuses whole-file replacement; use write_file only for intentional full overwrites."""
    try:
        return _tool_response(
            runtime.sandbox.edit_file(
                path=path,
                old_text=old_text,
                new_text=new_text,
                replace_all=replace_all,
                start_line=start_line,
                end_line=end_line,
                expected_old_text=expected_old_text,
                max_diff_chars=max_diff_chars,
            )
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("python-sandbox", dedupe=False, invalidates_cache=True, requires_approval=True)
def sandbox_multiedit_file(
    runtime: PentestRuntime,
    path: str,
    edits_json: str,
    max_diff_chars: int = 12000,
) -> ToolResponse:
    """Apply several precise edits to the same file in order. edits_json must be a JSON list of edit objects, each using old_text/new_text or start_line/end_line/new_text. Every new_text value must be raw replacement text only, without markdown fences or explanatory prose."""
    try:
        return _tool_response(
            runtime.sandbox.multiedit_file(
                path=path,
                edits=_parse_json_object_list(edits_json),
                max_diff_chars=max_diff_chars,
            )
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("python-sandbox")
def sandbox_read_file(
    runtime: PentestRuntime,
    path: str,
    max_chars: int = 12000,
    start_line: int = 0,
    end_line: int = 0,
    include_line_numbers: bool = False,
) -> ToolResponse:
    """Read a UTF-8 text file from the sandbox workspace. Use include_line_numbers=true and an optional line range before line-based edits."""
    try:
        return _tool_response(
            runtime.sandbox.read_file(
                path=path,
                max_chars=max_chars,
                start_line=start_line,
                end_line=end_line,
                include_line_numbers=include_line_numbers,
            )
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("python-sandbox", dedupe=False, invalidates_cache=True, requires_approval=True)
def sandbox_install_packages(
    runtime: PentestRuntime,
    packages: str,
    upgrade: bool = False,
    timeout_sec: int = 300,
    max_output_chars: int = 20000,
) -> ToolResponse:
    """Install newline-separated, comma-separated, space-separated, or JSON-list Python packages into the sandbox venv."""
    try:
        return _tool_response(
            runtime.sandbox.install_packages(
                packages=_parse_package_specs(packages),
                upgrade=upgrade,
                timeout_sec=timeout_sec,
                max_output_chars=max_output_chars,
            ),
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("python-sandbox", invalidates_cache=True, requires_approval=True)
def sandbox_run_python(
    runtime: PentestRuntime,
    code: str = "",
    script_path: str = "",
    args_json: str = "[]",
    env_json: str = "{}",
    timeout_sec: int = 120,
    max_output_chars: int = 20000,
) -> ToolResponse:
    """Run inline Python code or an existing sandbox script. If code is provided, it must be raw Python only, without markdown fences or narrative preambles. Prefer script_path for iterative payload work so the file can be updated with sandbox_edit_file or sandbox_multiedit_file between runs. Avoid rerunning identical code unless inputs or logic changed."""
    try:
        return _tool_response(
            runtime.sandbox.run_python(
                code=code,
                script_path=script_path,
                args=_parse_json_list(args_json),
                env={key: str(value) for key, value in _parse_json_object(env_json).items()},
                timeout_sec=timeout_sec,
                max_output_chars=max_output_chars,
            ),
        )
    except Exception as exc:
        return _error_response(exc)
