from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from autosongshu_agent.agent.error_healing import (
    ErrorHealingConfig,
    ErrorRecoveryContext,
    ErrorRecoveryStats,
    ErrorHealingMixin,
)


class ErrorHealingConfigTests(unittest.TestCase):
    def test_default_config(self) -> None:
        config = ErrorHealingConfig()
        self.assertEqual(config.max_recovery_attempts, 3)
        self.assertTrue(config.enable_model_switching)
        self.assertTrue(config.enable_task_simplification)
        self.assertTrue(config.enable_delegation)
        self.assertTrue(config.enable_plan_mode_fallback)

    def test_custom_config(self) -> None:
        config = ErrorHealingConfig(
            max_recovery_attempts=5,
            enable_model_switching=False,
            enable_task_simplification=False,
            enable_delegation=False,
            enable_plan_mode_fallback=False,
        )
        self.assertEqual(config.max_recovery_attempts, 5)
        self.assertFalse(config.enable_model_switching)
        self.assertFalse(config.enable_task_simplification)
        self.assertFalse(config.enable_delegation)
        self.assertFalse(config.enable_plan_mode_fallback)


class ErrorRecoveryStatsTests(unittest.TestCase):
    def test_initial_state(self) -> None:
        stats = ErrorRecoveryStats()
        self.assertEqual(stats.total_errors, 0)
        self.assertEqual(stats.total_recoveries, 0)
        self.assertEqual(stats.total_failures, 0)
        self.assertEqual(stats.strategy_counts, {})
        self.assertEqual(stats.last_error_type, "")
        self.assertEqual(stats.last_recovery_strategy, "")
        self.assertEqual(stats.recovery_times_ms, [])

    def test_record_successful_recovery(self) -> None:
        stats = ErrorRecoveryStats()
        stats.record_attempt("model_switching", success=True, duration_ms=150.0)
        self.assertEqual(stats.total_errors, 1)
        self.assertEqual(stats.total_recoveries, 1)
        self.assertEqual(stats.total_failures, 0)
        self.assertEqual(stats.strategy_counts["model_switching"], 1)
        self.assertEqual(stats.last_recovery_strategy, "model_switching")
        self.assertEqual(len(stats.recovery_times_ms), 1)
        self.assertEqual(stats.recovery_times_ms[0], 150.0)

    def test_record_failed_recovery(self) -> None:
        stats = ErrorRecoveryStats()
        stats.record_attempt("task_simplification", success=False, duration_ms=200.0)
        self.assertEqual(stats.total_errors, 1)
        self.assertEqual(stats.total_recoveries, 0)
        self.assertEqual(stats.total_failures, 1)
        self.assertEqual(stats.strategy_counts["task_simplification"], 1)

    def test_record_multiple_strategies(self) -> None:
        stats = ErrorRecoveryStats()
        stats.record_attempt("model_switching", success=True, duration_ms=100.0)
        stats.record_attempt("task_simplification", success=False, duration_ms=200.0)
        stats.record_attempt("delegation", success=True, duration_ms=300.0)
        self.assertEqual(stats.total_errors, 3)
        self.assertEqual(stats.total_recoveries, 2)
        self.assertEqual(stats.total_failures, 1)
        self.assertEqual(stats.strategy_counts["model_switching"], 1)
        self.assertEqual(stats.strategy_counts["task_simplification"], 1)
        self.assertEqual(stats.strategy_counts["delegation"], 1)

    def test_success_rate(self) -> None:
        stats = ErrorRecoveryStats()
        self.assertEqual(stats.success_rate, 0.0)
        stats.record_attempt("model_switching", success=True, duration_ms=100.0)
        stats.record_attempt("task_simplification", success=False, duration_ms=200.0)
        stats.record_attempt("delegation", success=True, duration_ms=300.0)
        self.assertAlmostEqual(stats.success_rate, 2 / 3, places=4)

    def test_avg_recovery_time(self) -> None:
        stats = ErrorRecoveryStats()
        self.assertEqual(stats.avg_recovery_time_ms, 0.0)
        stats.record_attempt("model_switching", success=True, duration_ms=100.0)
        stats.record_attempt("task_simplification", success=False, duration_ms=200.0)
        self.assertAlmostEqual(stats.avg_recovery_time_ms, 150.0, places=2)

    def test_to_dict(self) -> None:
        stats = ErrorRecoveryStats()
        stats.record_attempt("model_switching", success=True, duration_ms=100.0)
        stats.last_error_type = "ConnectionError"
        d = stats.to_dict()
        self.assertIn("total_errors", d)
        self.assertIn("total_recoveries", d)
        self.assertIn("total_failures", d)
        self.assertIn("success_rate", d)
        self.assertIn("avg_recovery_time_ms", d)
        self.assertIn("strategy_counts", d)
        self.assertIn("last_error_type", d)
        self.assertIn("last_recovery_strategy", d)
        self.assertEqual(d["last_error_type"], "ConnectionError")
        self.assertEqual(d["total_errors"], 1)


