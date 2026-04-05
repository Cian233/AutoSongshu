from __future__ import annotations

from typing import Any

import agentscope
from agentscope.agent import ReActAgent
from agentscope.model import OpenAIChatModel
from agentscope.plan import PlanNotebook
from agentscope.tool import Toolkit

from ..config import AppConfig
from .formatter import SafeOpenAIChatFormatter
from ..prompts import build_system_prompt
from ..runtime import PentestRuntime
from ..skills import SkillLoadReport, SkillRegistry, SkillRuntimeContext
from ..tools import register_default_tools
from .utils import _make_agentscope_output_safe


class _AgentBuilderMixin:
    config: AppConfig
    runtime: PentestRuntime
    skill_report: SkillLoadReport
    permission_interceptor: Any = None

    def _build_model(self) -> OpenAIChatModel:
        api_key = self.config.model.api_key
        if not api_key and self.config.model.base_url:
            api_key = "EMPTY"
        if not api_key and not self.config.model.base_url:
            raise ValueError(
                "Missing model credentials. Set AUTOSONGSHU_MODEL_API_KEY/model.api_key, "
                "or provide model.base_url for an OpenAI-compatible endpoint.",
            )

        client_kwargs: dict[str, Any] = {"timeout": self.config.model.timeout}
        if self.config.model.base_url:
            client_kwargs["base_url"] = self.config.model.base_url

        generate_kwargs: dict[str, Any] = {
            "temperature": self.config.model.temperature,
            "top_p": self.config.model.top_p,
        }
        if self.config.model.max_tokens is not None:
            generate_kwargs["max_tokens"] = self.config.model.max_tokens

        return OpenAIChatModel(
            model_name=self.config.model.model_name,
            api_key=api_key,
            stream=self.config.model.stream,
            client_kwargs=client_kwargs,
            generate_kwargs=generate_kwargs,
        )

    def _build_memory_model(self) -> OpenAIChatModel:
        api_key = self.config.model.api_key
        if not api_key and self.config.model.base_url:
            api_key = "EMPTY"
        if not api_key and not self.config.model.base_url:
            raise ValueError(
                "Missing model credentials. Set AUTOSONGSHU_MODEL_API_KEY/model.api_key, "
                "or provide model.base_url for an OpenAI-compatible endpoint.",
            )

        client_kwargs: dict[str, Any] = {"timeout": self.config.model.timeout}
        if self.config.model.base_url:
            client_kwargs["base_url"] = self.config.model.base_url

        generate_kwargs: dict[str, Any] = {
            "temperature": min(float(self.config.model.temperature), 0.2),
            "top_p": self.config.model.top_p,
        }
        if self.config.model.max_tokens is not None:
            generate_kwargs["max_tokens"] = self.config.model.max_tokens

        return OpenAIChatModel(
            model_name=self.config.model.model_name,
            api_key=api_key,
            stream=False,
            client_kwargs=client_kwargs,
            generate_kwargs=generate_kwargs,
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
        model = self._build_model()
        formatter = SafeOpenAIChatFormatter()
        sys_prompt = build_system_prompt(self.config)
        if skill_prompt:
            sys_prompt = f"{sys_prompt}\n\n{skill_prompt}"

        return _make_agentscope_output_safe(
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


__all__ = ["_AgentBuilderMixin"]
