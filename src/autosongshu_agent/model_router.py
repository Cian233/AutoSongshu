"""Multi-model routing with provider abstraction.

Design goals (inspired by Claude Code / Windsurf / Cursor):
- Define multiple model *profiles* in config, each with its own provider,
  API key, base URL, and generation parameters.
- Route different task types (reasoning, memory, search, …) to different
  profiles.
- Allow runtime switching of the active profile via API / frontend.
- Graceful fallback across providers on transient errors.

All providers go through AgentScope's ``OpenAIChatModel`` (OpenAI-compatible
API), so the abstraction is lightweight — just different credentials + endpoints.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

logger = logging.getLogger(__name__)


# ── Provider types ────────────────────────────────────────────────

class ModelProvider(str, Enum):
    """Supported model providers (all accessed via OpenAI-compatible API)."""
    OPENAI = "openai"
    AZURE = "azure"
    ANTHROPIC = "anthropic"
    DASHSCOPE = "dashscope"
    DEEPSEEK = "deepseek"
    ZHIPU = "zhipu"
    MOONSHOT = "moonshot"
    SILICONFLOW = "siliconflow"
    CUSTOM = "custom"  # Any OpenAI-compatible endpoint


# ── Task types for routing ────────────────────────────────────────

class TaskType(str, Enum):
    """Task categories that can be routed to different models."""
    REASONING = "reasoning"          # Main agent reasoning (default)
    MEMORY = "memory"                # Compaction / summarization
    SEARCH = "search"                # Web search queries
    TOOL_PLANNING = "tool_planning"  # Tool selection / plan creation
    CODE_GEN = "code_gen"            # Sandbox code generation
    KNOWLEDGE = "knowledge"          # Knowledge base queries
    GENERAL = "general"              # Fallback for anything else


class TaskComplexity(str, Enum):
    """Task complexity levels for automatic model routing."""
    SIMPLE = "simple"
    MODERATE = "moderate"
    COMPLEX = "complex"


SIMPLE_INDICATORS = [
    r"\b(read|get|fetch|query|check|status|info|list|show|view)\b",
    r"\b(file|log|config|setting|status|version|detail)\b",
    r"\b(basic|simple|quick|easy|straightforward)\b",
]

MODERATE_INDICATORS = [
    r"\b(generate|create|build|implement|write|develop|produce)\b",
    r"\b(function|method|class|module|component|script)\b",
    r"\b(refactor|modify|update|change|improve|optimize)\b",
    r"\b(single-file|one file|single module)\b",
]

COMPLEX_INDICATORS = [
    r"\b(architecture|design|system|infrastructure|framework)\b",
    r"\b(vulnerability|exploit|attack|penetration|security)\b",
    r"\b(chain|workflow|pipeline|orchestration|integration)\b",
    r"\b(multi-file|multiple files|cross-module|end-to-end|e2e)\b",
    r"\b(analysis|investigation|assessment|audit|review)\b",
]


class TaskComplexityAnalyzer:
    """Analyzes task descriptions to determine complexity level."""

    def __init__(
        self,
        simple_indicators: list[str] | None = None,
        moderate_indicators: list[str] | None = None,
        complex_indicators: list[str] | None = None,
    ) -> None:
        self._simple_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in (simple_indicators or SIMPLE_INDICATORS)
        ]
        self._moderate_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in (moderate_indicators or MODERATE_INDICATORS)
        ]
        self._complex_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in (complex_indicators or COMPLEX_INDICATORS)
        ]

    def analyze(self, task_description: str) -> TaskComplexity:
        """Analyze task description for complexity indicators.

        Scoring:
        - Each complex indicator match: +3 points
        - Each moderate indicator match: +2 points
        - Each simple indicator match: +1 point

        Thresholds:
        - 0-2 points: SIMPLE
        - 3-5 points: MODERATE
        - 6+ points: COMPLEX
        """
        if not task_description or not task_description.strip():
            return TaskComplexity.SIMPLE

        score = 0

        for pattern in self._complex_patterns:
            score += len(pattern.findall(task_description)) * 3

        for pattern in self._moderate_patterns:
            score += len(pattern.findall(task_description)) * 2

        for pattern in self._simple_patterns:
            score += len(pattern.findall(task_description)) * 1

        if score >= 6:
            return TaskComplexity.COMPLEX
        if score >= 3:
            return TaskComplexity.MODERATE
        return TaskComplexity.SIMPLE


# ── Model profile ─────────────────────────────────────────────────

@dataclass
class ModelProfile:
    """A single model configuration with its own credentials and params."""

    name: str  # Unique identifier, e.g. "qwen-plus", "gpt-4o"
    display_name: str = ""  # Human-readable name for UI
    provider: ModelProvider = ModelProvider.CUSTOM
    model_name: str = ""  # Actual model ID sent to the API
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 1.0
    top_p: float = 0.95
    max_tokens: int | None = None
    timeout: float = 120.0
    stream: bool = True

    # Cost / performance hints for routing
    cost_per_1m_input: float = 0.0   # USD per 1M input tokens
    cost_per_1m_output: float = 0.0  # USD per 1M output tokens
    latency_ms: int = 0              # Expected latency in ms (0 = unknown)

    # Which task types this profile is suitable for
    tasks: list[TaskType] = field(default_factory=lambda: [TaskType.GENERAL])

    # Is this profile enabled?
    enabled: bool = True

    # Per-profile compaction overrides (None = use global defaults)
    compaction: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.display_name:
            self.display_name = self.name
        if not self.model_name:
            self.model_name = self.name

    def to_openai_kwargs(self) -> dict[str, Any]:
        """Build kwargs for ``OpenAIChatModel``."""
        api_key = self.api_key
        if not api_key and self.base_url:
            api_key = "EMPTY"

        client_kwargs: dict[str, Any] = {"timeout": self.timeout}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url

        generate_kwargs: dict[str, Any] = {
            "temperature": self.temperature,
            "top_p": self.top_p,
        }
        if self.max_tokens is not None:
            generate_kwargs["max_tokens"] = self.max_tokens

        return {
            "model_name": self.model_name,
            "api_key": api_key,
            "stream": self.stream,
            "client_kwargs": client_kwargs,
            "generate_kwargs": generate_kwargs,
        }

    def to_dict(self) -> dict[str, Any]:
        d = {
            "name": self.name,
            "display_name": self.display_name,
            "provider": self.provider.value,
            "model_name": self.model_name,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "tasks": [t.value for t in self.tasks],
            "enabled": self.enabled,
            "cost_per_1m_input": self.cost_per_1m_input,
            "cost_per_1m_output": self.cost_per_1m_output,
        }
        if self.compaction:
            d["compaction"] = self.compaction
        return d


# ── Model router ──────────────────────────────────────────────────

@dataclass
class _ModelErrorStats:
    """Tracks error statistics for a single model."""
    success_count: int = 0
    failure_count: int = 0

    @property
    def total_count(self) -> int:
        return self.success_count + self.failure_count

    @property
    def error_rate(self) -> float:
        if self.total_count == 0:
            return 0.0
        return self.failure_count / self.total_count


class ErrorRateTracker:
    """Tracks error rates per model and triggers automatic degradation."""

    def __init__(
        self,
        degradation_threshold: float = 0.5,
        min_samples: int = 3,
    ) -> None:
        self._degradation_threshold = degradation_threshold
        self._min_samples = min_samples
        self._stats: dict[str, _ModelErrorStats] = {}

    def record_result(self, model_name: str, success: bool) -> None:
        """Record a success or failure for a model."""
        if model_name not in self._stats:
            self._stats[model_name] = _ModelErrorStats()

        stats = self._stats[model_name]
        if success:
            stats.success_count += 1
        else:
            stats.failure_count += 1

        logger.debug(
            "ErrorRateTracker: model='%s' success=%s, stats: %d/%d (error_rate=%.2f)",
            model_name, success, stats.failure_count, stats.total_count, stats.error_rate,
        )

    def should_degrade(self, model_name: str) -> bool:
        """Check if a model's error rate exceeds the degradation threshold."""
        stats = self._stats.get(model_name)
        if stats is None:
            return False
        if stats.total_count < self._min_samples:
            return False
        return stats.error_rate >= self._degradation_threshold

    def get_degraded_model(self, current_model: str) -> str | None:
        """Get a fallback model if the current model should be degraded.

        Returns None if degradation is not needed or no fallback is available.
        """
        if not self.should_degrade(current_model):
            return None

        for model_name, stats in self._stats.items():
            if model_name == current_model:
                continue
            if not self.should_degrade(model_name):
                logger.warning(
                    "Degrading from '%s' to '%s' due to high error rate (%.2f%%)",
                    current_model, model_name,
                    self._stats[current_model].error_rate * 100,
                )
                return model_name

        logger.warning(
            "All models have high error rates, cannot degrade from '%s'",
            current_model,
        )
        return None

    def get_error_rate(self, model_name: str) -> float:
        """Get the current error rate for a model."""
        stats = self._stats.get(model_name)
        if stats is None:
            return 0.0
        return stats.error_rate


