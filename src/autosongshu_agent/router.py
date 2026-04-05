from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RoutedMatch:
    kind: str
    name: str
    source_hint: str
    score: int
    description: str = ""


@dataclass(frozen=True)
class CommandEntry:
    name: str
    description: str
    handler: str = ""
    aliases: tuple[str, ...] = ()

    def matches_token(self, token: str) -> bool:
        lowered = token.lower()
        if lowered in self.name.lower():
            return True
        if lowered in self.description.lower():
            return True
        for alias in self.aliases:
            if lowered in alias.lower():
                return True
        return False


@dataclass(frozen=True)
class ToolEntry:
    name: str
    description: str
    group: str = ""
    risk_level: str = "medium"

    def matches_token(self, token: str) -> bool:
        lowered = token.lower()
        if lowered in self.name.lower():
            return True
        if lowered in self.description.lower():
            return True
        if lowered in self.group.lower():
            return True
        return False


@dataclass(frozen=True)
class SkillEntry:
    name: str
    description: str
    path: str = ""
    tags: tuple[str, ...] = ()

    def matches_token(self, token: str) -> bool:
        lowered = token.lower()
        if lowered in self.name.lower():
            return True
        if lowered in self.description.lower():
            return True
        for tag in self.tags:
            if lowered in tag.lower():
                return True
        return False


DEFAULT_COMMANDS: tuple[CommandEntry, ...] = (
    CommandEntry(
        name="/help",
        description="Show available commands and usage",
        aliases=("?", "h"),
    ),
    CommandEntry(
        name="/stats",
        description="Show token usage statistics",
        aliases=("usage", "tokens"),
    ),
    CommandEntry(
        name="/clear", description="Clear conversation history", aliases=("reset",)
    ),
    CommandEntry(
        name="/compact", description="Compact session memory", aliases=("summarize",)
    ),
    CommandEntry(name="/pause", description="Pause current task execution"),
    CommandEntry(name="/resume", description="Resume paused task"),
    CommandEntry(name="/status", description="Show current session status"),
    CommandEntry(
        name="/interrupt",
        description="Interrupt current agent turn",
        aliases=("stop", "abort"),
    ),
    CommandEntry(name="/exit", description="Exit the session", aliases=("quit", "q")),
)

DEFAULT_TOOLS: tuple[ToolEntry, ...] = (
    ToolEntry(
        name="http_get",
        description="Perform HTTP GET request",
        group="http",
        risk_level="low",
    ),
    ToolEntry(
        name="http_post",
        description="Perform HTTP POST request",
        group="http",
        risk_level="medium",
    ),
    ToolEntry(
        name="browser_navigate",
        description="Navigate browser to URL",
        group="browser",
        risk_level="low",
    ),
    ToolEntry(
        name="browser_click",
        description="Click element in browser",
        group="browser",
        risk_level="low",
    ),
    ToolEntry(
        name="browser_execute_script",
        description="Execute JavaScript in browser",
        group="browser",
        risk_level="high",
    ),
    ToolEntry(
        name="sandbox_run_python",
        description="Execute Python code in sandbox",
        group="sandbox",
        risk_level="high",
    ),
    ToolEntry(
        name="sandbox_write_file",
        description="Write file to sandbox",
        group="sandbox",
        risk_level="high",
    ),
    ToolEntry(
        name="sandbox_edit_file",
        description="Edit file in sandbox",
        group="sandbox",
        risk_level="high",
    ),
    ToolEntry(
        name="run_skill_script",
        description="Execute skill script",
        group="skills",
        risk_level="high",
    ),
    ToolEntry(
        name="knowledge_search",
        description="Search knowledge bases",
        group="knowledge",
        risk_level="low",
    ),
    ToolEntry(
        name="add_finding",
        description="Record security finding",
        group="findings",
        risk_level="low",
    ),
    ToolEntry(
        name="list_findings",
        description="List recorded findings",
        group="findings",
        risk_level="low",
    ),
)


