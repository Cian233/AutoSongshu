from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GitStatus:
    branch: str = ""
    is_clean: bool = True
    staged_files: tuple[str, ...] = ()
    unstaged_files: tuple[str, ...] = ()
    untracked_files: tuple[str, ...] = ()
    ahead: int = 0
    behind: int = 0
    has_git: bool = False

    def as_summary(self, max_files: int = 10) -> str:
        if not self.has_git:
            return "No Git repository detected."
        lines = [f"Branch: {self.branch or 'unknown'}"]
        if not self.is_clean:
            parts = []
            if self.staged_files:
                parts.append(f"{len(self.staged_files)} staged")
            if self.unstaged_files:
                parts.append(f"{len(self.unstaged_files)} modified")
            if self.untracked_files:
                parts.append(f"{len(self.untracked_files)} untracked")
            lines.append(f"Status: dirty ({', '.join(parts)})")
            all_changed = (
                list(self.staged_files[:max_files])
                + list(self.unstaged_files[:max_files])
                + list(self.untracked_files[:max_files])
            )
            for f in all_changed[:max_files]:
                lines.append(f"  - {f}")
            if len(all_changed) > max_files:
                lines.append(f"  ... and {len(all_changed) - max_files} more")
        else:
            lines.append("Status: clean (working directory)")
        if self.ahead > 0 or self.behind > 0:
            sync_parts = []
            if self.ahead > 0:
                sync_parts.append(f"{self.ahead} ahead")
            if self.behind > 0:
                sync_parts.append(f"{self.behind} behind")
            lines.append(f"Sync: {', '.join(sync_parts)}")
        return "\n".join(lines)


@dataclass(frozen=True)
class ProjectContext:
    root: Path
    name: str
    python_files: int = 0
    has_tests: bool = False
    has_configs: bool = False
    has_docs: bool = False
    git_status: GitStatus = field(default_factory=GitStatus)
    environment_vars: dict[str, str] = field(default_factory=dict)

    def as_summary(self) -> str:
        lines = [
            f"Project: {self.name}",
            f"Root: {self.root}",
            f"Python files: {self.python_files}",
        ]
        if self.has_tests:
            lines.append("Has tests: yes")
        if self.has_configs:
            lines.append("Has configs: yes")
        if self.has_docs:
            lines.append("Has docs: yes")
        lines.append("")
        lines.append("Git status:")
        lines.append(self.git_status.as_summary())
        return "\n".join(lines)


def detect_git_root(start_path: Path | None = None) -> Path | None:
    current = (start_path or Path.cwd()).resolve()
    for parent in [current] + list(current.parents):
        if (parent / ".git").exists():
            return parent
    return None


def get_git_status(repo_path: Path | None = None) -> GitStatus:
    root = detect_git_root(repo_path)
    if root is None:
        return GitStatus(has_git=False)

    def run_git(*args: str, cwd: Path) -> str:
        try:
            result = subprocess.run(
                ["git"] + list(args),
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    branch = run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=root) or "unknown"
    status_output = run_git("status", "--porcelain", cwd=root)
    sync_output = run_git(
        "rev-list", "--left-right", "--count", "@{upstream}...HEAD", cwd=root
    )

    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []

    for line in status_output.splitlines():
        if not line:
            continue
        index_status = line[0] if len(line) > 0 else " "
        work_tree_status = line[1] if len(line) > 1 else " "
        file_path = line[3:] if len(line) > 3 else ""

        if index_status in ("M", "A", "D", "R", "C"):
            staged.append(file_path)
        if work_tree_status in ("M", "D"):
            unstaged.append(file_path)
        if index_status == "?" and work_tree_status == "?":
            untracked.append(file_path)

    ahead, behind = 0, 0
    if sync_output:
        parts = sync_output.split()
        if len(parts) >= 2:
            try:
                behind = int(parts[0])
                ahead = int(parts[1])
            except ValueError:
                pass

    return GitStatus(
        branch=branch,
        is_clean=not (staged or unstaged or untracked),
        staged_files=tuple(staged),
        unstaged_files=tuple(unstaged),
        untracked_files=tuple(untracked),
        ahead=ahead,
        behind=behind,
        has_git=True,
    )


def scan_project_structure(root: Path) -> dict[str, Any]:
    python_files = sum(1 for p in root.rglob("*.py") if p.is_file())
    has_tests = any(
        [
            (root / "tests").exists(),
            (root / "test").exists(),
        ]
    )
    has_configs = any(
        [
            (root / "configs").exists(),
            (root / "config").exists(),
            (root / "pyproject.toml").exists(),
            (root / "setup.py").exists(),
        ]
    )
    has_docs = any(
        [
            (root / "docs").exists(),
            (root / "README.md").exists(),
        ]
    )
    return {
        "python_files": python_files,
        "has_tests": has_tests,
        "has_configs": has_configs,
        "has_docs": has_docs,
    }


def build_project_context(root: Path | None = None) -> ProjectContext:
    project_root = (root or Path.cwd()).resolve()
    structure = scan_project_structure(project_root)
    git_status = get_git_status(project_root)
    env_vars: dict[str, str] = {}
    for key in ("PYTHON_VERSION", "NODE_VERSION", "PATH"):
        value = os.environ.get(key)
        if value:
            env_vars[key] = value.split(os.pathsep)[0] if key == "PATH" else value

    return ProjectContext(
        root=project_root,
        name=project_root.name,
        python_files=structure["python_files"],
        has_tests=structure["has_tests"],
        has_configs=structure["has_configs"],
        has_docs=structure["has_docs"],
        git_status=git_status,
        environment_vars=env_vars,
    )


def render_environment_context(
    ctx: ProjectContext | None = None, root: Path | None = None
) -> str:
    context = ctx or build_project_context(root)
    lines = [
        "# Environment Context",
        "",
        context.as_summary(),
    ]
    return "\n".join(lines)


def inject_git_status_to_prompt(
    base_prompt: str, ctx: ProjectContext | None = None, root: Path | None = None
) -> str:
    context = ctx or build_project_context(root)
    if not context.git_status.has_git:
        return base_prompt
    git_section = f"""
<environment_snapshot>
{context.git_status.as_summary()}
</environment_snapshot>
"""
    insertion_marker = "Authorization context:"
    if insertion_marker in base_prompt:
        return base_prompt.replace(
            insertion_marker, git_section.strip() + "\n\n" + insertion_marker
        )
    return base_prompt + "\n\n" + git_section.strip()


__all__ = [
    "GitStatus",
    "ProjectContext",
    "detect_git_root",
    "get_git_status",
    "scan_project_structure",
    "build_project_context",
    "render_environment_context",
    "inject_git_status_to_prompt",
]
