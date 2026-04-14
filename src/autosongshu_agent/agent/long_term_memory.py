from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Experience:
    id: str
    session_id: str
    target_url: str
    target_type: str
    tech_stack: list[str]
    vulnerability_types: list[str]
    findings: list[dict]
    successful_strategies: list[str]
    failed_approaches: list[str]
    lessons_learned: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "target_url": self.target_url,
            "target_type": self.target_type,
            "tech_stack": self.tech_stack,
            "vulnerability_types": self.vulnerability_types,
            "findings": self.findings,
            "successful_strategies": self.successful_strategies,
            "failed_approaches": self.failed_approaches,
            "lessons_learned": self.lessons_learned,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Experience:
        return cls(
            id=data["id"],
            session_id=data["session_id"],
            target_url=data["target_url"],
            target_type=data["target_type"],
            tech_stack=data.get("tech_stack", []),
            vulnerability_types=data.get("vulnerability_types", []),
            findings=data.get("findings", []),
            successful_strategies=data.get("successful_strategies", []),
            failed_approaches=data.get("failed_approaches", []),
            lessons_learned=data.get("lessons_learned", ""),
            created_at=data.get("created_at", 0.0),
        )

    def render_for_prompt(self) -> str:
        lines = [
            f"## Experience: {self.target_type} ({', '.join(self.vulnerability_types) if self.vulnerability_types else 'unknown'})",
            f"- Target: {self.target_url}",
            f"- Tech Stack: {', '.join(self.tech_stack) if self.tech_stack else 'N/A'}",
        ]
        if self.successful_strategies:
            lines.append("- Successful Strategies:")
            for s in self.successful_strategies:
                lines.append(f"  - {s}")
        if self.failed_approaches:
            lines.append("- Failed Approaches:")
            for f in self.failed_approaches:
                lines.append(f"  - {f}")
        if self.lessons_learned:
            lines.append(f"- Lessons Learned: {self.lessons_learned}")
        if self.findings:
            lines.append("- Key Findings:")
            for finding in self.findings[:5]:
                title = finding.get("title", "Unknown")
                severity = finding.get("severity", "unknown")
                lines.append(f"  - [{severity.upper()}] {title}")
        return "\n".join(lines)


class LongTermMemory:
    def __init__(self, storage_dir: Path | str | None = None) -> None:
        if storage_dir is None:
            storage_dir = Path("./data/long_term_memory")
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._index_file = self._storage_dir / "index.json"
        self._experiences: dict[str, Experience] = {}
        self._load_index()

    def _load_index(self) -> None:
        if not self._index_file.exists():
            return
        try:
            data = json.loads(self._index_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    exp = Experience.from_dict(item)
                    self._experiences[exp.id] = exp
            elif isinstance(data, dict):
                for exp_id, item in data.items():
                    exp = Experience.from_dict(item)
                    self._experiences[exp_id] = exp
            logger.info("Loaded %d experiences from long-term memory", len(self._experiences))
        except Exception as e:
            logger.warning("Failed to load long-term memory index: %s", e)

    def _save_index(self) -> None:
        try:
            data = [exp.to_dict() for exp in self._experiences.values()]
            self._index_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to save long-term memory index: %s", e)

    def store_experience(
        self,
        session_id: str,
        findings: list[dict],
        strategies: dict,
        target_info: dict,
    ) -> Experience:
        experience = Experience(
            id=str(uuid.uuid4()),
            session_id=session_id,
            target_url=target_info.get("target_url", ""),
            target_type=target_info.get("target_type", "web_app"),
            tech_stack=target_info.get("tech_stack", []),
            vulnerability_types=target_info.get("vulnerability_types", []),
            findings=findings,
            successful_strategies=strategies.get("successful", []),
            failed_approaches=strategies.get("failed", []),
            lessons_learned=strategies.get("lessons_learned", ""),
            created_at=time.time(),
        )
        self._experiences[experience.id] = experience
        self._save_index()
        logger.info(
            "Stored experience %s for session %s (target: %s)",
            experience.id,
            session_id,
            experience.target_url,
        )
        return experience

    def retrieve_relevant_experience(
        self,
        target: str,
        tech_stack: str | None = None,
        limit: int = 5,
    ) -> list[Experience]:
        target_lower = target.lower()
        scored: list[tuple[int, Experience]] = []

        for exp in self._experiences.values():
            score = 0
            if target_lower in exp.target_url.lower():
                score += 10
            if tech_stack and tech_stack.lower() in [t.lower() for t in exp.tech_stack]:
                score += 5
            if exp.vulnerability_types:
                score += 2
            if score > 0:
                scored.append((score, exp))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [exp for _, exp in scored[:limit]]

    def search_experiences(
        self,
        vulnerability_type: str | None = None,
        target_type: str | None = None,
        limit: int = 10,
    ) -> list[Experience]:
        results: list[Experience] = []

        for exp in self._experiences.values():
            match = True
            if vulnerability_type:
                vuln_lower = vulnerability_type.lower()
                if not any(vuln_lower in v.lower() for v in exp.vulnerability_types):
                    match = False
            if target_type and exp.target_type.lower() != target_type.lower():
                match = False
            if match:
                results.append(exp)

        results.sort(key=lambda e: e.created_at, reverse=True)
        return results[:limit]

    def get_all_experiences(self) -> list[Experience]:
        return list(self._experiences.values())

    def get_experience_count(self) -> int:
        return len(self._experiences)

    def render_experiences_for_prompt(
        self,
        experiences: list[Experience],
        max_chars: int = 4000,
    ) -> str:
        if not experiences:
            return ""

        lines = [
            "# Historical Penetration Testing Experiences",
            "",
            "The following are relevant experiences from previous penetration testing sessions. Use these to inform your approach:",
            "",
        ]

        current_length = len("\n".join(lines))
        for exp in experiences:
            rendered = exp.render_for_prompt()
            if current_length + len(rendered) + 2 > max_chars:
                lines.append("... (more experiences available but truncated due to context limits)")
                break
            lines.append(rendered)
            lines.append("")
            current_length += len(rendered) + 2

        return "\n".join(lines)


__all__ = ["Experience", "LongTermMemory"]
