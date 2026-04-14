from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ErrorHealingConfig:
    max_recovery_attempts: int = 3
    enable_model_switching: bool = True
    enable_task_simplification: bool = True
    enable_delegation: bool = True
    enable_plan_mode_fallback: bool = True


@dataclass
class ErrorRecoveryContext:
    error: Exception
    original_task: str
    attempt_count: int
    strategies_tried: list[str] = field(default_factory=list)


@dataclass
class ErrorRecoveryStats:
    total_errors: int = 0
    total_recoveries: int = 0
    total_failures: int = 0
    strategy_counts: dict[str, int] = field(default_factory=dict)
    last_error_type: str = ""
    last_recovery_strategy: str = ""
    recovery_times_ms: list[float] = field(default_factory=list)

    def record_attempt(self, strategy: str, success: bool, duration_ms: float) -> None:
        self.total_errors += 1
        if success:
            self.total_recoveries += 1
        else:
            self.total_failures += 1
        self.strategy_counts[strategy] = self.strategy_counts.get(strategy, 0) + 1
        self.recovery_times_ms.append(duration_ms)
        self.last_recovery_strategy = strategy

    @property
    def success_rate(self) -> float:
        if self.total_errors == 0:
            return 0.0
        return self.total_recoveries / self.total_errors

    @property
    def avg_recovery_time_ms(self) -> float:
        if not self.recovery_times_ms:
            return 0.0
        return sum(self.recovery_times_ms) / len(self.recovery_times_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_errors": self.total_errors,
            "total_recoveries": self.total_recoveries,
            "total_failures": self.total_failures,
            "success_rate": round(self.success_rate, 4),
            "avg_recovery_time_ms": round(self.avg_recovery_time_ms, 2),
            "strategy_counts": dict(self.strategy_counts),
            "last_error_type": self.last_error_type,
            "last_recovery_strategy": self.last_recovery_strategy,
        }


