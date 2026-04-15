from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return normalized or "session"


class ArtifactStore:
    """Manages artifact storage with project-level and session-level directories.

    Codex/OpenCode-style architecture:
    - project_dir: Project-level root (shared across all sessions)
    - workspace_dir: Project-level shared workspace (files, scripts, outputs)
    - sessions_dir: Contains per-session artifacts (memory, trajectories)
    - session_dir: Current session's artifact directory
    """

    def __init__(
        self,
        root_dir: str,
        engagement_name: str,
        session_name: str | None = None,
        project_dir: str | None = None,
    ) -> None:
        if session_name is None:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            session_name = f"{timestamp}-{_slugify(engagement_name)}"
        else:
            normalized = session_name.strip()
            if (
                not normalized
                or normalized in {".", ".."}
                or "/" in normalized
                or "\\" in normalized
            ):
                raise ValueError(f"Invalid artifact session name: {session_name!r}")
            session_name = normalized

        self.root_dir = Path(root_dir).resolve()

        # Project-level directory / workspace root.
        if project_dir:
            self.project_dir = Path(project_dir).resolve()
            # When project_dir is provided, treat it as the explicit workspace root.
            self.workspace_dir = self.project_dir
        else:
            # Fallback: use root_dir as project dir (legacy behavior)
            self.project_dir = self.root_dir
            # Legacy behavior: workspace is stored under root_dir/workspace.
            self.workspace_dir = self.project_dir / "workspace"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        # Session-level artifacts (memory, trajectories, etc.)
        self.sessions_dir = self.root_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.session_dir = self.sessions_dir / session_name
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # Legacy compatibility: session_dir alias
        self._session_name = session_name

    @property
    def session_name(self) -> str:
        return self._session_name

    def path(self, relative_path: str) -> Path:
        """Resolve a path within the session's artifact directory."""
        target = self.session_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def workspace_path(self, relative_path: str) -> Path:
        """Resolve a path within the project's shared workspace.

        This is the Codex-style path where all sessions can read/write files.
        """
        target = self.workspace_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def write_text(self, relative_path: str, content: str) -> Path:
        target = self.path(relative_path)
        target.write_text(content, encoding="utf-8")
        return target

    def write_json(self, relative_path: str, content: Any) -> Path:
        target = self.path(relative_path)
        target.write_text(
            json.dumps(content, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return target

    def append_jsonl(self, relative_path: str, record: Any) -> Path:
        target = self.path(relative_path)
        with target.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, default=str))
            file.write("\n")
        return target


__all__ = ["ArtifactStore"]
