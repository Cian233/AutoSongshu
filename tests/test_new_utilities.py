"""
Tests for new utilities - lazy_schema and denial_tracking.
"""

import pytest
from autosongshu_agent.utils import (
    LazySchema,
    lazy_schema,
    DenialTracking,
    get_global_denial_tracking,
    reset_global_denial_tracking,
)


class TestLazySchema:
    """Tests for lazy_schema."""

    def test_lazy_construction(self):
        """Test that schema is constructed lazily."""
        call_count = [0]

        def factory():
            call_count[0] += 1
            return {"type": "object"}

        schema = lazy_schema(factory)

        # Not constructed yet
        assert call_count[0] == 0

        # First access constructs
        result = schema()
        assert call_count[0] == 1
        assert result == {"type": "object"}

        # Second access returns cached
        result2 = schema()
        assert call_count[0] == 1  # Not called again
        assert result2 is result  # Same instance

    def test_reset(self):
        """Test that reset clears cache."""
        call_count = [0]

        def factory():
            call_count[0] += 1
            return {"value": call_count[0]}

        schema = lazy_schema(factory)

        result = schema()
        assert call_count[0] == 1
        assert result == {"value": 1}

        schema.reset()
        result2 = schema()
        assert call_count[0] == 2  # Called again after reset
        assert result2 == {"value": 2}


class TestDenialTracking:
    """Tests for DenialTracking."""

    def test_record_denial(self):
        """Test recording denials."""
        tracking = DenialTracking()

        tracking.record_denial("test reason 1")
        tracking.record_denial("test reason 2")

        assert tracking.consecutive_denials == 2
        assert tracking.total_denials == 2
        assert tracking.last_reason == "test reason 2"

    def test_consecutive_reset_on_approval(self):
        """Test that approval resets consecutive denials."""
        tracking = DenialTracking()

        tracking.record_denial()
        tracking.record_denial()
        assert tracking.consecutive_denials == 2

        tracking.record_approval()
        assert tracking.consecutive_denials == 0
        assert tracking.total_denials == 2  # Total not reset

    def test_escalation_threshold(self):
        """Test escalation when threshold reached."""
        tracking = DenialTracking(consecutive_threshold=3)

        tracking.record_denial()
        tracking.record_denial()
        assert not tracking.should_escalate()

        tracking.record_denial()
        assert tracking.should_escalate()

    def test_total_threshold(self):
        """Test total denial threshold."""
        tracking = DenialTracking(total_threshold=5)

        for _ in range(4):
            tracking.record_denial()
            tracking.record_approval()  # Reset consecutive

        assert tracking.consecutive_denials == 0
        assert tracking.total_denials == 4
        assert not tracking.should_escalate()

        tracking.record_denial()
        assert tracking.should_escalate()  # Total >= 5

    def test_reset(self):
        """Test complete reset."""
        tracking = DenialTracking()

        tracking.record_denial("reason")
        tracking.record_denial("another")

        tracking.reset()

        assert tracking.consecutive_denials == 0
        assert tracking.total_denials == 0
        assert tracking.last_reason is None

    def test_global_tracking(self):
        """Test global tracking instance."""
        reset_global_denial_tracking()
        tracking = get_global_denial_tracking()

        tracking.record_denial()
        assert tracking.total_denials == 1

        reset_global_denial_tracking()
        assert get_global_denial_tracking().total_denials == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