class ModelRouter:
    """Routes task types to appropriate model profiles.

    Usage::

        router = ModelRouter(profiles=[...])
        profile = router.resolve(TaskType.REASONING)
        model = router.build_model(profile)
    """

    COMPLEXITY_MODEL_MAP: dict[TaskComplexity, str] = {
        TaskComplexity.SIMPLE: "gpt-4o-mini",
        TaskComplexity.MODERATE: "gpt-4o",
        TaskComplexity.COMPLEX: "claude-sonnet",
    }

    def __init__(
        self,
        profiles: list[ModelProfile],
        default_profile_name: str | None = None,
        complexity_model_map: dict[TaskComplexity, str] | None = None,
    ) -> None:
        self._profiles: dict[str, ModelProfile] = {}
        self._task_index: dict[TaskType, list[str]] = {}

        for p in profiles:
            if p.enabled:
                self._profiles[p.name] = p
                for task in p.tasks:
                    self._task_index.setdefault(task, []).append(p.name)

        # Determine default
        if default_profile_name and default_profile_name in self._profiles:
            self._default = default_profile_name
        elif profiles:
            self._default = profiles[0].name
        else:
            self._default = ""

        # Runtime override (set via API)
        self._active_override: str | None = None

        # Task complexity analyzer
        self._complexity_analyzer = TaskComplexityAnalyzer()

        # Complexity to model name mapping
        self._complexity_model_map = complexity_model_map or self.COMPLEXITY_MODEL_MAP

        # Error rate tracker
        self._error_tracker = ErrorRateTracker()

        logger.info(
            "ModelRouter initialized: %d profiles, default='%s', tasks=%s",
            len(self._profiles),
            self._default,
            {t.value: names for t, names in self._task_index.items()},
        )

    # ── Public API ────────────────────────────────────────────────

    @property
    def active_profile_name(self) -> str:
        """The currently active profile (override or default)."""
        if self._active_override and self._active_override in self._profiles:
            return self._active_override
        return self._default

    def set_active(self, profile_name: str) -> bool:
        """Set a runtime override for the active profile."""
        if profile_name not in self._profiles:
            logger.warning("Unknown profile '%s', available: %s", profile_name, list(self._profiles))
            return False
        self._active_override = profile_name
        logger.info("Active model switched to '%s'", profile_name)
        return True

    def clear_override(self) -> None:
        """Clear the runtime override, reverting to default routing."""
        self._active_override = None

    def select_model_for_task(self, task_description: str) -> str:
        """Select the best model for a task based on complexity analysis.

        Uses TaskComplexityAnalyzer to determine task complexity, then maps
        to the appropriate model profile. Also checks error rates and may
        degrade to a fallback model if needed.

        Args:
            task_description: Natural language description of the task.

        Returns:
            The name of the selected model profile.
        """
        complexity = self._complexity_analyzer.analyze(task_description)
        target_model = self._complexity_model_map.get(complexity, self._default)

        logger.info(
            "Task complexity: %s, selected model: %s",
            complexity.value, target_model,
        )

        degraded = self._error_tracker.get_degraded_model(target_model)
        if degraded is not None:
            return degraded

        if target_model in self._profiles:
            return target_model

        logger.warning(
            "Complexity-selected model '%s' not available, using default '%s'",
            target_model, self._default,
        )
        return self._default

    def record_task_result(self, model_name: str, success: bool) -> None:
        """Record the result of a task execution for error rate tracking."""
        self._error_tracker.record_result(model_name, success)

    def get_model_error_rate(self, model_name: str) -> float:
        """Get the current error rate for a model."""
        return self._error_tracker.get_error_rate(model_name)

    def resolve(self, task: TaskType) -> ModelProfile:
        """Resolve a task type to the best model profile.

        Priority:
        1. Runtime override (if set)
        2. Profiles registered for the specific task type
        3. Default profile
        """
        # If override is active, use it for everything
        if self._active_override and self._active_override in self._profiles:
            return self._profiles[self._active_override]

        # Find profiles for this task type
        candidates = self._task_index.get(task, [])
        if candidates:
            # Return the first candidate (could add cost/latency optimization)
            return self._profiles[candidates[0]]

        # Fall back to default
        if self._default and self._default in self._profiles:
            return self._profiles[self._default]

        raise ValueError(
            f"No model profile available for task '{task.value}'. "
            f"Registered profiles: {list(self._profiles)}"
        )

    def get_profile(self, name: str) -> ModelProfile | None:
        """Get a profile by name."""
        return self._profiles.get(name)

    def list_profiles(self) -> list[dict[str, Any]]:
        """Return all profiles for the frontend."""
        active = self.active_profile_name
        result = []
        for name, p in self._profiles.items():
            d = p.to_dict()
            d["is_active"] = name == active
            result.append(d)
        return result

    def build_model(self, profile: ModelProfile | None = None, **overrides: Any):
        """Build an ``OpenAIChatModel`` for the given profile.

        Args:
            profile: The profile to use. If None, uses the active profile.
            **overrides: Override temperature, stream, etc.

        Returns:
            An ``OpenAIChatModel`` instance.
        """
        if profile is None:
            profile = self.resolve(TaskType.REASONING)

        kwargs = profile.to_openai_kwargs()

        # Apply overrides
        if "temperature" in overrides:
            kwargs["generate_kwargs"]["temperature"] = overrides["temperature"]
        if "stream" in overrides:
            kwargs["stream"] = overrides["stream"]

        from agentscope.model import OpenAIChatModel
        return OpenAIChatModel(**kwargs)

    def build_model_for_task(
        self, task: TaskType, **overrides: Any,
    ):
        """Convenience: resolve task → profile → model."""
        profile = self.resolve(task)
        return self.build_model(profile, **overrides)


