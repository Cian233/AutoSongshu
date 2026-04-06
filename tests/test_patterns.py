"""Tests for claw-code inspired patterns."""

from __future__ import annotations

import pytest

from autosongshu_agent import (
    BudgetCheckResult,
    BudgetConfig,
    BudgetTracker,
    StopReason,
    ToolExecutionResult,
    ToolBatchResult,
    TurnResult,
    AgentExecutionResult,
)


class TestToolExecutionResult:
    def test_success_result(self) -> None:
        result = ToolExecutionResult.success_result(
            tool_name="test_tool",
            output={"result": "success"},
            arguments={"arg1": "value1"},
        )
        assert result.success is True
        assert result.handled is True
        assert result.error is None
        assert result.tool_name == "test_tool"

    def test_error_result(self) -> None:
        result = ToolExecutionResult.error_result(
            tool_name="test_tool",
            error="Something went wrong",
        )
        assert result.success is False
        assert result.handled is True
        assert result.error == "Something went wrong"

    def test_permission_denied(self) -> None:
        result = ToolExecutionResult.permission_denied(
            tool_name="dangerous_tool",
            reason="High risk tool requires approval",
        )
        assert result.success is False
        assert result.handled is False
        assert "High risk" in result.error

    def test_not_found(self) -> None:
        result = ToolExecutionResult.not_found("unknown_tool")
        assert result.success is False
        assert result.handled is False
        assert "unknown_tool" in result.error

    def test_summary(self) -> None:
        success = ToolExecutionResult.success_result("tool", "output")
        assert "✓" in success.summary()

        error = ToolExecutionResult.error_result("tool", "error")
        assert "✗" in error.summary()

        denied = ToolExecutionResult.permission_denied("tool")
        assert "⊘" in denied.summary()


class TestToolBatchResult:
    def test_all_succeeded(self) -> None:
        results = ToolBatchResult(
            results=(
                ToolExecutionResult.success_result("tool1", "out1"),
                ToolExecutionResult.success_result("tool2", "out2"),
            )
        )
        assert results.all_succeeded is True
        assert results.any_succeeded is True

    def test_any_succeeded(self) -> None:
        results = ToolBatchResult(
            results=(
                ToolExecutionResult.success_result("tool1", "out1"),
                ToolExecutionResult.error_result("tool2", "error"),
            )
        )
        assert results.all_succeeded is False
        assert results.any_succeeded is True

    def test_failed_results(self) -> None:
        results = ToolBatchResult(
            results=(
                ToolExecutionResult.success_result("tool1", "out1"),
                ToolExecutionResult.error_result("tool2", "error"),
            )
        )
        assert len(results.failed_results) == 1

    def test_get_result(self) -> None:
        results = ToolBatchResult(
            results=(
                ToolExecutionResult.success_result("tool1", "out1"),
                ToolExecutionResult.success_result("tool2", "out2"),
            )
        )
        tool1 = results.get_result("tool1")
        assert tool1 is not None
        assert tool1.tool_name == "tool1"

        missing = results.get_result("tool3")
        assert missing is None

    def test_summary(self) -> None:
        results = ToolBatchResult(
            results=(
                ToolExecutionResult.success_result("tool1", "out1"),
                ToolExecutionResult.error_result("tool2", "error"),
            )
        )
        assert "1/2 tools succeeded" in results.summary()


class TestStopReason:
    def test_is_success(self) -> None:
        assert StopReason.COMPLETED.is_success() is True
        assert StopReason.ERROR.is_success() is False

    def test_is_error(self) -> None:
        assert StopReason.ERROR.is_error() is True
        assert StopReason.TIMEOUT.is_error() is True
        assert StopReason.COMPLETED.is_error() is False

    def test_description(self) -> None:
        assert "正常完成" in StopReason.COMPLETED.description()
        assert "错误" in StopReason.ERROR.description()


class TestTurnResult:
    def test_success(self) -> None:
        result = TurnResult(
            assistant_message="Hello",
            stop_reason=StopReason.COMPLETED,
            input_tokens=100,
            output_tokens=50,
        )
        assert result.success is True
        assert result.total_tokens == 150

    def test_should_continue(self) -> None:
        completed = TurnResult("Hello", StopReason.COMPLETED)
        assert completed.should_continue is True

        max_turns = TurnResult("Hello", StopReason.MAX_TURNS_REACHED)
        assert max_turns.should_continue is False

    def test_to_dict(self) -> None:
        result = TurnResult(
            assistant_message="Hello",
            stop_reason=StopReason.COMPLETED,
            input_tokens=100,
            output_tokens=50,
            turn_number=1,
        )
        data = result.to_dict()
        assert data["success"] is True
        assert data["total_tokens"] == 150


