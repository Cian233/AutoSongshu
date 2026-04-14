from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import agentscope
from agentscope.agent import ReActAgent
from agentscope.model import OpenAIChatModel
from agentscope.tool import Toolkit

from ..config import AppConfig
from ..model_router import (
    ModelRouter,
    TaskType,
    parse_profiles_from_config,
)
from ..runtime import PentestRuntime
from ..tools import register_default_tools
from .builder import _AgentBuilderMixin
from .formatter import SafeOpenAIChatFormatter
from .utils import _make_agentscope_output_safe

logger = logging.getLogger(__name__)


class SubAgentRole(str, Enum):
    RECON = "recon"
    SCANNER = "scanner"
    EXPLOIT = "exploit"
    REPORT = "report"


@dataclass
class SubAgentProfile:
    role: SubAgentRole
    display_name: str
    system_prompt: str
    tool_group_names: list[str]
    recommended_model_profile: str = ""
    temperature: float = 1.0


@dataclass
class SubAgentConfig:
    role: SubAgentRole
    model_profile: str = ""
    tool_groups: list[str] = field(default_factory=list)
    system_prompt_template: str = ""


_GROUP_NAME_MAP: dict[str, list[str]] = {
    "http": ["http-analysis"],
    "browser": [
        "browser-basic",
        "browser-interact",
        "browser-inspect",
        "browser-network",
        "browser-advanced",
    ],
    "knowledge": ["knowledge-rag"],
    "sandbox": ["python-sandbox"],
    "skill-scripts": ["skill-scripts"],
    "findings": ["findings"],
}


def _resolve_tool_groups(group_names: list[str]) -> list[str]:
    resolved: list[str] = []
    for name in group_names:
        mapped = _GROUP_NAME_MAP.get(name, [name])
        for g in mapped:
            if g not in resolved:
                resolved.append(g)
    return resolved


_RECON_SYSTEM_PROMPT = """你是 AutoSongshu 的侦察专家（Recon Agent）。你的职责是收集目标信息。

职责范围：
- 使用 HTTP 工具探测目标端点、API 接口、响应头和技术栈
- 使用浏览器工具进行页面导航、截图、DOM 结构分析
- 使用知识检索工具查询已知漏洞模式和安全经验

工作原则：
- 被动侦察优先：先观察再交互
- 记录所有发现：URL、参数、技术栈、潜在入口点
- 不要尝试漏洞利用或漏洞扫描——那是其他 Agent 的职责
- 输出结构化的侦察结果，为后续 Agent 提供情报

语言：所有叙述性输出使用简体中文，技术标识符保持原文。""".strip()

_SCANNER_SYSTEM_PROMPT = """你是 AutoSongshu 的扫描专家（Scanner Agent）。你的职责是发现潜在漏洞。

职责范围：
- 使用沙箱工具运行扫描脚本（端口扫描、目录枚举等）
- 使用技能脚本执行预定义的扫描工作流
- 使用发现工具记录和整理扫描结果

工作原则：
- 系统化扫描：覆盖所有已知的入口点
- 低影响优先：避免对目标造成干扰
- 每个潜在问题都要通过 `record_finding` 记录
- 不要尝试漏洞利用——那是 Exploit Agent 的职责
- 输出结构化的扫描结果，包含严重程度评级

语言：所有叙述性输出使用简体中文，技术标识符保持原文。""".strip()

_EXPLOIT_SYSTEM_PROMPT = """你是 AutoSongshu 的漏洞利用专家（Exploit Agent）。你的职责是验证和利用已发现的漏洞。

职责范围：
- 使用沙箱工具生成和测试漏洞利用 payload
- 使用技能脚本执行预定义的利用工作流
- 使用发现工具更新漏洞验证状态
- 使用 HTTP 工具发送精心构造的请求进行验证

工作原则：
- 证据优先：每个利用尝试都要有明确的证据
- 最小化影响：使用 PoC 级别的验证，不要造成实际损害
- 绝不夸大影响：如实报告利用结果
- 严格在授权范围内操作
- 记录完整的利用链：触发条件 → payload → 响应 → 影响

语言：所有叙述性输出使用简体中文，技术标识符保持原文。""".strip()

_REPORT_SYSTEM_PROMPT = """你是 AutoSongshu 的报告专家（Report Agent）。你的职责是整理和输出安全评估报告。

职责范围：
- 使用发现工具检索所有已记录的漏洞发现
- 使用知识检索工具查询修复建议和最佳实践
- 生成结构化的安全评估报告

工作原则：
- 基于证据：所有结论都要有工具输出的直接证据
- 结构清晰：按严重程度排序，每个发现包含标题、描述、证据、影响、修复建议
- 简洁专业：避免冗余，使用专业的安全术语
- 不要执行新的扫描或利用——只整理已有发现

语言：所有叙述性输出使用简体中文，技术标识符保持原文。""".strip()


_ROLE_PROFILES: dict[SubAgentRole, SubAgentProfile] = {
    SubAgentRole.RECON: SubAgentProfile(
        role=SubAgentRole.RECON,
        display_name="ReconAgent",
        system_prompt=_RECON_SYSTEM_PROMPT,
        tool_group_names=["http", "browser", "knowledge"],
        recommended_model_profile="",
    ),
    SubAgentRole.SCANNER: SubAgentProfile(
        role=SubAgentRole.SCANNER,
        display_name="ScannerAgent",
        system_prompt=_SCANNER_SYSTEM_PROMPT,
        tool_group_names=["sandbox", "skill-scripts", "findings"],
        recommended_model_profile="",
    ),
    SubAgentRole.EXPLOIT: SubAgentProfile(
        role=SubAgentRole.EXPLOIT,
        display_name="ExploitAgent",
        system_prompt=_EXPLOIT_SYSTEM_PROMPT,
        tool_group_names=["sandbox", "skill-scripts", "findings", "http"],
        recommended_model_profile="",
    ),
    SubAgentRole.REPORT: SubAgentProfile(
        role=SubAgentRole.REPORT,
        display_name="ReportAgent",
        system_prompt=_REPORT_SYSTEM_PROMPT,
        tool_group_names=["findings", "knowledge"],
        recommended_model_profile="",
    ),
}