# ── Config parsing helpers ────────────────────────────────────────

def parse_profiles_from_config(
    model_config: Any,
) -> list[ModelProfile]:
    """Parse model profiles from the YAML / env config.

    Supports two formats:

    **Legacy (single model)**:
        model:
          model_name: gpt-4.1-mini
          api_key: sk-...
          base_url: https://...

    **Multi-profile**:
        model:
          active: qwen-plus
          profiles:
            - name: qwen-plus
              provider: dashscope
              model_name: qwen3.6-plus
              api_key: sk-...
              base_url: https://...
              tasks: [reasoning, general]
            - name: gpt-4o
              provider: openai
              model_name: gpt-4o
              api_key: sk-...
              tasks: [code_gen, search]
    """
    profiles: list[ModelProfile] = []

    # Check for new multi-profile format
    raw_profiles = getattr(model_config, "profiles", None)
    if raw_profiles and isinstance(raw_profiles, list) and len(raw_profiles) > 0:
        for raw in raw_profiles:
            if isinstance(raw, dict):
                profiles.append(_parse_single_profile(raw))
            elif hasattr(raw, "model_name"):  # Pydantic model
                profiles.append(_pydantic_to_profile(raw))
        return profiles

    # Legacy: single model config → one profile named "default"
    profiles.append(_pydantic_to_profile(model_config, default_name="default"))
    return profiles


