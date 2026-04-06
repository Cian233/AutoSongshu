"""
Denial Tracking - Circuit breaker for tool permissions.

Inspired by claw-code's denial tracking system.

Problem: Agent might retry denied operations infinitely.
Solution: Track denials and fallback to user confirmation or abort.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DenialTracking:
    """
    Track permission denials for circuit breaking.

    When denials exceed threshold, stop retrying and escalate.

    Thresholds:
    - consecutive_threshold: Stop after N consecutive denials (default: 3)
    - total_threshold: Stop after N total denials (default: 20)
    """

    consecutive_threshold: int = 3
    total_threshold: int = 20

    _consecutive_denials: int = field(default=0, init=False)
    _total_denials: int = field(default=0, init=False)
    _denial_reasons: list[str] = field(default_factory=list, init=False)

    def record_denial(self, reason: str = "") -> None:
        """
        Record a permission denial.

        Args:
            reason: Why the operation was denied
        """
        self._consecutive_denials += 1
        self._total_denials += 1
        if reason:
            self._denial_reasons.append(reason)

    def record_approval(self) -> None:
        """Reset consecutive denials on approval."""
        self._consecutive_denials = 0

    def should_escalate(self) -> bool:
        """
        Check if we should escalate (stop retrying).

        Returns:
            True if consecutive or total denials exceed threshold
        """
        return (
            self._consecutive_denials >= self.consecutive_threshold
            or self._total_denials >= self.total_threshold
        )

    def is_circuit_open(self) -> bool:
        """Alias for should_escalate()."""
        return self.should_escalate()

    def reset(self) -> None:
        """Reset all tracking."""
        self._consecutive_denials = 0
        self._total_denials = 0
        self._denial_reasons.clear()

    @property
    def consecutive_denials(self) -> int:
        """Get consecutive denial count."""
        return self._consecutive_denials

    @property
    def total_denials(self) -> int:
        """Get total denial count."""
        return self._total_denials

    @property
    def last_reason(self) -> str | None:
        """Get the last denial reason."""
        return self._denial_reasons[-1] if self._denial_reasons else None

    def get_summary(self) -> dict[str, Any]:
        """Get summary of denial tracking."""
        return {
            "consecutive_denials": self._consecutive_denials,
            "total_denials": self._total_denials,
            "consecutive_threshold": self.consecutive_threshold,
            "total_threshold": self.total_threshold,
            "circuit_open": self.should_escalate(),
        }


# Global instance for shared tracking
_global_tracking: DenialTracking | None = None


def get_global_denial_tracking() -> DenialTracking:
    """Get the global denial tracking instance."""
    global _global_tracking
    if _global_tracking is None:
        _global_tracking = DenialTracking()
    return _global_tracking


def reset_global_denial_tracking() -> None:
    """Reset the global denial tracking (for testing)."""
    global _global_tracking
    if _global_tracking:
        _global_tracking.reset()


__all__ = [
    "DenialTracking",
    "get_global_denial_tracking",
    "reset_global_denial_tracking",
]
