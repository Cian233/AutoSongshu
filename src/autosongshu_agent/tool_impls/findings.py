from __future__ import annotations

from typing import Any

from agentscope.tool import ToolResponse

from ..models import Finding
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _error_response, _parse_list_like, _tool_response

registry.create_group(
    "findings",
    description="Persist and review findings collected during the assessment.",
    active=True,
)

@registry.register("findings", dedupe=False, invalidates_cache=True)
def record_finding(
    runtime: PentestRuntime,
    title: str,
    severity: str,
    summary: str,
    url: str = "",
    evidence: str = "",
    recommendation: str = "",
    cwe: str = "",
    tags: str = "",
    status: str = "validated",
) -> ToolResponse:
    """Persist a finding. Use newline-separated or JSON-list strings for evidence and tags."""
    try:
        finding = Finding(
            title=title,
            severity=severity,  # type: ignore[arg-type]
            summary=summary,
            url=url or None,
            evidence=_parse_list_like(evidence),
            recommendation=recommendation or None,
            cwe=cwe or None,
            tags=_parse_list_like(tags),
            status=status,  # type: ignore[arg-type]
        )
        saved = runtime.findings.add(finding)
        return _tool_response(saved.model_dump())
    except Exception as exc:
        return _error_response(exc)

@registry.register("findings")
def list_findings(runtime: PentestRuntime) -> ToolResponse:
    """Return all persisted findings."""
    try:
        return _tool_response([item.model_dump() for item in runtime.findings.list()])
    except Exception as exc:
        return _error_response(exc)
