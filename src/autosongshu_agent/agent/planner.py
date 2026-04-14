from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..config import AppConfig
from ..runtime import PentestRuntime
from .builder import _AgentBuilderMixin

logger = logging.getLogger(__name__)


class PentestPhase(str, Enum):
    RECON = "recon"
    SCANNING = "scanning"
    EXPLOITATION = "exploitation"
    REPORTING = "reporting"


class SubTaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SubTask:
    id: str
    name: str
    phase: PentestPhase
    description: str
    assigned_agent_id: str | None = None
    status: SubTaskStatus = SubTaskStatus.PENDING
    result: str | None = None


@dataclass
class PentestPlan:
    target: str
    phases: list[PentestPhase]
    subtasks: list[SubTask] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    metadata: dict[str, Any] = field(default_factory=dict)


class PlannerAgent(_AgentBuilderMixin):
    def __init__(
        self,
        config: AppConfig,
        artifact_session_name: str | None = None,
        sandbox_user_id: str | None = None,
    ) -> None:
        self.config = config
        self.runtime = PentestRuntime(
            config,
            artifact_session_name=artifact_session_name,
            sandbox_user_id=sandbox_user_id,
        )
        self._current_plan: PentestPlan | None = None

    def analyze_target(self, target: str) -> dict[str, Any]:
        logger.info("Analyzing target: %s", target)
        analysis: dict[str, Any] = {
            "target": target,
            "phase_recommendations": [
                PentestPhase.RECON,
                PentestPhase.SCANNING,
                PentestPhase.EXPLOITATION,
                PentestPhase.REPORTING,
            ],
            "risk_level": "unknown",
            "notes": [],
        }
        logger.info("Target analysis complete for: %s", target)
        return analysis

    def generate_plan(
        self,
        target: str,
        phases: list[PentestPhase] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PentestPlan:
        if phases is None:
            phases = list(PentestPhase)

        logger.info(
            "Generating plan for target=%s with phases=%s", target, [p.value for p in phases]
        )

        plan = PentestPlan(
            target=target,
            phases=phases,
            status=PlanStatus.DRAFT,
            metadata=metadata or {},
        )

        self._current_plan = plan
        self._persist_plan(plan)
        logger.info("Plan generated and persisted: target=%s, phases=%d", target, len(phases))
        return plan

    def decompose_to_subtasks(
        self,
        plan: PentestPhase | None = None,
    ) -> list[SubTask]:
        if self._current_plan is None:
            raise RuntimeError("No plan has been generated. Call generate_plan() first.")

        phases = [plan] if plan is not None else self._current_plan.phases
        subtasks: list[SubTask] = []

        for phase in phases:
            phase_subtasks = self._create_subtasks_for_phase(phase)
            subtasks.extend(phase_subtasks)

        self._current_plan.subtasks = subtasks
        self._persist_plan(self._current_plan)
        logger.info(
            "Decomposed plan into %d subtasks across %d phase(s)",
            len(subtasks),
            len(phases),
        )
        return subtasks

    def dispatch_subtask(self, subtask_id: str, agent_id: str | None = None) -> SubTask:
        if self._current_plan is None:
            raise RuntimeError("No plan has been generated. Call generate_plan() first.")

        subtask = self._find_subtask(subtask_id)
        if subtask is None:
            raise ValueError(f"Subtask '{subtask_id}' not found in current plan.")

        if subtask.status != SubTaskStatus.PENDING:
            logger.warning(
                "Subtask '%s' is in status '%s', cannot dispatch.",
                subtask_id,
                subtask.status.value,
            )
            return subtask

        subtask.assigned_agent_id = agent_id
        subtask.status = SubTaskStatus.IN_PROGRESS
        self._persist_plan(self._current_plan)
        logger.info(
            "Dispatched subtask '%s' (%s) to agent '%s'",
            subtask_id,
            subtask.name,
            agent_id or "unassigned",
        )
        return subtask

    def complete_subtask(self, subtask_id: str, result: str, *, success: bool = True) -> SubTask:
        if self._current_plan is None:
            raise RuntimeError("No plan has been generated. Call generate_plan() first.")

        subtask = self._find_subtask(subtask_id)
        if subtask is None:
            raise ValueError(f"Subtask '{subtask_id}' not found in current plan.")

        subtask.status = SubTaskStatus.COMPLETED if success else SubTaskStatus.FAILED
        subtask.result = result
        self._persist_plan(self._current_plan)
        logger.info(
            "Subtask '%s' completed (success=%s): %s",
            subtask_id,
            success,
            result[:120],
        )
        return subtask

    def get_plan_summary(self) -> dict[str, Any]:
        if self._current_plan is None:
            return {"error": "No plan has been generated."}

        phase_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for st in self._current_plan.subtasks:
            phase_counts[st.phase.value] = phase_counts.get(st.phase.value, 0) + 1
            status_counts[st.status.value] = status_counts.get(st.status.value, 0) + 1

        return {
            "target": self._current_plan.target,
            "status": self._current_plan.status.value,
            "phases": [p.value for p in self._current_plan.phases],
            "total_subtasks": len(self._current_plan.subtasks),
            "phase_breakdown": phase_counts,
            "status_breakdown": status_counts,
        }

    @property
    def current_plan(self) -> PentestPlan | None:
        return self._current_plan

    def _create_subtasks_for_phase(self, phase: PentestPhase) -> list[SubTask]:
        templates = {
            PentestPhase.RECON: [
                ("Identify target surface", "Enumerate all reachable endpoints and entry points of the target."),
                ("Gather technology stack info", "Detect frameworks, languages, and server technologies in use."),
                ("Map authentication flows", "Document login, session, and authorization mechanisms."),
            ],
            PentestPhase.SCANNING: [
                ("Run vulnerability scan", "Execute automated and manual scans for known vulnerability classes."),
                ("Analyze input vectors", "Identify and catalog all user-controlled input points."),
                ("Enumerate API endpoints", "Discover and document all API routes and their parameters."),
            ],
            PentestPhase.EXPLOITATION: [
                ("Validate high-confidence findings", "Confirm suspected vulnerabilities with minimal-impact proof-of-concept."),
                ("Develop exploitation chain", "Chain individual findings into a coherent attack path if applicable."),
                ("Assess business impact", "Evaluate the real-world impact of confirmed vulnerabilities."),
            ],
            PentestPhase.REPORTING: [
                ("Compile findings summary", "Aggregate all confirmed and candidate findings with evidence."),
                ("Draft remediation guidance", "Provide actionable remediation steps for each finding."),
                ("Generate final report", "Produce the structured penetration testing report artifact."),
            ],
        }

        subtasks: list[SubTask] = []
        for name, description in templates.get(phase, []):
            subtasks.append(
                SubTask(
                    id=str(uuid.uuid4())[:8],
                    name=name,
                    phase=phase,
                    description=description,
                )
            )
        return subtasks

    def _find_subtask(self, subtask_id: str) -> SubTask | None:
        if self._current_plan is None:
            return None
        for st in self._current_plan.subtasks:
            if st.id == subtask_id:
                return st
        return None

    def _persist_plan(self, plan: PentestPlan) -> None:
        plan_data: dict[str, Any] = {
            "target": plan.target,
            "phases": [p.value for p in plan.phases],
            "status": plan.status.value,
            "metadata": plan.metadata,
            "subtasks": [
                {
                    "id": st.id,
                    "name": st.name,
                    "phase": st.phase.value,
                    "description": st.description,
                    "assigned_agent_id": st.assigned_agent_id,
                    "status": st.status.value,
                    "result": st.result,
                }
                for st in plan.subtasks
            ],
        }
        self.runtime.artifacts.write_json("current_plan.json", plan_data)
        logger.debug("Plan persisted to artifacts: %s", plan.target)


__all__ = [
    "PentestPhase",
    "SubTaskStatus",
    "PlanStatus",
    "SubTask",
    "PentestPlan",
    "PlannerAgent",
]