class ErrorRecoveryContextTests(unittest.TestCase):
    def test_context_creation(self) -> None:
        error = ValueError("Test error")
        context = ErrorRecoveryContext(
            error=error,
            original_task="Test task",
            attempt_count=0,
        )
        self.assertIs(context.error, error)
        self.assertEqual(context.original_task, "Test task")
        self.assertEqual(context.attempt_count, 0)
        self.assertEqual(context.strategies_tried, [])

    def test_context_with_strategies(self) -> None:
        context = ErrorRecoveryContext(
            error=RuntimeError("Failed"),
            original_task="Complex task",
            attempt_count=2,
            strategies_tried=["model_switching", "task_simplification"],
        )
        self.assertEqual(context.attempt_count, 2)
        self.assertIn("model_switching", context.strategies_tried)


class ErrorHealingMixinTests(unittest.TestCase):
    def _make_mixin(self) -> ErrorHealingMixin:
        class TestClass(ErrorHealingMixin):
            def __init__(self) -> None:
                super().__init__()

        return TestClass()

    def test_mixin_initialization(self) -> None:
        mixin = self._make_mixin()
        self.assertIsNotNone(mixin.error_healing_config)
        self.assertIsNotNone(mixin.error_recovery_stats)
        self.assertIsInstance(mixin.error_healing_config, ErrorHealingConfig)
        self.assertIsInstance(mixin.error_recovery_stats, ErrorRecoveryStats)

    def test_handle_agent_error_exhausted_attempts(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.max_recovery_attempts = 0
        error = ValueError("Test error")
        success, result = mixin._handle_agent_error(error, "Test task", attempt_count=0)
        self.assertFalse(success)
        self.assertIsNone(result)

    def test_handle_agent_error_sets_last_error_type(self) -> None:
        mixin = self._make_mixin()
        error = ConnectionError("Connection failed")
        mixin._handle_agent_error(error, "Test task", attempt_count=0)
        self.assertEqual(mixin.error_recovery_stats.last_error_type, "ConnectionError")

    def test_handle_agent_error_with_model_switching(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.enable_model_switching = True
        mixin.error_healing_config.enable_task_simplification = False
        mixin.error_healing_config.enable_delegation = False
        mixin.error_healing_config.enable_plan_mode_fallback = False

        mock_router = MagicMock()
        mock_router.active_profile_name = "default"
        mock_router.list_profiles.return_value = [
            {"name": "default", "enabled": True},
            {"name": "fast-model", "enabled": True},
        ]
        mock_router.set_active = MagicMock()
        mixin.model_router = mock_router

        error = ValueError("Model error")
        success, result = mixin._handle_agent_error(error, "Test task", attempt_count=0)
        self.assertTrue(success)
        self.assertEqual(result["strategy"], "model_switching")
        self.assertEqual(result["to_model"], "fast-model")

    def test_handle_agent_error_model_switching_no_router(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.enable_model_switching = True
        mixin.error_healing_config.enable_task_simplification = False
        mixin.error_healing_config.enable_delegation = False
        mixin.error_healing_config.enable_plan_mode_fallback = False

        if hasattr(mixin, "model_router"):
            del mixin.model_router

        error = ValueError("Model error")
        success, result = mixin._handle_agent_error(error, "Test task", attempt_count=0)
        self.assertFalse(success)
        self.assertIsNone(result)

    def test_handle_agent_error_model_switching_no_alternatives(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.enable_model_switching = True
        mixin.error_healing_config.enable_task_simplification = False
        mixin.error_healing_config.enable_delegation = False
        mixin.error_healing_config.enable_plan_mode_fallback = False

        mock_router = MagicMock()
        mock_router.active_profile_name = "default"
        mock_router.list_profiles.return_value = [
            {"name": "default", "enabled": True},
        ]
        mixin.model_router = mock_router

        error = ValueError("Model error")
        success, result = mixin._handle_agent_error(error, "Test task", attempt_count=0)
        self.assertFalse(success)
        self.assertIsNone(result)

    def test_handle_agent_error_task_simplification(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.enable_model_switching = False
        mixin.error_healing_config.enable_task_simplification = True
        mixin.error_healing_config.enable_delegation = False
        mixin.error_healing_config.enable_plan_mode_fallback = False

        error = ValueError("Task error")
        success, result = mixin._handle_agent_error(error, "Complex task", attempt_count=0)
        self.assertTrue(success)
        self.assertEqual(result["strategy"], "task_simplification")
        self.assertIn("Complex task", result["simplified_task"])
        self.assertIn("Break the following task", result["simplified_task"])

    def test_handle_agent_error_delegation(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.enable_model_switching = False
        mixin.error_healing_config.enable_task_simplification = False
        mixin.error_healing_config.enable_delegation = True
        mixin.error_healing_config.enable_plan_mode_fallback = False

        mixin._build_sub_agent = MagicMock()

        error = ValueError("Delegation error")
        success, result = mixin._handle_agent_error(error, "Delegated task", attempt_count=0)
        self.assertTrue(success)
        self.assertEqual(result["strategy"], "delegation")
        self.assertEqual(result["delegated_role"], "recon")
        self.assertEqual(result["delegated_task"], "Delegated task")

    def test_handle_agent_error_delegation_no_builder(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.enable_model_switching = False
        mixin.error_healing_config.enable_task_simplification = False
        mixin.error_healing_config.enable_delegation = True
        mixin.error_healing_config.enable_plan_mode_fallback = False

        error = ValueError("Delegation error")
        success, result = mixin._handle_agent_error(error, "Delegated task", attempt_count=0)
        self.assertFalse(success)
        self.assertIsNone(result)

    def test_handle_agent_error_plan_mode_fallback(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.enable_model_switching = False
        mixin.error_healing_config.enable_task_simplification = False
        mixin.error_healing_config.enable_delegation = False
        mixin.error_healing_config.enable_plan_mode_fallback = True

        error = ValueError("Plan error")
        success, result = mixin._handle_agent_error(error, "Plan task", attempt_count=0)
        self.assertTrue(success)
        self.assertEqual(result["strategy"], "plan_mode_fallback")
        self.assertIn("Plan error", result["plan_prompt"])
        self.assertIn("Plan task", result["plan_prompt"])

    def test_handle_agent_error_tries_multiple_strategies(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.enable_model_switching = True
        mixin.error_healing_config.enable_task_simplification = True
        mixin.error_healing_config.enable_delegation = True
        mixin.error_healing_config.enable_plan_mode_fallback = True

        if hasattr(mixin, "model_router"):
            del mixin.model_router

        error = ValueError("Multi-strategy error")
        success, result = mixin._handle_agent_error(error, "Complex task", attempt_count=0)
        self.assertTrue(success)
        self.assertIn(result["strategy"], ["task_simplification", "delegation", "plan_mode_fallback"])

    def test_handle_agent_error_records_stats(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.enable_model_switching = False
        mixin.error_healing_config.enable_task_simplification = True
        mixin.error_healing_config.enable_delegation = False
        mixin.error_healing_config.enable_plan_mode_fallback = False

        error = ValueError("Stats test")
        mixin._handle_agent_error(error, "Task", attempt_count=0)
        self.assertEqual(mixin.error_recovery_stats.total_errors, 1)
        self.assertEqual(mixin.error_recovery_stats.total_recoveries, 1)
        self.assertEqual(mixin.error_recovery_stats.strategy_counts["task_simplification"], 1)

    def test_get_recovery_stats(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.enable_model_switching = False
        mixin.error_healing_config.enable_task_simplification = True
        mixin.error_healing_config.enable_delegation = False
        mixin.error_healing_config.enable_plan_mode_fallback = False

        error = ValueError("Stats test")
        mixin._handle_agent_error(error, "Task", attempt_count=0)
        stats = mixin.get_recovery_stats()
        self.assertEqual(stats["total_errors"], 1)
        self.assertEqual(stats["total_recoveries"], 1)
        self.assertIn("success_rate", stats)

    def test_reset_recovery_stats(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.enable_model_switching = False
        mixin.error_healing_config.enable_task_simplification = True
        mixin.error_healing_config.enable_delegation = False
        mixin.error_healing_config.enable_plan_mode_fallback = False

        error = ValueError("Reset test")
        mixin._handle_agent_error(error, "Task", attempt_count=0)
        self.assertEqual(mixin.error_recovery_stats.total_errors, 1)

        mixin.reset_recovery_stats()
        self.assertEqual(mixin.error_recovery_stats.total_errors, 0)
        self.assertEqual(mixin.error_recovery_stats.total_recoveries, 0)

    def test_recovery_strategy_failure_does_not_crash(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.enable_model_switching = True
        mixin.error_healing_config.enable_task_simplification = False
        mixin.error_healing_config.enable_delegation = False
        mixin.error_healing_config.enable_plan_mode_fallback = True

        mock_router = MagicMock()
        mock_router.active_profile_name = "default"
        mock_router.list_profiles.side_effect = RuntimeError("Router broken")
        mixin.model_router = mock_router

        error = ValueError("Test error")
        success, result = mixin._handle_agent_error(error, "Task", attempt_count=0)
        self.assertTrue(success)
        self.assertEqual(result["strategy"], "plan_mode_fallback")

    def test_handle_agent_error_respects_max_attempts(self) -> None:
        mixin = self._make_mixin()
        mixin.error_healing_config.max_recovery_attempts = 2
        mixin.error_healing_config.enable_model_switching = True
        mixin.error_healing_config.enable_task_simplification = False
        mixin.error_healing_config.enable_delegation = False
        mixin.error_healing_config.enable_plan_mode_fallback = False

        if hasattr(mixin, "model_router"):
            del mixin.model_router

        error = ValueError("Test error")
        success, result = mixin._handle_agent_error(error, "Task", attempt_count=2)
        self.assertFalse(success)
        self.assertIsNone(result)


class RecoveryStrategyTests(unittest.TestCase):
    def _make_mixin(self) -> ErrorHealingMixin:
        class TestClass(ErrorHealingMixin):
            def __init__(self) -> None:
                super().__init__()

        return TestClass()

    def test_retry_with_different_model_success(self) -> None:
        mixin = self._make_mixin()
        mock_router = MagicMock()
        mock_router.active_profile_name = "default"
        mock_router.list_profiles.return_value = [
            {"name": "default", "enabled": True},
            {"name": "fast-model", "enabled": True},
        ]
        mock_router.set_active = MagicMock()
        mixin.model_router = mock_router

        context = ErrorRecoveryContext(
            error=ValueError("Model error"),
            original_task="Test task",
            attempt_count=0,
        )
        success, result = mixin._retry_with_different_model(context.error, context)
        self.assertTrue(success)
        self.assertEqual(result["from_model"], "default")
        self.assertEqual(result["to_model"], "fast-model")

    def test_simplify_task_and_retry(self) -> None:
        mixin = self._make_mixin()
        context = ErrorRecoveryContext(
            error=ValueError("Task error"),
            original_task="Complex multi-step task",
            attempt_count=0,
        )
        success, result = mixin._simplify_task_and_retry(context.error, context)
        self.assertTrue(success)
        self.assertIn("Complex multi-step task", result["simplified_task"])
        self.assertIn("Break the following task", result["simplified_task"])

    def test_delegate_to_specialized_agent(self) -> None:
        mixin = self._make_mixin()
        mixin._build_sub_agent = MagicMock()
        context = ErrorRecoveryContext(
            error=ValueError("Delegation error"),
            original_task="Delegated task",
            attempt_count=0,
        )
        success, result = mixin._delegate_to_specialized_agent(context.error, context)
        self.assertTrue(success)
        self.assertEqual(result["delegated_role"], "recon")
        self.assertEqual(result["delegated_task"], "Delegated task")

    def test_fallback_to_plan_mode(self) -> None:
        mixin = self._make_mixin()
        context = ErrorRecoveryContext(
            error=ValueError("Plan error"),
            original_task="Plan task",
            attempt_count=0,
        )
        success, result = mixin._fallback_to_plan_mode(context.error, context)
        self.assertTrue(success)
        self.assertIn("Plan error", result["plan_prompt"])
        self.assertIn("Plan task", result["plan_prompt"])


if __name__ == "__main__":
    unittest.main()
