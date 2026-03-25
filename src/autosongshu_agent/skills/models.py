from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

_SKILL_MARKDOWN = "SKILL.md"
_SKILL_SCRIPTS_DIR = "scripts"
_IGNORED_CHILD_DIRS = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "node_modules",
}
_VALID_ACTIVATION_MODES = {"auto", "manual"}
_SCRIPT_RUNNERS_BY_SUFFIX = {
    ".py": "python",
    ".ps1": "powershell",
    ".bat": "cmd",
    ".cmd": "cmd",
    ".sh": "shell",
}


@dataclass(slots=True)
class SkillScript:
    name: str
    relative_path: str
    absolute_path: str
    runner: str


@dataclass(slots=True)
class SkillLoadEvent:
    status: str
    path: str
    name: str | None = None
    source_directory: str | None = None
    reason: str | None = None

    @property
    def canonical_name(self) -> str | None:
        return self.name.strip().lower() if self.name else None


@dataclass(slots=True)
class SkillTurnSelection:
    requested_names: list[str]
    activated: list["LoadedSkill"] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    blocked: list[SkillLoadEvent] = field(default_factory=list)

    @property
    def prompt(self) -> str | None:
        if not self.activated and not self.missing and not self.blocked:
            return None

        sections: list[str] = []
        if self.activated:
            sections.append(
                "以下是操作员为当前这一轮显式启用的本地 skills。仅在与当前任务相关时优先遵循它们；若与系统安全约束冲突，以系统安全约束为准。"
            )
            sections.extend(skill.prompt_block() for skill in self.activated)

        notices: list[str] = []
        if self.missing:
            notices.append(f"未找到这些 skill: {', '.join(self.missing)}")
        if self.blocked:
            blocked_parts = []
            for item in self.blocked:
                label = item.name or item.path
                if item.reason:
                    blocked_parts.append(f"{label} ({item.reason})")
                else:
                    blocked_parts.append(label)
            notices.append(f"这些 skill 当前不可用: {', '.join(blocked_parts)}")
        if notices:
            sections.append("说明: " + "；".join(notices))

        return (
            "\n\n".join(section for section in sections if section.strip()).strip()
            or None
        )


@dataclass(slots=True)
class LoadedSkill:
    name: str
    description: str
    directory: str
    source_directory: str
    body: str
    activation_mode: str = "auto"
    requires_tools: list[str] = field(default_factory=list)
    requires_browser: bool = False
    requires_sandbox: bool = False
    host_patterns: list[str] = field(default_factory=list)
    scripts_dir: str | None = None
    scripts: list[SkillScript] = field(default_factory=list)

    @property
    def canonical_name(self) -> str:
        return self.name.strip().lower()

    @property
    def auto_activate(self) -> bool:
        return self.activation_mode == "auto"

    def prompt_block(self) -> str:
        lines = [
            f"## Skill: {self.name}",
            f"Description: {self.description}",
            f"Directory: {self.directory}",
        ]
        if self.scripts:
            preview = self.scripts[:8]
            lines.append("Bundled scripts:")
            lines.extend(f"- {item.relative_path} [{item.runner}]" for item in preview)
            if len(self.scripts) > len(preview):
                lines.append(f"- ... and {len(self.scripts) - len(preview)} more")
            lines.append(
                "Prefer `run_skill_script` for these scripts and `list_skill_scripts` to inspect them."
            )
        if self.body:
            lines.append(self.body)
        return "\n".join(lines).strip()

    def summary_block(self) -> str:
        lines = [
            f"## On-Demand Skill: {self.name}",
            f"Description: {self.description}",
            f"Activation: {self.activation_mode}",
        ]
        if self.scripts:
            preview = self.scripts[:6]
            lines.append("Bundled scripts:")
            lines.extend(f"- {item.relative_path} [{item.runner}]" for item in preview)
            if len(self.scripts) > len(preview):
                lines.append(f"- ... and {len(self.scripts) - len(preview)} more")
            lines.append(
                "Use `list_skill_scripts()` or `list_skill_scripts(skill_name=...)` to inspect this skill, "
                "then call `run_skill_script(...)` when the task clearly needs it.",
            )
        else:
            lines.append(
                "This skill does not ship scripts. Its full instructions are only available when the operator "
                "explicitly enables it for the current turn with `/skill skill-name`.",
            )
        return "\n".join(lines).strip()

    def index_line(self) -> str:
        activation = "auto" if self.auto_activate else "manual"
        delivery = "scripted" if self.scripts else "notes-only"
        return f"- {self.name} [{activation}; {delivery}]: {self.description}"


