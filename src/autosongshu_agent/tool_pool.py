from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agentscope.tool import Toolkit

from .permissions import ToolPermissionContext
from .runtime import PentestRuntime


class PentestPhase(str, Enum):
    RECON = "recon"
    SCANNING = "scanning"
    EXPLOITATION = "exploitation"
    REPORTING = "reporting"


PHASE_TOOL_GROUPS: dict[str, list[str]] = {
    PentestPhase.RECON: ["http", "browser", "knowledge", "agent"],
    PentestPhase.SCANNING: ["sandbox", "skill-scripts", "findings", "agent"],
    PentestPhase.EXPLOITATION: ["sandbox", "skill-scripts", "findings", "http", "agent"],
    PentestPhase.REPORTING: ["findings", "knowledge", "agent"],
}


def get_tools_for_phase(phase: str) -> list[str]:
    phase_value = phase if isinstance(phase, str) else phase.value
    group_names = PHASE_TOOL_GROUPS.get(phase_value, [])
    enabled: list[str] = []
    for group in DEFAULT_TOOL_GROUPS:
        if group.name in group_names:
            enabled.extend(group.tools)
    return enabled


@dataclass(frozen=True)
class ToolGroupConfig:
    name: str
    description: str
    tools: tuple[str, ...]
    enabled_by_default: bool = True
    requires_approval: bool = False
    risk_level: str = "medium"


DEFAULT_TOOL_GROUPS: tuple[ToolGroupConfig, ...] = (
    ToolGroupConfig(
        name="browser",
        description="Browser automation and CDP tools",
        tools=(
            "browser_navigate",
            "browser_click",
            "browser_type",
            "browser_snapshot",
            "browser_list_forms",
            "browser_list_links",
            "browser_get_html",
            "browser_get_cdp_requests",
            "browser_get_response_bodies",
            "browser_get_network_log",
            "browser_get_console_log",
            "browser_get_cookies",
            "browser_storage_snapshot",
            "browser_analyze_page_resources",
            "browser_wait_for_load_state",
            "browser_wait_for_selector",
            "browser_execute_script",
        ),
        enabled_by_default=True,
        risk_level="low",
    ),
    ToolGroupConfig(
        name="http",
        description="HTTP request tools",
        tools=(
            "http_request",
            "http_get",
            "http_post",
        ),
        enabled_by_default=True,
        risk_level="low",
    ),
    ToolGroupConfig(
        name="sandbox",
        description="Sandbox execution tools (high risk)",
        tools=(
            "sandbox_status",
            "sandbox_install_packages",
            "sandbox_run_python",
            "sandbox_write_file",
            "sandbox_read_file",
            "sandbox_edit_file",
            "sandbox_multiedit_file",
            "sandbox_list_files",
            "sandbox_delete_file",
        ),
        enabled_by_default=True,
        requires_approval=True,
        risk_level="high",
    ),
    ToolGroupConfig(
        name="skill-scripts",
        description="Skill script execution tools",
        tools=(
            "run_skill_script",
            "list_skill_scripts",
        ),
        enabled_by_default=True,
        requires_approval=True,
        risk_level="high",
    ),
    ToolGroupConfig(
        name="findings",
        description="Security findings management",
        tools=(
            "add_finding",
            "list_findings",
            "update_finding",
            "delete_finding",
        ),
        enabled_by_default=True,
        risk_level="low",
    ),
    ToolGroupConfig(
        name="knowledge",
        description="Knowledge base search tools",
        tools=("knowledge_search",),
        enabled_by_default=True,
        risk_level="low",
    ),
    ToolGroupConfig(
        name="agent",
        description="Sub-agent spawning tools for parallel task execution",
        tools=("spawn_agent",),
        enabled_by_default=True,
        requires_approval=True,
        risk_level="high",
    ),
)


@dataclass
class ToolPoolConfig:
    enabled_groups: set[str] = field(default_factory=set)
    disabled_tools: set[str] = field(default_factory=set)
    permission_context: ToolPermissionContext | None = None
    simple_mode: bool = False
    include_skills: bool = True
    include_sandbox: bool = True

    @classmethod
    def default(cls) -> "ToolPoolConfig":
        return cls(
            enabled_groups={group.name for group in DEFAULT_TOOL_GROUPS},
        )

    @classmethod
    def simple(cls) -> "ToolPoolConfig":
        return cls(
            enabled_groups={"browser", "http", "findings", "knowledge"},
            simple_mode=True,
            include_skills=False,
            include_sandbox=False,
        )

    @classmethod
    def readonly(cls) -> "ToolPoolConfig":
        return cls(
            enabled_groups={"browser", "http", "findings", "knowledge"},
            disabled_tools={
                "browser_click",
                "browser_type",
                "browser_execute_script",
                "sandbox_run_python",
                "sandbox_write_file",
                "sandbox_edit_file",
                "run_skill_script",
            },
            include_skills=False,
        )


