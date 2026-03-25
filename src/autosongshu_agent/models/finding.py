from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


Severity = Literal["info", "low", "medium", "high", "critical"]
FindingStatus = Literal["candidate", "validated"]


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    title: str
    severity: Severity
    summary: str
    url: str | None = None
    evidence: list[str] = Field(default_factory=list)
    recommendation: str | None = None
    cwe: str | None = None
    tags: list[str] = Field(default_factory=list)
    status: FindingStatus = "validated"


__all__ = ["Severity", "FindingStatus", "Finding"]
