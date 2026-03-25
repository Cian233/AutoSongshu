from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from ..models import Finding
from .store import ArtifactStore


SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


class FindingStore:
    def __init__(self, artifacts: ArtifactStore) -> None:
        self.artifacts = artifacts
        self._findings: list[Finding] = []
        self._load()

    def _load(self) -> None:
        path = self.artifacts.session_dir / "findings.json"
        if not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(payload, list):
            return
        self._findings = []
        for item in payload:
            try:
                self._findings.append(Finding.model_validate(item))
            except Exception:
                continue

    def add(self, finding: Finding) -> Finding:
        self._findings.append(finding)
        self.persist()
        return finding

    def list(self) -> list[Finding]:
        return list(self._findings)

    def persist(self) -> Path:
        payload = [item.model_dump() for item in self._findings]
        return self.artifacts.write_json("findings.json", payload)

    def render_markdown(self, engagement_summary: dict[str, str] | None = None) -> str:
        lines = [
            "# Pentest Report",
            "",
            f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
        ]

        if engagement_summary:
            for key, value in engagement_summary.items():
                lines.append(f"- {key}: {value}")

        lines.append("")

        findings = sorted(
            self._findings,
            key=lambda item: (SEVERITY_ORDER[item.severity], item.title.lower()),
        )

        if not findings:
            lines.extend(
                [
                    "## Summary",
                    "",
                    "No validated findings were recorded during this run.",
                    "",
                ],
            )
            return "\n".join(lines)

        lines.extend(
            [
                "## Summary",
                "",
                f"Validated findings: {sum(1 for item in findings if item.status == 'validated')}",
                f"Candidate findings: {sum(1 for item in findings if item.status == 'candidate')}",
                "",
                "## Findings",
                "",
            ],
        )

        for item in findings:
            lines.append(f"### [{item.severity.upper()}] {item.title}")
            lines.append("")
            lines.append(f"- Status: {item.status}")
            if item.url:
                lines.append(f"- URL: {item.url}")
            if item.cwe:
                lines.append(f"- CWE: {item.cwe}")
            if item.tags:
                lines.append(f"- Tags: {', '.join(item.tags)}")
            lines.append(f"- Summary: {item.summary}")
            if item.recommendation:
                lines.append(f"- Recommendation: {item.recommendation}")
            if item.evidence:
                lines.append("- Evidence:")
                for entry in item.evidence:
                    lines.append(f"  - {entry}")
            lines.append("")

        return "\n".join(lines)


__all__ = ["FindingStore", "SEVERITY_ORDER"]