def get_role_profile(role: SubAgentRole) -> SubAgentProfile:
    return _ROLE_PROFILES[role]


class BaseSubAgent(_AgentBuilderMixin):
    config: AppConfig
    runtime: PentestRuntime
    _model_router: ModelRouter | None = None

    def __init__(
        self,
        config: AppConfig,
        runtime: PentestRuntime,
        sub_config: SubAgentConfig,
    ) -> None:
        self.config = config
        self.runtime = runtime
        self.sub_config = sub_config

    def _resolve_tool_groups(self) -> list[str]:
        if self.sub_config.tool_groups:
            return _resolve_tool_groups(self.sub_config.tool_groups)
        profile = get_role_profile(self.sub_config.role)
        return _resolve_tool_groups(profile.tool_group_names)

    def _build_system_prompt(self) -> str:
        if self.sub_config.system_prompt_template:
            return self.sub_config.system_prompt_template
        profile = get_role_profile(self.sub_config.role)
        return profile.system_prompt

    def _build_toolkit(self) -> Toolkit:
        toolkit = Toolkit()
        register_default_tools(
            toolkit, self.runtime, permission_interceptor=None
        )

        active_groups = set(self._resolve_tool_groups())
        all_groups = toolkit.groups if hasattr(toolkit, "groups") else {}

        for group_name in all_groups:
            if group_name not in active_groups:
                try:
                    toolkit.remove_tool_group(group_name)
                except Exception:
                    logger.debug(
                        "Could not remove tool group '%s' (may not be supported).",
                        group_name,
                    )

        return toolkit

    def _build_model(self) -> OpenAIChatModel:
        model_profile_name = (
            self.sub_config.model_profile
            or get_role_profile(self.sub_config.role).recommended_model_profile
        )

        if model_profile_name:
            profile = self.model_router.get_profile(model_profile_name)
            if profile:
                return self.model_router.build_model(profile, stream=True)

        return self._build_model_config(stream=True)

    def build(self) -> ReActAgent:
        agentscope.init(
            project="autosongshu-sub-agent",
            name=f"{self.sub_config.role.value}-agent",
            logging_path=str(self.runtime.artifacts.session_dir / "agentscope"),
            logging_level="INFO",
        )

        toolkit = self._build_toolkit()
        model = self._build_model()
        formatter = SafeOpenAIChatFormatter()
        sys_prompt = self._build_system_prompt()

        agent = _make_agentscope_output_safe(
            ReActAgent(
                name=f"{self.sub_config.role.value}-agent",
                sys_prompt=sys_prompt,
                model=model,
                formatter=formatter,
                toolkit=toolkit,
                max_iters=self.config.agent.max_iters,
                enable_meta_tool=self.config.agent.enable_meta_tool,
                parallel_tool_calls=self.config.agent.parallel_tool_calls,
                print_hint_msg=False,
            ),
        )

        logger.info(
            "Sub-agent '%s' built with role=%s, tool_groups=%s",
            agent.name,
            self.sub_config.role.value,
            self._resolve_tool_groups(),
        )

        return agent


def create_recon_agent(
    config: AppConfig,
    runtime: PentestRuntime,
    *,
    model_profile: str = "",
    system_prompt_template: str = "",
) -> BaseSubAgent:
    sub_config = SubAgentConfig(
        role=SubAgentRole.RECON,
        model_profile=model_profile,
        tool_groups=["http", "browser", "knowledge"],
        system_prompt_template=system_prompt_template,
    )
    return BaseSubAgent(config, runtime, sub_config)


def create_scanner_agent(
    config: AppConfig,
    runtime: PentestRuntime,
    *,
    model_profile: str = "",
    system_prompt_template: str = "",
) -> BaseSubAgent:
    sub_config = SubAgentConfig(
        role=SubAgentRole.SCANNER,
        model_profile=model_profile,
        tool_groups=["sandbox", "skill-scripts", "findings"],
        system_prompt_template=system_prompt_template,
    )
    return BaseSubAgent(config, runtime, sub_config)


def create_exploit_agent(
    config: AppConfig,
    runtime: PentestRuntime,
    *,
    model_profile: str = "",
    system_prompt_template: str = "",
) -> BaseSubAgent:
    sub_config = SubAgentConfig(
        role=SubAgentRole.EXPLOIT,
        model_profile=model_profile,
        tool_groups=["sandbox", "skill-scripts", "findings", "http"],
        system_prompt_template=system_prompt_template,
    )
    return BaseSubAgent(config, runtime, sub_config)


def create_report_agent(
    config: AppConfig,
    runtime: PentestRuntime,
    *,
    model_profile: str = "",
    system_prompt_template: str = "",
) -> BaseSubAgent:
    sub_config = SubAgentConfig(
        role=SubAgentRole.REPORT,
        model_profile=model_profile,
        tool_groups=["findings", "knowledge"],
        system_prompt_template=system_prompt_template,
    )
    return BaseSubAgent(config, runtime, sub_config)


__all__ = [
    "SubAgentRole",
    "SubAgentConfig",
    "SubAgentProfile",
    "BaseSubAgent",
    "get_role_profile",
    "create_recon_agent",
    "create_scanner_agent",
    "create_exploit_agent",
    "create_report_agent",
]