class ToolPool:
    def __init__(
        self,
        config: ToolPoolConfig | None = None,
        groups: tuple[ToolGroupConfig, ...] | None = None,
    ) -> None:
        self.config = config or ToolPoolConfig.default()
        self.groups = groups or DEFAULT_TOOL_GROUPS
        self._tool_to_group: dict[str, str] = {}
        self._build_tool_mapping()

    def _build_tool_mapping(self) -> None:
        self._tool_to_group.clear()
        for group in self.groups:
            for tool_name in group.tools:
                self._tool_to_group[tool_name] = group.name

    def get_group_for_tool(self, tool_name: str) -> str | None:
        return self._tool_to_group.get(tool_name)

    def is_tool_enabled(self, tool_name: str) -> bool:
        group_name = self._tool_to_group.get(tool_name)
        if group_name is None:
            return False
        if tool_name in self.config.disabled_tools:
            return False
        if group_name not in self.config.enabled_groups:
            return False
        if self.config.simple_mode:
            if group_name in ("sandbox", "skill-scripts"):
                return False
        if not self.config.include_skills and group_name == "skill-scripts":
            return False
        if not self.config.include_sandbox and group_name == "sandbox":
            return False
        return True

    def get_enabled_tools(self) -> list[str]:
        enabled: list[str] = []
        for group in self.groups:
            if group.name not in self.config.enabled_groups:
                continue
            for tool_name in group.tools:
                if self.is_tool_enabled(tool_name):
                    enabled.append(tool_name)
        return enabled

    def get_blocked_tools(self) -> list[str]:
        blocked: list[str] = []
        for group in self.groups:
            for tool_name in group.tools:
                if not self.is_tool_enabled(tool_name):
                    blocked.append(tool_name)
        return blocked

    def enable_group(self, group_name: str) -> None:
        self.config.enabled_groups.add(group_name)

    def disable_group(self, group_name: str) -> None:
        self.config.enabled_groups.discard(group_name)

    def enable_tool(self, tool_name: str) -> None:
        self.config.disabled_tools.discard(tool_name)

    def disable_tool(self, tool_name: str) -> None:
        self.config.disabled_tools.add(tool_name)

    def get_tools_requiring_approval(self) -> list[str]:
        tools: list[str] = []
        for group in self.groups:
            if group.requires_approval and group.name in self.config.enabled_groups:
                tools.extend(group.tools)
        return tools

    def as_summary_dict(self) -> dict[str, Any]:
        enabled = self.get_enabled_tools()
        blocked = self.get_blocked_tools()
        return {
            "enabled_count": len(enabled),
            "blocked_count": len(blocked),
            "enabled_groups": list(self.config.enabled_groups),
            "disabled_tools": list(self.config.disabled_tools),
            "simple_mode": self.config.simple_mode,
            "approval_required": self.get_tools_requiring_approval(),
        }

    def as_markdown(self) -> str:
        lines = [
            "# Tool Pool Configuration",
            "",
            f"- **Mode**: {'Simple' if self.config.simple_mode else 'Full'}",
            f"- **Enabled Groups**: {', '.join(sorted(self.config.enabled_groups))}",
            f"- **Total Tools**: {len(self.get_enabled_tools())}",
            "",
            "## Tool Groups",
        ]
        for group in self.groups:
            status = "✓" if group.name in self.config.enabled_groups else "✗"
            lines.append(
                f"- [{status}] **{group.name}** ({len(group.tools)} tools) - {group.description}"
            )
        return "\n".join(lines)


def build_tool_pool(
    simple_mode: bool = False,
    include_skills: bool = True,
    include_sandbox: bool = True,
    permission_context: ToolPermissionContext | None = None,
    disabled_tools: list[str] | None = None,
) -> ToolPool:
    config = ToolPoolConfig(
        enabled_groups={group.name for group in DEFAULT_TOOL_GROUPS},
        disabled_tools=set(disabled_tools or []),
        permission_context=permission_context,
        simple_mode=simple_mode,
        include_skills=include_skills,
        include_sandbox=include_sandbox,
    )
    return ToolPool(config=config)


def filter_toolkit_by_pool(
    toolkit: Toolkit,
    pool: ToolPool,
) -> list[str]:
    filtered: list[str] = []
    for tool_name in pool.get_enabled_tools():
        if hasattr(toolkit, "has_tool") and toolkit.has_tool(tool_name):
            filtered.append(tool_name)
    return filtered


__all__ = [
    "ToolGroupConfig",
    "ToolPoolConfig",
    "ToolPool",
    "DEFAULT_TOOL_GROUPS",
    "build_tool_pool",
    "filter_toolkit_by_pool",
    "PentestPhase",
    "PHASE_TOOL_GROUPS",
    "get_tools_for_phase",
]
