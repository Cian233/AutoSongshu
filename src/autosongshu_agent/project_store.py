from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .utils import now_iso

logger = logging.getLogger(__name__)


class ProjectRecord(BaseModel):
    id: str
    name: str
    workspace_dir: str
    artifacts_dir: str
    isolation_mode: str = "project"
    created_at: str
    updated_at: str
    session_count: int = 0


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    workspace_dir: str = ""


class ProjectStore:
    """Simple file-based project persistence store."""

    def __init__(self, data_dir: Path | None = None) -> None:
        if data_dir is None:
            data_dir = Path(__file__).resolve().parents[2] / "data"
        self._data_dir = data_dir
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._projects_file = self._data_dir / "projects.json"
        self._lock = threading.Lock()
        self._projects: dict[str, ProjectRecord] = {}
        self._load()

    def _load(self) -> None:
        if self._projects_file.exists():
            try:
                content = self._projects_file.read_text(encoding="utf-8")
                data = json.loads(content)
                if isinstance(data, list):
                    for item in data:
                        record = ProjectRecord.model_validate(item)
                        self._projects[record.id] = record
                logger.info("Loaded %d projects from %s", len(self._projects), self._projects_file)
            except Exception:
                logger.exception("Failed to load projects from %s", self._projects_file)
                self._projects = {}
        else:
            self._projects = {}

    def _save(self) -> None:
        try:
            records = list(self._projects.values())
            content = json.dumps([r.model_dump() for r in records], ensure_ascii=False, indent=2)
            self._projects_file.write_text(content, encoding="utf-8")
        except Exception:
            logger.exception("Failed to save projects to %s", self._projects_file)

    def list_projects(self) -> list[ProjectRecord]:
        with self._lock:
            return sorted(self._projects.values(), key=lambda p: p.created_at, reverse=True)

    def get_project(self, project_id: str) -> ProjectRecord | None:
        with self._lock:
            return self._projects.get(project_id)

    def create_project(self, name: str, workspace_dir: str = "") -> ProjectRecord:
        with self._lock:
            project_id = uuid4().hex[:12]
            now = now_iso()
            if not workspace_dir:
                workspace_dir = f"./workspace/{project_id}"
            artifacts_dir = f"./artifacts/{project_id}"

            record = ProjectRecord(
                id=project_id,
                name=name,
                workspace_dir=workspace_dir,
                artifacts_dir=artifacts_dir,
                isolation_mode="project",
                created_at=now,
                updated_at=now,
                session_count=0,
            )
            self._projects[project_id] = record
            self._save()
            logger.info("Created project: %s (%s)", name, project_id)
            return record

    def delete_project(self, project_id: str) -> bool:
        with self._lock:
            if project_id not in self._projects:
                return False
            del self._projects[project_id]
            self._save()
            logger.info("Deleted project: %s", project_id)
            return True

    def update_project(self, project_id: str, updates: dict[str, Any]) -> ProjectRecord | None:
        with self._lock:
            record = self._projects.get(project_id)
            if record is None:
                return None
            for key, value in updates.items():
                if hasattr(record, key) and key not in ("id", "created_at"):
                    setattr(record, key, value)
            record.updated_at = now_iso()
            self._save()
            return record

    def increment_session_count(self, project_id: str) -> ProjectRecord | None:
        """Increment the session count for a project."""
        with self._lock:
            record = self._projects.get(project_id)
            if record is None:
                return None
            record.session_count += 1
            record.updated_at = now_iso()
            self._save()
            logger.info("Incremented session count for project %s: %d", project_id, record.session_count)
            return record

    def decrement_session_count(self, project_id: str) -> ProjectRecord | None:
        """Decrement the session count for a project."""
        with self._lock:
            record = self._projects.get(project_id)
            if record is None:
                return None
            record.session_count = max(0, record.session_count - 1)
            record.updated_at = now_iso()
            self._save()
            logger.info("Decremented session count for project %s: %d", project_id, record.session_count)
            return record