def _parse_single_profile(raw: dict[str, Any]) -> ModelProfile:
    """Parse a profile from a raw dict (YAML)."""
    provider_str = raw.get("provider", "custom")
    try:
        provider = ModelProvider(provider_str)
    except ValueError:
        provider = ModelProvider.CUSTOM

    task_strs = raw.get("tasks", ["general"])
    tasks = []
    for t in task_strs:
        try:
            tasks.append(TaskType(t))
        except ValueError:
            logger.warning("Unknown task type '%s' in profile '%s'", t, raw.get("name"))

    return ModelProfile(
        name=raw.get("name", "unnamed"),
        display_name=raw.get("display_name", ""),
        provider=provider,
        model_name=raw.get("model_name", raw.get("name", "")),
        api_key=raw.get("api_key"),
        base_url=raw.get("base_url"),
        temperature=float(raw.get("temperature", 1.0)),
        top_p=float(raw.get("top_p", 0.95)),
        max_tokens=raw.get("max_tokens"),
        timeout=float(raw.get("timeout", 120.0)),
        stream=bool(raw.get("stream", True)),
        cost_per_1m_input=float(raw.get("cost_per_1m_input", 0)),
        cost_per_1m_output=float(raw.get("cost_per_1m_output", 0)),
        latency_ms=int(raw.get("latency_ms", 0)),
        tasks=tasks,
        enabled=bool(raw.get("enabled", True)),
        compaction=raw.get("compaction") if isinstance(raw.get("compaction"), dict) else None,
    )


def _pydantic_to_profile(model_config: Any, default_name: str = "default") -> ModelProfile:
    """Convert a legacy ModelConfig (Pydantic) to a ModelProfile."""
    name = getattr(model_config, "model_name", "default")
    return ModelProfile(
        name=default_name,
        display_name=name,
        model_name=name,
        api_key=getattr(model_config, "api_key", None),
        base_url=getattr(model_config, "base_url", None),
        temperature=float(getattr(model_config, "temperature", 1.0)),
        top_p=float(getattr(model_config, "top_p", 0.95)),
        max_tokens=getattr(model_config, "max_tokens", None),
        timeout=float(getattr(model_config, "timeout", 120.0)),
        stream=bool(getattr(model_config, "stream", True)),
    )


__all__ = [
    "ModelProvider",
    "TaskType",
    "TaskComplexity",
    "TaskComplexityAnalyzer",
    "ErrorRateTracker",
    "ModelProfile",
    "ModelRouter",
    "parse_profiles_from_config",
]
