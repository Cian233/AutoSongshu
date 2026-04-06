"""
Session-level global state - Layer 1 of the three-layer architecture.

This is the leaf node in the import DAG - it imports almost nothing,
so it can be safely imported by anyone.

Inspired by claw-code's bootstrap/state.ts:
- Process-level singleton
- Getter/setter functions (no pub-sub)
- For truly global state that lives across the entire session
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SessionState:
    """
    Session-level global state.

    DO NOT ADD MORE STATE HERE - BE JUDICIOUS WITH GLOBAL STATE.
    Only use this for truly process-level state that:
    1. Lives across the entire session
    2. Doesn't belong to any React component
    3. Doesn't belong to any single query loop
    """

    session_id: str = ""
    parent_session_id: str | None = None

    # Path info
    cwd: str = ""
    project_root: str = ""
    original_cwd: str = ""

    # Cost tracking
    total_cost_usd: float = 0.0
    total_api_duration_ms: float = 0.0
    turn_tool_count: int = 0

    # Model usage tracking
    model_usage: dict[str, dict[str, int]] = field(default_factory=dict)

    # Session flags
    is_interactive: bool = True
    is_remote_mode: bool = False

    # Cache state
    prompt_cache_1h_eligible: bool = False

    # Telemetry
    telemetry_enabled: bool = True


# Module-level singleton
_state: SessionState = SessionState()


def get_session_id() -> str:
    """Get current session ID."""
    return _state.session_id


def set_session_id(session_id: str) -> None:
    """Set current session ID."""
    _state.session_id = session_id


def generate_session_id() -> str:
    """Generate a new session ID."""
    return f"session-{uuid.uuid4().hex[:16]}"


def init_session(cwd: str | Path | None = None) -> str:
    """Initialize session with optional CWD."""
    _state.session_id = generate_session_id()
    if cwd:
        _state.cwd = str(cwd)
        _state.project_root = str(Path(cwd).resolve())
        _state.original_cwd = _state.cwd
    return _state.session_id


def get_cwd() -> str:
    """Get current working directory."""
    return _state.cwd


def set_cwd(cwd: str | Path) -> None:
    """Set current working directory."""
    _state.cwd = str(cwd)


def get_project_root() -> str:
    """Get project root directory."""
    return _state.project_root


def get_total_cost() -> float:
    """Get total cost in USD."""
    return _state.total_cost_usd


def add_to_total_cost(
    cost: float, model: str | None = None, usage: dict[str, int] | None = None
) -> None:
    """Add to total cost and optionally track model usage."""
    _state.total_cost_usd += cost
    _state.total_api_duration_ms += usage.get("duration_ms", 0) if usage else 0
    _state.turn_tool_count += 1

    if model and usage:
        if model not in _state.model_usage:
            _state.model_usage[model] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            }
        _state.model_usage[model]["input_tokens"] += usage.get("input_tokens", 0)
        _state.model_usage[model]["output_tokens"] += usage.get("output_tokens", 0)
        _state.model_usage[model]["total_tokens"] += usage.get("total_tokens", 0)


def get_model_usage() -> dict[str, dict[str, int]]:
    """Get model usage statistics."""
    return _state.model_usage.copy()


def get_state() -> SessionState:
    """Get the entire session state (for debugging/testing only)."""
    return _state


def reset_state() -> None:
    """Reset session state (for testing only)."""
    global _state
    _state = SessionState()