class PromptRouter:
    def __init__(
        self,
        commands: tuple[CommandEntry, ...] | None = None,
        tools: tuple[ToolEntry, ...] | None = None,
        skills: tuple[SkillEntry, ...] | None = None,
    ) -> None:
        self.commands = commands or DEFAULT_COMMANDS
        self.tools = tools or DEFAULT_TOOLS
        self.skills = skills or ()

    def register_skill(self, skill: SkillEntry) -> None:
        object.__setattr__(self, "skills", self.skills + (skill,))

    def register_command(self, command: CommandEntry) -> None:
        object.__setattr__(self, "commands", self.commands + (command,))

    def register_tool(self, tool: ToolEntry) -> None:
        object.__setattr__(self, "tools", self.tools + (tool,))

    def tokenize_prompt(self, prompt: str) -> set[str]:
        tokens: set[str] = set()
        for raw in prompt.replace("/", " ").replace("-", " ").replace("_", " ").split():
            token = raw.lower().strip()
            if token and len(token) >= 2:
                tokens.add(token)
        return tokens

    def route(self, prompt: str, limit: int = 5) -> list[RoutedMatch]:
        tokens = self.tokenize_prompt(prompt)
        if not tokens:
            return []

        command_matches = self._match_commands(tokens)
        tool_matches = self._match_tools(tokens)
        skill_matches = self._match_skills(tokens)

        by_kind = {
            "command": command_matches,
            "tool": tool_matches,
            "skill": skill_matches,
        }

        selected: list[RoutedMatch] = []
        for kind in ("command", "tool", "skill"):
            if by_kind[kind]:
                selected.append(by_kind[kind].pop(0))

        leftovers = sorted(
            [match for matches in by_kind.values() for match in matches],
            key=lambda item: (-item.score, item.kind, item.name),
        )
        selected.extend(leftovers[: max(0, limit - len(selected))])
        return selected[:limit]

    def _match_commands(self, tokens: set[str]) -> list[RoutedMatch]:
        matches: list[RoutedMatch] = []
        for cmd in self.commands:
            score = 0
            for token in tokens:
                if cmd.matches_token(token):
                    score += 1
            if score > 0:
                matches.append(
                    RoutedMatch(
                        kind="command",
                        name=cmd.name,
                        source_hint=cmd.handler or "built-in",
                        score=score,
                        description=cmd.description,
                    )
                )
        matches.sort(key=lambda item: (-item.score, item.name))
        return matches

    def _match_tools(self, tokens: set[str]) -> list[RoutedMatch]:
        matches: list[RoutedMatch] = []
        for tool in self.tools:
            score = 0
            for token in tokens:
                if tool.matches_token(token):
                    score += 1
            if score > 0:
                matches.append(
                    RoutedMatch(
                        kind="tool",
                        name=tool.name,
                        source_hint=tool.group or "default",
                        score=score,
                        description=tool.description,
                    )
                )
        matches.sort(key=lambda item: (-item.score, item.name))
        return matches

    def _match_skills(self, tokens: set[str]) -> list[RoutedMatch]:
        matches: list[RoutedMatch] = []
        for skill in self.skills:
            score = 0
            for token in tokens:
                if skill.matches_token(token):
                    score += 1
            if score > 0:
                matches.append(
                    RoutedMatch(
                        kind="skill",
                        name=skill.name,
                        source_hint=skill.path or "skills",
                        score=score,
                        description=skill.description,
                    )
                )
        matches.sort(key=lambda item: (-item.score, item.name))
        return matches

    def is_command(self, prompt: str) -> bool:
        stripped = prompt.strip()
        return stripped.startswith("/")

    def parse_command(self, prompt: str) -> tuple[str, str] | None:
        stripped = prompt.strip()
        if not stripped.startswith("/"):
            return None
        parts = stripped.split(None, 1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        return command, args

    def suggest_commands(self, prefix: str, limit: int = 5) -> list[CommandEntry]:
        lowered = prefix.lower().lstrip("/")
        if not lowered:
            return list(self.commands[:limit])
        matches = [
            cmd
            for cmd in self.commands
            if cmd.name.lower().lstrip("/").startswith(lowered)
            or any(alias.lower().startswith(lowered) for alias in cmd.aliases)
        ]
        return matches[:limit]

    def suggest_tools(self, query: str, limit: int = 10) -> list[ToolEntry]:
        lowered = query.lower()
        if not lowered:
            return list(self.tools[:limit])
        matches = [tool for tool in self.tools if tool.matches_token(lowered)]
        return matches[:limit]

    def summary_dict(self) -> dict[str, Any]:
        return {
            "commands": len(self.commands),
            "tools": len(self.tools),
            "skills": len(self.skills),
            "command_names": [cmd.name for cmd in self.commands],
            "tool_names": [tool.name for tool in self.tools],
            "skill_names": [skill.name for skill in self.skills],
        }


def build_router_from_skill_registry(skill_registry: Any) -> PromptRouter:
    skills: list[SkillEntry] = []
    loaded_skills = getattr(skill_registry, "loaded", [])
    for skill_info in loaded_skills:
        name = str(
            getattr(skill_info, "name", "") or getattr(skill_info, "skill_id", "")
        )
        description = str(getattr(skill_info, "description", "") or "")
        path = str(getattr(skill_info, "path", "") or "")
        tags = tuple(getattr(skill_info, "tags", []) or ())
        if name:
            skills.append(
                SkillEntry(name=name, description=description, path=path, tags=tags)
            )
    return PromptRouter(skills=tuple(skills))


__all__ = [
    "RoutedMatch",
    "CommandEntry",
    "ToolEntry",
    "SkillEntry",
    "PromptRouter",
    "DEFAULT_COMMANDS",
    "DEFAULT_TOOLS",
    "build_router_from_skill_registry",
]