class TestAgentExecutionResult:
    def test_turn_count(self) -> None:
        result = AgentExecutionResult(
            turns=(
                TurnResult("Hello", StopReason.COMPLETED, turn_number=1),
                TurnResult("World", StopReason.COMPLETED, turn_number=2),
            )
        )
        assert result.turn_count == 2

    def test_success(self) -> None:
        success = AgentExecutionResult(
            turns=(TurnResult("Hello", StopReason.COMPLETED),)
        )
        assert success.success is True

        failed = AgentExecutionResult(turns=(TurnResult("Hello", StopReason.ERROR),))
        assert failed.success is False

    def test_has_errors(self) -> None:
        result = AgentExecutionResult(
            turns=(
                TurnResult("Hello", StopReason.COMPLETED),
                TurnResult("Oops", StopReason.ERROR),
            )
        )
        assert result.has_errors is True

    def test_get_turn(self) -> None:
        result = AgentExecutionResult(
            turns=(
                TurnResult("Hello", StopReason.COMPLETED, turn_number=1),
                TurnResult("World", StopReason.COMPLETED, turn_number=2),
            )
        )
        turn = result.get_turn(2)
        assert turn is not None
        assert turn.assistant_message == "World"


class TestBudgetConfig:
    def test_within_budget(self) -> None:
        config = BudgetConfig(max_total_tokens=1000)
        result = config.check_budget(100, 100)
        assert result.allowed is True
        assert result.reason is None

    def test_exceeds_budget(self) -> None:
        config = BudgetConfig(max_total_tokens=100)
        result = config.check_budget(50, 60)  # 110 > 100
        assert result.allowed is False
        assert "exceeded" in result.reason

    def test_warning_threshold(self) -> None:
        config = BudgetConfig(max_total_tokens=100, warning_threshold=0.8)
        # Slightly above 80% should trigger warning
        result = config.check_budget(41, 41)  # 82/100 = 82%
        assert result.allowed is True
        assert result.is_warning is True


class TestBudgetTracker:
    def test_add_usage(self) -> None:
        tracker = BudgetTracker(BudgetConfig(max_total_tokens=1000))
        result = tracker.add_usage(100, 100, "turn_1")
        assert tracker.input_tokens == 100
        assert tracker.output_tokens == 100
        assert result.allowed is True

    def test_check_before_call(self) -> None:
        tracker = BudgetTracker(BudgetConfig(max_total_tokens=1000))
        tracker.add_usage(400, 400)  # 800 used

        # Check if we can add another 200
        result = tracker.check_before_call(100, 100)  # Would be 1000 total
        assert result.allowed is True

    def test_increment_turn(self) -> None:
        tracker = BudgetTracker(BudgetConfig(max_turns=3))
        assert tracker.increment_turn() is True  # 1
        assert tracker.increment_turn() is True  # 2
        assert tracker.increment_turn() is True  # 3
        assert tracker.increment_turn() is False  # 4 > 3

    def test_get_remaining(self) -> None:
        config = BudgetConfig(
            max_input_tokens=1000, max_output_tokens=500, max_turns=10
        )
        tracker = BudgetTracker(config)
        tracker.add_usage(200, 100)
        tracker.increment_turn()

        remaining = tracker.get_remaining()
        assert remaining["input"] == 800
        assert remaining["output"] == 400
        assert remaining["turns"] == 9

    def test_get_summary(self) -> None:
        config = BudgetConfig(max_total_tokens=1000)
        tracker = BudgetTracker(config)
        tracker.add_usage(200, 100)

        summary = tracker.get_summary()
        assert summary["total_used"] == 300
        assert summary["usage_ratio"] == 0.3

    def test_reset(self) -> None:
        tracker = BudgetTracker(BudgetConfig(max_total_tokens=1000))
        tracker.add_usage(100, 100)
        tracker.increment_turn()

        tracker.reset()
        assert tracker.input_tokens == 0
        assert tracker.output_tokens == 0
        assert tracker.turn_count == 0