@dataclass(slots=True)
class SkillLoadReport:
    configured_directories: list[str]
    loaded: list[LoadedSkill] = field(default_factory=list)
    manual_available: list[LoadedSkill] = field(default_factory=list)
    skipped: list[SkillLoadEvent] = field(default_factory=list)
    failed: list[SkillLoadEvent] = field(default_factory=list)

    @property
    def loaded_paths(self) -> list[str]:
        return [skill.directory for skill in self.loaded]

    @property
    def all_available(self) -> list[LoadedSkill]:
        return [*self.loaded, *self.manual_available]

    @property
    def turn_hint(self) -> str | None:
        available = sorted(
            self.all_available,
            key=lambda item: (item.activation_mode != "auto", item.name.lower()),
        )
        if not available:
            return None

        scripted = [skill for skill in available if skill.scripts]
        lines = [
            "Available local skills in this session. If the task matches one of these, prefer using it instead of improvising from scratch:",
        ]
        lines.extend(skill.index_line() for skill in available[:12])
        if len(available) > 12:
            lines.append(f"- ... and {len(available) - 12} more local skills.")
        if scripted:
            lines.append(
                "If a loaded local scripted skill already matches the task, prefer inspecting and running that packaged workflow before writing ad-hoc sandbox code.",
            )
        lines.append(
            "For scripted skills, call `list_skill_scripts()` or `list_skill_scripts(skill_name=...)`, then use `run_skill_script(...)` when appropriate.",
        )
        return "\n".join(lines).strip()

    @property
    def agent_prompt(self) -> str | None:
        if not self.loaded and not self.manual_available:
            return None

        sections: list[str] = []
        available = sorted(
            self.all_available,
            key=lambda item: (item.activation_mode != "auto", item.name.lower()),
        )
        sections.append(
            (
                "Local skill index for this run. When a task matches one of these descriptions, prefer using the "
                "named skill instead of improvising a brand-new workflow."
            ),
        )
        sections.extend(skill.index_line() for skill in available[:24])
        if len(available) > 24:
            sections.append(f"... and {len(available) - 24} more local skills.")
        if any(skill.scripts for skill in available):
            sections.append(
                (
                    "When a loaded local scripted skill already fits the task, prefer `list_skill_scripts(...)` and "
                    "`run_skill_script(...)` before falling back to ad-hoc sandbox code."
                ),
            )
        sections.append(
            (
                "For scripted skills, inspect them with `list_skill_scripts()` or "
                "`list_skill_scripts(skill_name=...)`, then execute them with `run_skill_script(...)` when relevant."
            ),
        )

        if self.loaded:
            sections.append(
                (
                    "The following local skills are auto-loaded into this run. "
                    "Use them when their descriptions match the task, and follow their workflow, notes, "
                    "constraints, and evidence requirements."
                ),
            )
            sections.extend(skill.prompt_block() for skill in self.loaded)

        if self.manual_available:
            sections.append(
                (
                    "The following local manual skills are available on demand. "
                    "Their full SKILL.md bodies are not injected by default. Some ship scripts that you can inspect "
                    "with `list_skill_scripts()` and execute with `run_skill_script(...)`; others require the operator "
                    "to explicitly enable them with `/skill skill-name` before their full instructions become active."
                ),
            )
            preview = self.manual_available[:12]
            sections.extend(skill.summary_block() for skill in preview)
            if len(self.manual_available) > len(preview):
                sections.append(
                    f"... and {len(self.manual_available) - len(preview)} more on-demand skills."
                )

        return "\n\n".join(sections).strip()

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured_directories": list(self.configured_directories),
            "counts": {
                "loaded": len(self.loaded),
                "manual_available": len(self.manual_available),
                "skipped": len(self.skipped),
                "failed": len(self.failed),
            },
            "loaded": [asdict(item) for item in self.loaded],
            "manual_available": [asdict(item) for item in self.manual_available],
            "skipped": [asdict(item) for item in self.skipped],
            "failed": [asdict(item) for item in self.failed],
        }

    def build_turn_selection(self, requested_names: list[str]) -> SkillTurnSelection:
        requested: list[str] = []
        seen_requested: set[str] = set()
        for item in requested_names:
            normalized = item.strip()
            canonical = normalized.lower()
            if not normalized or canonical in seen_requested:
                continue
            seen_requested.add(canonical)
            requested.append(normalized)

        available_by_name = {
            skill.canonical_name: skill for skill in self.all_available
        }
        blocked_by_name = {
            event.canonical_name: event
            for event in self.skipped
            if event.canonical_name
        }

        activated: list[LoadedSkill] = []
        missing: list[str] = []
        blocked: list[SkillLoadEvent] = []

        for name in requested:
            canonical = name.lower()
            skill = available_by_name.get(canonical)
            if skill is not None:
                activated.append(skill)
                continue
            blocked_event = blocked_by_name.get(canonical)
            if blocked_event is not None:
                blocked.append(blocked_event)
                continue
            missing.append(name)

        return SkillTurnSelection(
            requested_names=requested,
            activated=activated,
            missing=missing,
            blocked=blocked,
        )


