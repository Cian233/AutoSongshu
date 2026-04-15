"""File search tools — glob pattern matching and regex content search.

Ported from claw-code's glob_search and grep_search tools, adapted for the
security assessment context (searching within the sandbox workspace and
project artifacts).
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any

from agentscope.tool import ToolResponse

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _tool_response, _error_response


registry.create_group(
    "file-search",
    description="文件搜索工具：通过 glob 模式查找文件或用正则表达式搜索文件内容。",
)


@registry.register(
    "file-search",
    description="通过 glob 模式查找文件路径。支持 **、*、? 等通配符。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=True,
)
def glob_search(
    runtime: PentestRuntime,
    pattern: str,
    path: str = "",
) -> ToolResponse:
    """Search for files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g. "**/*.py", "*.json", "src/**/*.js").
        path: Root directory to search in. Defaults to sandbox workspace.
              Must be within the sandbox workspace directory.
    """
    try:
        workspace = runtime.sandbox.workspace_dir.resolve()
        if path:
            search_root = Path(path).resolve()
            if not str(search_root).startswith(str(workspace)):
                return _tool_response({"ok": False, "error": f"路径必须在 sandbox workspace 范围内: {workspace}"})
        else:
            search_root = workspace

        if not search_root.exists():
            return _tool_response({"ok": False, "error": f"路径不存在: {search_root}"})

        matches: list[str] = []
        # Use pathlib glob with recursive pattern support
        if "**" in pattern:
            matched = list(search_root.glob(pattern))
        else:
            matched = list(search_root.glob(pattern))

        # Sort by modification time (most recent first)
        matched.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)

        for p in matched[:200]:
            if p.is_file():
                try:
                    matches.append(str(p.relative_to(search_root)))
                except ValueError:
                    matches.append(str(p))

        return _tool_response({
            "ok": True,
            "pattern": pattern,
            "root": str(search_root),
            "total_matches": len(matches),
            "matches": matches[:200],
        })
    except Exception as exc:
        return _error_response(exc)


@registry.register(
    "file-search",
    description="用正则表达式搜索文件内容。支持文件类型过滤、上下文行、大小写不敏感等选项。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=True,
)
def grep_search(
    runtime: PentestRuntime,
    pattern: str,
    path: str = "",
    glob: str = "",
    output_mode: str = "files_with_matches",
    ignore_case: bool = False,
    show_line_numbers: bool = True,
    before_context: int = 0,
    after_context: int = 0,
    max_results: int = 100,
) -> ToolResponse:
    """Search file contents using a regular expression.

    Args:
        pattern: Regular expression to search for.
        path: Directory to search in. Defaults to sandbox workspace.
        glob: File filter pattern (e.g. "*.py", "*.json").
        output_mode: "files_with_matches", "content", or "count".
        ignore_case: Case-insensitive search.
        show_line_numbers: Include line numbers in content output.
        before_context: Number of lines before each match.
        after_context: Number of lines after each match.
        max_results: Maximum number of results to return.
    """
    try:
        workspace = runtime.sandbox.workspace_dir.resolve()
        if path:
            search_root = Path(path).resolve()
            if not str(search_root).startswith(str(workspace)):
                return _tool_response({"ok": False, "error": f"路径必须在 sandbox workspace 范围内: {workspace}"})
        else:
            search_root = workspace

        if not search_root.exists():
            return _tool_response({"ok": False, "error": f"路径不存在: {search_root}"})

        regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        glob_pattern = glob.strip() if glob else None

        results: list[dict[str, Any]] = []
        file_count = 0

        for root, dirs, files in os.walk(search_root):
            # Skip hidden directories and common exclusions
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
                "__pycache__", "node_modules", ".git", "venv", ".venv",
                "env", ".env", ".tox", ".mypy_cache", ".pytest_cache",
            )]

            for filename in sorted(files):
                if glob_pattern and not fnmatch.fnmatch(filename, glob_pattern):
                    continue

                filepath = Path(root) / filename
                if not filepath.is_file():
                    continue

                try:
                    content = filepath.read_text(encoding="utf-8", errors="replace")
                except (OSError, PermissionError):
                    continue

                lines = content.splitlines()
                matches_in_file: list[dict[str, Any]] = []

                for i, line in enumerate(lines):
                    if regex.search(line):
                        rel_path = str(filepath.relative_to(search_root))
                        match_info: dict[str, Any] = {"line": i + 1, "text": line.rstrip()}
                        if before_context > 0:
                            ctx_start = max(0, i - before_context)
                            match_info["before"] = lines[ctx_start:i]
                        if after_context > 0:
                            ctx_end = min(len(lines), i + 1 + after_context)
                            match_info["after"] = lines[i + 1:ctx_end]
                        matches_in_file.append(match_info)

                if matches_in_file:
                    file_count += 1
                    rel_path = str(filepath.relative_to(search_root))
                    if output_mode == "files_with_matches":
                        results.append({"path": rel_path, "match_count": len(matches_in_file)})
                    elif output_mode == "content":
                        for m in matches_in_file:
                            entry: dict[str, Any] = {"path": rel_path}
                            if show_line_numbers:
                                entry["line"] = m["line"]
                            entry["text"] = m["text"]
                            if "before" in m:
                                entry["before"] = m["before"]
                            if "after" in m:
                                entry["after"] = m["after"]
                            results.append(entry)
                    elif output_mode == "count":
                        results.append({"path": rel_path, "count": len(matches_in_file)})

                    if file_count >= max_results:
                        break

            if file_count >= max_results:
                break

        return _tool_response({
            "ok": True,
            "pattern": pattern,
            "root": str(search_root),
            "output_mode": output_mode,
            "total_files_with_matches": file_count,
            "results": results[:max_results],
        })
    except Exception as exc:
        return _error_response(exc)
