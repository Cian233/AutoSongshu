from __future__ import annotations

import logging
from typing import Any

import agentscope
from agentscope.agent import ReActAgent
from agentscope.model import OpenAIChatModel
from agentscope.plan import PlanNotebook
from agentscope.tool import Toolkit

from ..config import AppConfig
from ..model_router import (
    ModelRouter,
    TaskType,
    parse_profiles_from_config,
)
from .formatter import SafeOpenAIChatFormatter
from .prompts import build_system_prompt
from ..runtime import PentestRuntime
from ..skills import SkillLoadReport, SkillRegistry, SkillRuntimeContext
from ..tools import register_default_tools
from .utils import _make_agentscope_output_safe

logger = logging.getLogger(__name__)

# HTTP status codes that should trigger a fallback to the next model.
_FALLBACK_STATUS_CODES = frozenset({429, 500, 502, 503})


class FallbackModelWrapper:
    """Wraps an :class:`OpenAIChatModel` with automatic fallback support.

    When the primary model (or a fallback) raises an exception whose HTTP
    status code is in :data:`_FALLBACK_STATUS_CODES`, the wrapper
    transparently retries the call with the next model in the chain.

    The wrapper delegates all attribute access to the *current* primary
    model so that AgentScope internals (e.g. ``model.model_name``,
    ``model.stream``) continue to work unchanged.
    """

    def __init__(
        self,
        primary: OpenAIChatModel,
        fallbacks: list[OpenAIChatModel],
    ) -> None:
        self._primary = primary
        self._fallbacks = fallbacks
        self._all_models = [primary, *fallbacks]

    # -- proxy attributes to the primary model -----------------------------

    def __getattr__(self, name: str) -> Any:
        return getattr(self._primary, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._primary, name, value)

    @property
    def model_name(self) -> str:  # type: ignore[override]
        return self._primary.model_name  # type: ignore[attr-defined]

    @model_name.setter
    def model_name(self, value: str) -> None:
        self._primary.model_name = value  # type: ignore[attr-defined]

    # -- core call with fallback -------------------------------------------

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        last_exc: Exception | None = None

        for idx, model in enumerate(self._all_models):
            try:
                return model(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                status_code = _extract_status_code(exc)
                if status_code is None or status_code not in _FALLBACK_STATUS_CODES:
                    # Not a retryable error -- re-raise immediately.
                    raise

                is_primary = idx == 0
                label = "primary" if is_primary else f"fallback#{idx}"
                next_model = (
                    self._all_models[idx + 1]
                    if idx + 1 < len(self._all_models)
                    else None
                )

                if next_model is not None:
                    logger.warning(
                        "Model call failed with HTTP %s on %s model '%s'. "
                        "Falling back to '%s'. Error: %s",
                        status_code,
                        label,
                        getattr(model, "model_name", "<unknown>"),
                        getattr(next_model, "model_name", "<unknown>"),
                        exc,
                    )
                else:
                    logger.error(
                        "Model call failed with HTTP %s on %s model '%s'. "
                        "No more fallback models available. Error: %s",
                        status_code,
                        label,
                        getattr(model, "model_name", "<unknown>"),
                        exc,
                    )

        # All models exhausted -- raise the last exception.
        raise last_exc  # type: ignore[misc]

    def __repr__(self) -> str:
        names = [getattr(m, "model_name", "?") for m in self._all_models]
        return f"FallbackModelWrapper(primary={names[0]}, fallbacks={names[1:]})"


def _extract_status_code(exc: Exception) -> int | None:
    """Try to extract an HTTP status code from common exception types."""
    # openai.APIStatusError / openai.BadRequestError etc.
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    # httpx.HTTPStatusError
    response = getattr(exc, "response", None)
    if response is not None:
        sc = getattr(response, "status_code", None)
        if isinstance(sc, int):
            return sc
    return None


class _AgentBuilderMixin:
    config: AppConfig
    runtime: PentestRuntime
    skill_report: SkillLoadReport
    permission_interceptor: Any = None
    _model_router: ModelRouter | None = None

    @property
    def model_router(self) -> ModelRouter:
        """Lazy-initialize and return the ModelRouter."""
        if self._model_router is None:
            profiles = parse_profiles_from_config(self.config.model)
            self._model_router = ModelRouter(
                profiles=profiles,
                default_profile_name=getattr(self.config.model, "active", None),
            )
        return self._model_router

    def _build_model_config(
        self,
        *,
        model_name: str | None = None,
        temperature: float | None = None,
        stream: bool = True,
    ) -> OpenAIChatModel:
        """Build an OpenAIChatModel with the given overrides.

        When multi-model profiles are configured, uses the active profile
        as the base and applies overrides on top.

        Args:
            model_name: Override the configured model name.
            temperature: Override the configured temperature.
            stream: Whether to enable streaming responses.
        """
        router = self.model_router

        # If multi-profile is configured and no explicit model_name override,
        # use the router to build the model
        if len(router._profiles) > 1 or (len(router._profiles) == 1
                                           and list(router._profiles)[0] != "default"):
            overrides: dict[str, Any] = {"stream": stream}
            if temperature is not None:
                overrides["temperature"] = temperature
            if model_name:
                # Explicit model_name override: find matching profile or build directly
                profile = router.get_profile(model_name)
                if profile:
                    return router.build_model(profile, **overrides)
                # Fall through to legacy path
            return router.build_model_for_task(TaskType.REASONING, **overrides)

        # Legacy single-model path
        effective_name = model_name or self.config.model.model_name
        api_key = self.config.model.api_key
        if not api_key and self.config.model.base_url:
            api_key = "EMPTY"
            logger.warning(
                "No API key configured; using placeholder for base_url endpoint."
            )
        if not api_key and not self.config.model.base_url:
            raise ValueError(
                "Missing model credentials. Set AUTOSONGSHU_MODEL_API_KEY/model.api_key, "
                "or provide model.base_url for an OpenAI-compatible endpoint.",
            )

        effective_temp = (
            temperature if temperature is not None else self.config.model.temperature
        )

        client_kwargs: dict[str, Any] = {"timeout": self.config.model.timeout}
        if self.config.model.base_url:
            client_kwargs["base_url"] = self.config.model.base_url

        generate_kwargs: dict[str, Any] = {
            "temperature": effective_temp,
            "top_p": self.config.model.top_p,
        }
        if self.config.model.max_tokens is not None:
            generate_kwargs["max_tokens"] = self.config.model.max_tokens

        return OpenAIChatModel(
            model_name=effective_name,
            api_key=api_key,
            stream=stream,
            client_kwargs=client_kwargs,
            generate_kwargs=generate_kwargs,
        )

    def _build_model(self) -> OpenAIChatModel | FallbackModelWrapper:
        """Build the primary model, wrapped with fallback support if configured."""
        primary = self._build_model_config()

        fallback_names = self.config.model.fallbacks
        if not fallback_names:
            return primary

        fallback_models: list[OpenAIChatModel] = []
        for fb_name in fallback_names:
            fb_name = str(fb_name).strip()
            if not fb_name:
                continue
            try:
                fb_model = self._build_model_config(model_name=fb_name)
                fallback_models.append(fb_model)
                logger.info(
                    "Fallback model '%s' configured successfully.", fb_name
                )
            except Exception as exc:
                logger.warning(
                    "Failed to initialize fallback model '%s': %s. "
                    "This fallback will be skipped.",
                    fb_name,
                    exc,
                )

        if not fallback_models:
            logger.warning(
                "No fallback models could be initialized. "
                "Proceeding with primary model only."
            )
            return primary

        logger.info(
            "Model fallback chain enabled: primary='%s', fallbacks=[%s]",
            self.config.model.model_name,
            ", ".join(getattr(m, "model_name", "?") for m in fallback_models),
        )
        return FallbackModelWrapper(primary=primary, fallbacks=fallback_models)

    def _build_memory_model(self) -> OpenAIChatModel:
        return self._build_model_config(
            temperature=min(float(self.config.model.temperature), 0.2),
            stream=False,
        )

    def _build_agent(self) -> ReActAgent:
        agentscope.init(
            project="autosongshu-agent",
            name=self.config.engagement.name,
            logging_path=str(self.runtime.artifacts.session_dir / "agentscope"),
            logging_level="INFO",
        )

        toolkit = Toolkit()
        register_default_tools(
            toolkit, self.runtime, permission_interceptor=self.permission_interceptor
        )
        skill_report = SkillLoadReport(
            configured_directories=list(self.config.skills.directories)
        )
        skill_prompt: str | None = None

        if self.config.skills.enabled and self.config.skills.directories:
            skill_registry = SkillRegistry(
                self.config.skills.directories,
                context=SkillRuntimeContext.from_runtime(toolkit, self.config),
            )
            skill_report = skill_registry.register(toolkit)
            skill_prompt = skill_report.agent_prompt

        self.skill_report = skill_report
        self.runtime.loaded_skills = skill_report.loaded_paths
        self.runtime.skill_scripts.update_skills(
            skill_report.loaded,
            manual_skills=skill_report.manual_available,
        )
        skill_payload = skill_report.as_dict()
        self.runtime.update_session_metadata(
            {
                "skills": skill_payload,
                "skill_scripts": self.runtime.skill_scripts.describe(),
            },
        )

        plan_notebook = PlanNotebook(max_subtasks=self.config.agent.max_subtasks)

        # Override the default plan hint to be less aggressive.
        # AgentScope's DefaultPlanToHint pushes create_plan on every turn;
        # we only want a gentle reminder after several tool calls without a plan.
        _patch_plan_hint(plan_notebook)

        model = self._build_model()
        formatter = SafeOpenAIChatFormatter()
        sys_prompt = build_system_prompt(self.config)
        if skill_prompt:
            sys_prompt = f"{sys_prompt}\n\n{skill_prompt}"

        agent = _make_agentscope_output_safe(
            ReActAgent(
                name="AutoSongshu",
                sys_prompt=sys_prompt,
                model=model,
                formatter=formatter,
                toolkit=toolkit,
                plan_notebook=plan_notebook,
                max_iters=self.config.agent.max_iters,
                enable_meta_tool=self.config.agent.enable_meta_tool,
                parallel_tool_calls=self.config.agent.parallel_tool_calls,
                print_hint_msg=False,
            ),
        )

        return agent


__all__ = ["_AgentBuilderMixin", "FallbackModelWrapper"]


def _patch_plan_hint(plan_notebook: PlanNotebook) -> None:
    """Replace AgentScope's aggressive DefaultPlanToHint with a lazy version.

    The default hint injects a ``create_plan`` reminder on *every* reasoning
    step when no plan exists, which causes the agent to plan even for trivial
    one-shot queries.  Our version only suggests planning after the agent has
    already made several tool calls (signalling a complex, multi-step task).
    """

    def _lazy_get_hint(self, messages: list, **kwargs) -> str:
        # Count user-visible tool calls (ignore plan management tools).
        tool_calls = 0
        plan_tool_names = {
            "create_plan",
            "view_subtasks",
            "revise_current_plan",
            "update_subtask_state",
            "finish_subtask",
            "finish_plan",
            "view_historical_plans",
            "recover_historical_plan",
        }
        for msg in messages:
            if not hasattr(msg, "content"):
                continue
            parts = msg.content if isinstance(msg.content, list) else [msg.content]
            for part in parts:
                if isinstance(part, dict) and part.get("type") == "tool_call":
                    if part.get("name", "") not in plan_tool_names:
                        tool_calls += 1

        # No plan yet and agent has been busy → gentle nudge
        if self.current_plan is None and tool_calls >= 4:
            return (
                "You have made several tool calls without a plan. "
                "If this is a complex multi-step task, consider calling "
                "`create_plan` to organize the remaining work. "
                "For simple tasks, continue as you are."
            )

        # Plan exists → remind to advance subtasks
        if self.current_plan is not None:
            plan = self.current_plan
            if plan.state == "todo":
                return (
                    "A plan exists but has not started. Call "
                    "`update_subtask_state` with subtask_idx=0 and "
                    "state='in_progress' to begin."
                )
            if plan.state == "in_progress":
                # Find first non-done subtask
                for i, st in enumerate(plan.subtasks):
                    if st.state not in ("done", "abandoned"):
                        if st.state == "in_progress":
                            return (
                                f"Subtask {i} ('{st.name}') is in progress. "
                                f"Continue working on it, then call "
                                f"`finish_subtask(subtask_idx={i}, subtask_outcome='...')` "
                                f"when done."
                            )
                        return (
                            f"Subtask {i} ('{st.name}') is next. Call "
                            f"`update_subtask_state(subtask_idx={i}, state='in_progress')` "
                            f"to start it."
                        )

        return ""  # No hint

    # Monkey-patch the instance method
    import types
    plan_notebook._get_hint = types.MethodType(_lazy_get_hint, plan_notebook)
