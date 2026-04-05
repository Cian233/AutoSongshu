from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class SessionArchive:
    session_id: str
    title: str
    created_at: str
    archived_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    messages: list[dict[str, Any]] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    token_usage: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "archived_at": self.archived_at,
            "messages": self.messages,
            "memory": self.memory,
            "token_usage": self.token_usage,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionArchive":
        return cls(
            session_id=str(data.get("session_id") or ""),
            title=str(data.get("title") or ""),
            created_at=str(data.get("created_at") or ""),
            archived_at=str(
                data.get("archived_at") or datetime.now().isoformat(timespec="seconds")
            ),
            messages=list(data.get("messages") or []),
            memory=dict(data.get("memory") or {}),
            token_usage=dict(data.get("token_usage") or {}),
            metadata=dict(data.get("metadata") or {}),
        )

    def as_markdown(self) -> str:
        lines = [
            f"# Session Archive: {self.title}",
            "",
            f"- **Session ID**: {self.session_id}",
            f"- **Created**: {self.created_at}",
            f"- **Archived**: {self.archived_at}",
        ]
        if self.token_usage:
            lines.append(
                f"- **Tokens**: {self.token_usage.get('total_tokens', 0)} total"
            )
        lines.append("")
        lines.append("## Messages")
        lines.append("")
        for i, msg in enumerate(self.messages, 1):
            role = msg.get("role", "unknown")
            content = msg.get("text_content", "") or str(msg.get("content", ""))[:200]
            lines.append(f"### {i}. {role}")
            lines.append(f"{content[:500]}...")
            lines.append("")
        if self.memory:
            lines.append("## Memory Summary")
            lines.append("")
            summary = self.memory.get("summary", "") or self.memory.get(
                "recent_progress", ""
            )
            if summary:
                lines.append(summary[:500])
        return "\n".join(lines)


class SessionArchiver:
    def __init__(self, archive_dir: Path | None = None) -> None:
        self.archive_dir = archive_dir or Path(".autosongshu_archives")
        self.archive_dir.mkdir(parents=True, exist_ok=True)

    def archive_session(
        self,
        session_id: str,
        title: str,
        created_at: str,
        messages: list[dict[str, Any]],
        memory: dict[str, Any] | None = None,
        token_usage: dict[str, int] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        archive = SessionArchive(
            session_id=session_id,
            title=title,
            created_at=created_at,
            messages=messages,
            memory=memory or {},
            token_usage=token_usage or {},
            metadata=metadata or {},
        )
        archive_path = self.archive_dir / f"{session_id}.json"
        archive_path.write_text(
            json.dumps(archive.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return archive_path

    def load_archive(self, session_id: str) -> SessionArchive | None:
        archive_path = self.archive_dir / f"{session_id}.json"
        if not archive_path.exists():
            return None
        try:
            data = json.loads(archive_path.read_text(encoding="utf-8"))
            return SessionArchive.from_dict(data)
        except Exception:
            return None

    def list_archives(self) -> list[dict[str, Any]]:
        archives: list[dict[str, Any]] = []
        for path in sorted(
            self.archive_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                archives.append(
                    {
                        "session_id": data.get("session_id"),
                        "title": data.get("title"),
                        "archived_at": data.get("archived_at"),
                        "message_count": len(data.get("messages", [])),
                        "path": str(path),
                    }
                )
            except Exception:
                continue
        return archives

    def delete_archive(self, session_id: str) -> bool:
        archive_path = self.archive_dir / f"{session_id}.json"
        if archive_path.exists():
            archive_path.unlink()
            return True
        return False

    def export_as_markdown(self, session_id: str) -> str | None:
        archive = self.load_archive(session_id)
        if archive is None:
            return None
        return archive.as_markdown()

    def get_archive_stats(self) -> dict[str, Any]:
        archives = self.list_archives()
        total_messages = sum(a.get("message_count", 0) for a in archives)
        return {
            "archive_count": len(archives),
            "total_messages": total_messages,
            "archive_dir": str(self.archive_dir),
        }


def create_session_archive_from_state(
    session_state: Any,
    token_usage: dict[str, int] | None = None,
) -> SessionArchive:
    return SessionArchive(
        session_id=getattr(session_state, "session_id", ""),
        title=getattr(session_state, "title", ""),
        created_at=getattr(session_state, "created_at", ""),
        messages=[
            msg.to_dict() if hasattr(msg, "to_dict") else msg
            for msg in getattr(session_state, "messages", [])
        ],
        memory=getattr(session_state, "memory", {}).model_dump()
        if hasattr(getattr(session_state, "memory", {}), "model_dump")
        else {},
        token_usage=token_usage or {},
        metadata={
            "status": getattr(session_state, "status", ""),
            "mode": getattr(session_state, "mode", "auto"),
            "artifact_dir": getattr(session_state, "artifact_dir", ""),
        },
    )


__all__ = [
    "SessionArchive",
    "SessionArchiver",
    "create_session_archive_from_state",
]
