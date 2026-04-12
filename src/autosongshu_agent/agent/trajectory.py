"""Trajectory recording for agent sessions.

Provides ``TrajectoryRecorder`` which persists step-by-step execution
traces to disk as JSONL files, enabling post-hoc analysis, replay, and
debugging of agent behaviour -- inspired by the Trae MTC observability
layer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .step_model import AgentStep, StepState, TaskState


class TrajectoryRecorder:
    """Records agent execution trajectories to disk.

    Each session produces a JSONL file under the given *base_dir* named
    ``<session_id>.trajectory.jsonl``.  Every call to :meth:`record_step`
    appends one JSON line.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._session_file: Path | None = None
        self._steps: list[AgentStep] = []
        self._session_state: TaskState | None = None

    # -- Session lifecycle --------------------------------------------------

    def start_session(self, session_id: str) -> None:
        """Begin a new recording session."""
        self._session_file = self._base_dir / f"{session_id}.trajectory.jsonl"
        self._steps = []
        self._session_state = TaskState.RUNNING
        # Write an empty file to mark the session.
        self._session_file.write_text("", encoding="utf-8")

    def end_session(self, state: TaskState) -> None:
        """Close the current recording session."""
        self._session_state = state
        if self._session_file is not None:
            # Append a final summary line.
            summary = {
                "type": "session_end",
                "state": state.value,
                "total_steps": len(self._steps),
            }
            with self._session_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(summary, ensure_ascii=False, default=str))
                fh.write("\n")

    # -- Step recording -----------------------------------------------------

    def record_step(self, step: AgentStep) -> None:
        """Persist a single step to the trajectory file."""
        self._steps.append(step)
        if self._session_file is not None:
            with self._session_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(step.to_dict(), ensure_ascii=False, default=str))
                fh.write("\n")

    # -- Query helpers ------------------------------------------------------

    @property
    def steps(self) -> list[AgentStep]:
        """Return a read-only view of recorded steps."""
        return list(self._steps)

    @property
    def step_count(self) -> int:
        return len(self._steps)

    @property
    def current_state(self) -> TaskState | None:
        return self._session_state

    def summary(self) -> dict[str, Any]:
        """Return a lightweight summary of the current session."""
        succeeded = sum(1 for s in self._steps if s.state == StepState.SUCCEEDED)
        failed = sum(1 for s in self._steps if s.state == StepState.FAILED)
        total_input = sum(s.token_usage.input_tokens for s in self._steps)
        total_output = sum(s.token_usage.output_tokens for s in self._steps)
        return {
            "state": self._session_state.value if self._session_state else None,
            "total_steps": len(self._steps),
            "succeeded": succeeded,
            "failed": failed,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "session_file": str(self._session_file) if self._session_file else None,
        }


__all__ = ["TrajectoryRecorder"]
