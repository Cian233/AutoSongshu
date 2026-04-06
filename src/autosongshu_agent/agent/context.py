"""Agent context builder with computed properties.

Inspired by claw-code's PortContext pattern - immutable context
with computed properties, built once at session start.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import AppConfig
from ..permissions import ToolPermissionContext


@dataclass(frozen=True)
class AgentContext:
    """Immutable agent execution context.

    Similar to claw-code's PortContext - contains all computed
    properties for the current session.
    """

    # Paths
    project_root: Path
    source_root: Path
    artifacts_root: Path
    session_dir: Path | None = None

    # Project stats (computed at build time)
    python_file_count: int = 0
    test_file_count: int = 0
    config_file_count: int = 0

    # Git context
    git_branch: str = ""
    git_commit: str = ""
    git_status: str = ""
    has_uncommitted_changes: bool = False

    # Session info
    session_id: str = ""
    mode: str = "auto"
    max_iters: int = 50

    # Budget
    budget_config: dict[str, Any] = field(default_factory=dict)

    # Permissions
    permission_context: ToolPermissionContext = field(
        default_factory=lambda: ToolPermissionContext()
    )

    # Computed string representations
    context_summary: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        # Compute summary if not provided
        if not self.context_summary:
            summary = self._build_summary()
            # Note: Can't modify frozen dataclass, but __post_init__ runs before freeze
            object.__setattr__(self, "context_summary", summary)

    def _build_summary(self) -> str:
        """Build human-readable context summary."""
        lines = [
            f"Project: {self.project_root.name}",
            f"Files: {self.python_file_count} Python, {self.test_file_count} tests",
        ]
        if self.git_branch:
            lines.append(f"Git: {self.git_branch} ({self.git_commit[:8]})")
        if self.has_uncommitted_changes:
            lines.append("⚠ Uncommitted changes")
        return "\n".join(lines)

    @property
    def is_git_repo(self) -> bool:
        """Whether this is a git repository."""
        return bool(self.git_branch)

    @property
    def file_count(self) -> int:
        """Total file count."""
        return self.python_file_count + self.test_file_count + self.config_file_count

    def to_dict(self) -> dict[str, Any]:
        """Serialize context to dict."""
        return {
            "project_root": str(self.project_root),
            "source_root": str(self.source_root),
            "artifacts_root": str(self.artifacts_root),
            "session_dir": str(self.session_dir) if self.session_dir else None,
            "python_file_count": self.python_file_count,
            "test_file_count": self.test_file_count,
            "config_file_count": self.config_file_count,
            "git_branch": self.git_branch,
            "git_commit": self.git_commit,
            "has_uncommitted_changes": self.has_uncommitted_changes,
            "session_id": self.session_id,
            "mode": self.mode,
            "max_iters": self.max_iters,
            "file_count": self.file_count,
            "is_git_repo": self.is_git_repo,
        }

    def render_for_model(self) -> str:
        """Render context for LLM consumption."""
        return self.context_summary


def _get_git_info(path: Path) -> tuple[str, str, str, bool]:
    """Get git info for a path."""
    try:
        # Check if git repo
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return ("", "", "", False)

        # Get branch
        branch_result = subprocess.run(
            ["git", "-C", str(path), "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""

        # Get commit
        commit_result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        commit = commit_result.stdout.strip() if commit_result.returncode == 0 else ""

        # Get status
        status_result = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        has_changes = (
            bool(status_result.stdout.strip())
            if status_result.returncode == 0
            else False
        )
        status = status_result.stdout.strip() if status_result.returncode == 0 else ""

        return (branch, commit, status, has_changes)
    except Exception:
        return ("", "", "", False)


def _count_files(root: Path, pattern: str) -> int:
    """Count files matching pattern."""
    try:
        return sum(1 for _ in root.rglob(pattern) if _.is_file())
    except Exception:
        return 0


def build_agent_context(
    config: AppConfig,
    session_id: str = "",
    base_path: Path | None = None,
    permission_context: ToolPermissionContext | None = None,
) -> AgentContext:
    """Build agent context with computed properties.

    Similar to claw-code's build_port_context - computes all
    properties at build time for immutability.
    """
    # Resolve paths
    root = base_path or Path.cwd()
    source_root = (
        config.artifacts.root_dir if hasattr(config, "artifacts") else root / "src"
    )
    artifacts_root = Path(source_root) if isinstance(source_root, str) else source_root

    # Compute file counts
    python_files = _count_files(root, "*.py")
    test_files = _count_files(root, "test_*.py") + _count_files(root, "*_test.py")
    config_files = _count_files(root, "*.yaml") + _count_files(root, "*.json")

    # Get git info
    branch, commit, status, has_changes = _get_git_info(root)

    # Get budget config
    budget_config = {}
    if hasattr(config, "compaction"):
        budget_config = {
            "max_tokens": getattr(config.compaction, "context_window_tokens", 128000),
            "reserved_tokens": getattr(config.compaction, "reserved_tokens", 8000),
        }

    # Get max iters
    max_iters = getattr(getattr(config, "agent", None), "max_iters", 50)
    mode = getattr(getattr(config, "agent", None), "mode", "auto")

    return AgentContext(
        project_root=root,
        source_root=Path(source_root) if isinstance(source_root, str) else source_root,
        artifacts_root=artifacts_root,
        session_dir=artifacts_root / "sessions" / session_id if session_id else None,
        python_file_count=python_files,
        test_file_count=test_files,
        config_file_count=config_files,
        git_branch=branch,
        git_commit=commit,
        git_status=status,
        has_uncommitted_changes=has_changes,
        session_id=session_id,
        mode=mode,
        max_iters=max_iters,
        budget_config=budget_config,
        permission_context=permission_context or ToolPermissionContext(),
    )


__all__ = [
    "AgentContext",
    "build_agent_context",
]
