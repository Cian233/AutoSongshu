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
    def __init__(
        self, root_dir: str, engagement_name: str, session_name: str | None = None
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
        self.session_dir = self.root_dir / session_name
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def path(self, relative_path: str) -> Path:
        target = self.session_dir / relative_path
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