@dataclass(slots=True)
class SkillRuntimeContext:
    available_tools: set[str] = field(default_factory=set)
    sandbox_enabled: bool = False
    active_hosts: set[str] = field(default_factory=set)

    @classmethod
    def from_runtime(cls, toolkit: "Toolkit", config: Any) -> "SkillRuntimeContext":
        from .registry import _active_tool_names, _normalize_host, _safe_host

        available_tools = _active_tool_names(toolkit)
        active_hosts: set[str] = set()

        engagement = getattr(config, "engagement", None)
        if engagement is not None:
            start_host = _normalize_host(
                _safe_host(getattr(engagement, "start_url", None))
            )
            if start_host:
                active_hosts.add(start_host)

            for raw_host in getattr(engagement, "allowed_hosts", []) or []:
                normalized_host = _normalize_host(str(raw_host))
                if normalized_host:
                    active_hosts.add(normalized_host)

        sandbox = getattr(config, "sandbox", None)
        sandbox_enabled = bool(getattr(sandbox, "enabled", False))
        return cls(
            available_tools=available_tools,
            sandbox_enabled=sandbox_enabled,
            active_hosts=active_hosts,
        )

    @property
    def browser_available(self) -> bool:
        return (
            any(name.startswith("browser_") for name in self.available_tools)
            or "cdp_send" in self.available_tools
        )


__all__ = [
    "SKILL_MARKDOWN",
    "SKILL_SCRIPTS_DIR",
    "IGNORED_CHILD_DIRS",
    "VALID_ACTIVATION_MODES",
    "SCRIPT_RUNNERS_BY_SUFFIX",
    "SkillScript",
    "SkillLoadEvent",
    "SkillTurnSelection",
    "LoadedSkill",
    "SkillLoadReport",
    "SkillRuntimeContext",
]

SKILL_MARKDOWN = _SKILL_MARKDOWN
SKILL_SCRIPTS_DIR = _SKILL_SCRIPTS_DIR
IGNORED_CHILD_DIRS = _IGNORED_CHILD_DIRS
VALID_ACTIVATION_MODES = _VALID_ACTIVATION_MODES
SCRIPT_RUNNERS_BY_SUFFIX = _SCRIPT_RUNNERS_BY_SUFFIX