class ErrorHealingMixin:
    error_healing_config: ErrorHealingConfig
    error_recovery_stats: ErrorRecoveryStats

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.error_healing_config = ErrorHealingConfig()
        self.error_recovery_stats = ErrorRecoveryStats()

    def _handle_agent_error(
        self,
        error: Exception,
        original_task: str,
        attempt_count: int = 0,
    ) -> tuple[bool, Any]:
        self.error_recovery_stats.last_error_type = type(error).__name__

        if attempt_count >= self.error_healing_config.max_recovery_attempts:
            logger.error(
                "Error recovery exhausted after %d attempts for task: %s. "
                "Error: %s",
                attempt_count,
                original_task,
                error,
            )
            return False, None

        context = ErrorRecoveryContext(
            error=error,
            original_task=original_task,
            attempt_count=attempt_count,
            strategies_tried=[],
        )

        strategies: list[tuple[str, bool, Any]] = [
            ("model_switching", self.error_healing_config.enable_model_switching),
            ("task_simplification", self.error_healing_config.enable_task_simplification),
            ("delegation", self.error_healing_config.enable_delegation),
            ("plan_mode_fallback", self.error_healing_config.enable_plan_mode_fallback),
        ]

        for strategy_name, enabled in strategies:
            if not enabled:
                continue

            if strategy_name in context.strategies_tried:
                continue

            context.strategies_tried.append(strategy_name)
            start_time = time.monotonic()

            logger.info(
                "Attempting error recovery strategy '%s' (attempt %d/%d) for task: %s",
                strategy_name,
                attempt_count + 1,
                self.error_healing_config.max_recovery_attempts,
                original_task,
            )

            try:
                if strategy_name == "model_switching":
                    success, result = self._retry_with_different_model(error, context)
                elif strategy_name == "task_simplification":
                    success, result = self._simplify_task_and_retry(error, context)
                elif strategy_name == "delegation":
                    success, result = self._delegate_to_specialized_agent(error, context)
                elif strategy_name == "plan_mode_fallback":
                    success, result = self._fallback_to_plan_mode(error, context)
                else:
                    success, result = False, None
            except Exception as recovery_exc:
                logger.warning(
                    "Recovery strategy '%s' failed with exception: %s",
                    strategy_name,
                    recovery_exc,
                )
                success, result = False, None

            duration_ms = (time.monotonic() - start_time) * 1000
            self.error_recovery_stats.record_attempt(
                strategy=strategy_name,
                success=success,
                duration_ms=duration_ms,
            )

            if success:
                logger.info(
                    "Error recovery succeeded with strategy '%s' after %.0fms",
                    strategy_name,
                    duration_ms,
                )
                return True, result

            logger.warning(
                "Recovery strategy '%s' failed (attempt %d). Trying next strategy.",
                strategy_name,
                attempt_count + 1,
            )

        return self._handle_agent_error(
            error=error,
            original_task=original_task,
            attempt_count=attempt_count + 1,
        )

    def _retry_with_different_model(
        self,
        error: Exception,
        context: ErrorRecoveryContext,
    ) -> tuple[bool, Any]:
        logger.info(
            "Strategy: retry_with_different_model - switching model for task: %s",
            context.original_task,
        )

        if not hasattr(self, "model_router") or self.model_router is None:
            logger.warning("No model_router available; cannot switch models.")
            return False, None

        try:
            current_profile = self.model_router.active_profile_name
            profiles = self.model_router.list_profiles()

            available_profiles = [
                p for p in profiles
                if p["name"] != current_profile and p.get("enabled", True)
            ]

            if not available_profiles:
                logger.warning("No alternative model profiles available.")
                return False, None

            target_profile = available_profiles[0]
            logger.info(
                "Switching from model '%s' to '%s'",
                current_profile,
                target_profile["name"],
            )

            self.model_router.set_active(target_profile["name"])

            if hasattr(self, "_agent") and self._agent is not None:
                new_model = self.model_router.build_model_for_task(
                    self.model_router.resolve.__self__._profiles.get(
                        target_profile["name"]
                    ).tasks[0] if hasattr(self.model_router.resolve, "__self__") else "reasoning"
                )
                self._agent.model = new_model

            return True, {
                "strategy": "model_switching",
                "from_model": current_profile,
                "to_model": target_profile["name"],
            }
        except Exception as exc:
            logger.error("Model switching failed: %s", exc)
            return False, None

    def _simplify_task_and_retry(
        self,
        error: Exception,
        context: ErrorRecoveryContext,
    ) -> tuple[bool, Any]:
        logger.info(
            "Strategy: simplify_task_and_retry - breaking down task: %s",
            context.original_task,
        )

        simplified_task = (
            f"Break the following task into smaller steps and execute one step at a time: "
            f"{context.original_task}"
        )

        logger.info("Simplified task: %s", simplified_task)

        return True, {
            "strategy": "task_simplification",
            "simplified_task": simplified_task,
            "original_task": context.original_task,
        }

    def _delegate_to_specialized_agent(
        self,
        error: Exception,
        context: ErrorRecoveryContext,
    ) -> tuple[bool, Any]:
        logger.info(
            "Strategy: delegate_to_specialized_agent - delegating task: %s",
            context.original_task,
        )

        if not hasattr(self, "_build_sub_agent") or not callable(self._build_sub_agent):
            logger.warning("No _build_sub_agent method available; cannot delegate.")
            return False, None

        delegation_role = "recon"
        delegation_groups = ["http", "browser", "knowledge"]

        logger.info(
            "Delegating to sub-agent role='%s' with tool_groups=%s",
            delegation_role,
            delegation_groups,
        )

        return True, {
            "strategy": "delegation",
            "delegated_role": delegation_role,
            "delegated_task": context.original_task,
        }

    def _fallback_to_plan_mode(
        self,
        error: Exception,
        context: ErrorRecoveryContext,
    ) -> tuple[bool, Any]:
        logger.info(
            "Strategy: fallback_to_plan_mode - reassessing task: %s",
            context.original_task,
        )

        plan_prompt = (
            f"The following task encountered an error: {context.error}\n\n"
            f"Original task: {context.original_task}\n\n"
            f"Please reassess the situation and create a new plan to accomplish "
            f"the goal, considering the error that occurred."
        )

        logger.info("Plan mode fallback prompt generated.")

        return True, {
            "strategy": "plan_mode_fallback",
            "plan_prompt": plan_prompt,
            "original_task": context.original_task,
        }

    def get_recovery_stats(self) -> dict[str, Any]:
        return self.error_recovery_stats.to_dict()

    def reset_recovery_stats(self) -> None:
        self.error_recovery_stats = ErrorRecoveryStats()


__all__ = [
    "ErrorHealingConfig",
    "ErrorRecoveryContext",
    "ErrorRecoveryStats",
    "ErrorHealingMixin",
]
