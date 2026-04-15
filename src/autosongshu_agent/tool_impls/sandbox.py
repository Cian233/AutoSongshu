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
def sandbox_list_files(runtime: PentestRuntime, pattern: str = "**/*", limit: int = 200, path: str = "") -> ToolResponse:
    """List files in the sandbox workspace or a specific directory.

    By default this lists files in the current session's sandbox workspace.
    In project mode, this workspace is isolated per project.
    Use `path` to list a specific subdirectory (relative to the sandbox workspace).
    """
    try:
        return _tool_response(runtime.sandbox.list_files(pattern=pattern, limit=limit, path=path))
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
    max_chars: int = 0,
    start_line: int = 0,
    end_line: int = 0,
    include_line_numbers: bool = False,
    offset: int = 0,
    limit: int = 0,
) -> ToolResponse:
    """Read a UTF-8 text file from the sandbox workspace.

    OpenCode-style large file handling:
    - Default: reads up to 2000 lines (128K chars) at a time
    - For files exceeding the limit: auto-truncates with a hint like
      "--- 3500 more lines in file. Use offset=2001 to continue reading. ---"
    - Use offset/limit for line-based pagination (OpenCode style)
    - Use start_line/end_line for explicit line ranges
    - Out-of-range offset recovers gracefully (returns tail of file)
    - Use include_line_numbers=true before line-based edits

    Examples:
    - Read first 2000 lines: sandbox_read_file(path="large.py")
    - Read lines 2001-4000: sandbox_read_file(path="large.py", offset=2001)
    - Read 500 lines from offset 1000: sandbox_read_file(path="large.py", offset=1000, limit=500)
    - Read specific range: sandbox_read_file(path="config.yaml", start_line=10, end_line=50)
    """
    try:
        return _tool_response(
            runtime.sandbox.read_file(
                path=path,
                max_chars=max_chars,
                start_line=start_line,
                end_line=end_line,
                include_line_numbers=include_line_numbers,
                offset=offset,
                limit=limit,
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
    timeout_sec: int = 0,
    max_output_chars: int = 20000,
) -> ToolResponse:
    """Run inline Python code or an existing sandbox script.

    OpenCode-aligned timeout strategy:
    - timeout_sec=0 uses config default timeout (120s by default)
    - Max timeout: 600s (10 min, enforced by sandbox)
    - Heartbeat detection: checks every 30s for long-running tasks
    - Output auto-truncated at 50KB / 2000 lines (opencode limits)

    If code is provided, it must be raw Python only, without markdown fences or narrative preambles.
    Prefer script_path for iterative payload work so the file can be updated with sandbox_edit_file
    or sandbox_multiedit_file between runs. Avoid rerunning identical code unless inputs or logic changed.
    """
    try:
        effective_timeout = timeout_sec if timeout_sec > 0 else runtime.config.sandbox.execution_timeout_sec
        return _tool_response(
            runtime.sandbox.run_python(
                code=code,
                script_path=script_path,
                args=_parse_json_list(args_json),
                env={key: str(value) for key, value in _parse_json_object(env_json).items()},
                timeout_sec=effective_timeout,
                max_output_chars=max_output_chars,
            ),
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("python-sandbox", invalidates_cache=True, requires_approval=True)
def sandbox_bash(
    runtime: PentestRuntime,
    command: str,
    timeout_sec: int = 0,
    max_output_chars: int = 20000,
) -> ToolResponse:
    """Execute a shell command in the workspace directory.

    OpenCode-style bash tool:
    - Runs in the workspace directory with sandbox environment
    - Default timeout: 120s (configurable via timeout_sec)
    - Max timeout: 600s (enforced by sandbox)
    - Output auto-truncated at max_output_chars (default 20K)
    - On Windows, uses cmd.exe; on Linux/macOS, uses bash

    Examples:
    - sandbox_bash(command="ls -la")
    - sandbox_bash(command="find . -name '*.py' -type f")
    - sandbox_bash(command="grep -r 'TODO' .", timeout_sec=30)
    """
    try:
        return _tool_response(
            runtime.sandbox.run_bash(
                command=command,
                timeout_sec=timeout_sec,
                max_output_chars=max_output_chars,
            ),
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("python-sandbox")
def sandbox_grep(
    runtime: PentestRuntime,
    pattern: str,
    path: str = ".",
    glob_pattern: str = "",
    case_sensitive: bool = False,
    max_results: int = 100,
) -> ToolResponse:
    """Search file contents using regex patterns.

    OpenCode-style grep tool:
    - Uses Python's re module for cross-platform regex support
    - Supports glob pattern filtering (e.g., "*.py", "**/*.js")
    - Returns matching lines with file paths and line numbers
    - Results limited to max_results (default 100)

    Examples:
    - sandbox_grep(pattern="TODO|FIXME")
    - sandbox_grep(pattern="def\\s+\\w+", glob_pattern="*.py")
    - sandbox_grep(pattern="password", path="src", case_sensitive=True)
    """
    try:
        return _tool_response(
            runtime.sandbox.grep(
                pattern=pattern,
                path=path,
                glob_pattern=glob_pattern,
                case_sensitive=case_sensitive,
                max_results=max_results,
            ),
        )
    except Exception as exc:
        return _error_response(exc)

@registry.register("python-sandbox")
def sandbox_glob(
    runtime: PentestRuntime,
    pattern: str,
    path: str = ".",
) -> ToolResponse:
    """Find files using glob patterns.

    OpenCode-style glob tool:
    - Supports ** for recursive matching
    - Returns files sorted by modification time (newest first)
    - Includes file metadata (size, type, modified_at)

    Examples:
    - sandbox_glob(pattern="**/*.py")
    - sandbox_glob(pattern="src/**/*.ts", path=".")
    - sandbox_glob(pattern="**/test_*.py")
    """
    try:
        return _tool_response(
            runtime.sandbox.glob_files(
                pattern=pattern,
                path=path,
            ),
        )
    except Exception as exc:
        return _error_response(exc)
