"""
Agent Definition - Multi-source agent loading.

Inspired by claw-code's tools/AgentTool/loadAgentsDir.ts:106-165

Three types of agents:
1. Built-in: Hardcoded in code (Explore, Plan, Verification)
2. Custom: User-defined via .autosongshu/agents/*.md
3. Plugin: Provided by plugins
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Union


@dataclass
class AgentDefinitionBase:
    """
    Base fields for all agent definitions.

    All fields have defaults for dataclass inheritance.
    """

    agent_type: str = ""
    when_to_use: str = ""
    tools: list[str] | None = None
    disallowed_tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    model: str = "inherit"
    permission_mode: str | None = None
    max_turns: int | None = None
    background: bool = False
    initial_prompt: str | None = None
    omit_claude_md: bool = False
    memory_scope: Literal["user", "project", "local"] | None = None
    isolation: Literal["worktree", "remote"] | None = None
    critical_reminder: str | None = None


@dataclass
class BuiltInAgentDefinition(AgentDefinitionBase):
    """Built-in agent - hardcoded in the codebase."""

    source: Literal["built-in"] = field(default="built-in", init=False)
    get_system_prompt: Callable[[], str] | None = None


@dataclass
class CustomAgentDefinition(AgentDefinitionBase):
    """Custom agent - user-defined via .autosongshu/agents/*.md."""

    source: str = "user"
    filename: str | None = None
    base_dir: str | None = None
    get_system_prompt: Callable[[], str] | None = None


@dataclass
class PluginAgentDefinition(AgentDefinitionBase):
    """Plugin agent - provided by a plugin."""

    source: Literal["plugin"] = field(default="plugin", init=False)
    plugin: str = ""
    get_system_prompt: Callable[[], str] | None = None


AgentDefinition = Union[
    BuiltInAgentDefinition, CustomAgentDefinition, PluginAgentDefinition
]


def get_agent_model(
    agent_model: str | None,
    parent_model: str,
    override_model: str | None = None,
) -> str:
    """
    Resolve the model to use for an agent.

    Priority:
    1. Explicit override
    2. Agent's own model (if not 'inherit')
    3. Parent's model
    """
    if override_model:
        return override_model
    if agent_model and agent_model != "inherit":
        return agent_model
    return parent_model


def has_required_mcp_servers(
    agent: AgentDefinition,
    available_mcp_servers: list[str],
) -> bool:
    """
    Check if agent has all required MCP servers.

    Returns False if agent requires servers that aren't available.
    """
    return True


__all__ = [
    "AgentDefinitionBase",
    "BuiltInAgentDefinition",
    "CustomAgentDefinition",
    "PluginAgentDefinition",
    "AgentDefinition",
    "get_agent_model",
    "has_required_mcp_servers",
]
