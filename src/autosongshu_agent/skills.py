from __future__ import annotations

from dataclasses import asdict, dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from agentscope.tool import Toolkit

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
class SkillRuntimeContext:
    available_tools: set[str] = field(default_factory=set)
    sandbox_enabled: bool = False
    active_hosts: set[str] = field(default_factory=set)

    @classmethod
    def from_runtime(cls, toolkit: Toolkit, config: Any) -> "SkillRuntimeContext":
        available_tools = _active_tool_names(toolkit)
        active_hosts: set[str] = set()

        engagement = getattr(config, "engagement", None)
        if engagement is not None:
            start_host = _normalize_host(_safe_host(getattr(engagement, "start_url", None)))
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
        return any(name.startswith("browser_") for name in self.available_tools) or "cdp_send" in self.available_tools


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
    scripts: list["SkillScript"] = field(default_factory=list)

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
            lines.append("Prefer `run_skill_script` for these scripts and `list_skill_scripts` to inspect them.")
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
    activated: list[LoadedSkill] = field(default_factory=list)
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

        return "\n\n".join(section for section in sections if section.strip()).strip() or None


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
        available = sorted(self.all_available, key=lambda item: (item.activation_mode != "auto", item.name.lower()))
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
        available = sorted(self.all_available, key=lambda item: (item.activation_mode != "auto", item.name.lower()))
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
                sections.append(f"... and {len(self.manual_available) - len(preview)} more on-demand skills.")

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

        available_by_name = {skill.canonical_name: skill for skill in self.all_available}
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


class SkillRegistry:
    def __init__(self, directories: list[str], context: SkillRuntimeContext | None = None) -> None:
        self.directories = directories
        self.context = context or SkillRuntimeContext()

    def register(self, toolkit: Toolkit) -> SkillLoadReport:
        report = SkillLoadReport(configured_directories=[str(Path(item).resolve()) for item in self.directories])
        registered_names: dict[str, str] = {}
        seen_paths: set[str] = set()

        for raw_dir in self.directories:
            base = Path(raw_dir).expanduser()
            resolved_base = str(base.resolve())
            if not base.exists():
                report.skipped.append(
                    SkillLoadEvent(
                        status="skipped",
                        path=resolved_base,
                        source_directory=resolved_base,
                        reason="Configured skill directory does not exist.",
                    ),
                )
                continue
            if not base.is_dir():
                report.failed.append(
                    SkillLoadEvent(
                        status="failed",
                        path=resolved_base,
                        source_directory=resolved_base,
                        reason="Configured skill path is not a directory.",
                    ),
                )
                continue

            for skill_dir in self._iter_candidate_skill_dirs(base):
                resolved_skill_dir = str(skill_dir.resolve())
                if resolved_skill_dir in seen_paths:
                    report.skipped.append(
                        SkillLoadEvent(
                            status="skipped",
                            path=resolved_skill_dir,
                            source_directory=resolved_base,
                            reason="Duplicate skill path encountered; keeping the first registration.",
                        ),
                    )
                    continue

                try:
                    loaded_skill = self._load_skill(skill_dir, base)
                except Exception as exc:
                    report.failed.append(
                        SkillLoadEvent(
                            status="failed",
                            path=resolved_skill_dir,
                            source_directory=resolved_base,
                            reason=str(exc),
                        ),
                    )
                    continue

                existing_path = registered_names.get(loaded_skill.canonical_name)
                if existing_path is not None:
                    report.skipped.append(
                        SkillLoadEvent(
                            status="skipped",
                            path=loaded_skill.directory,
                            name=loaded_skill.name,
                            source_directory=loaded_skill.source_directory,
                            reason=(
                                "Duplicate skill name encountered; keeping the earlier registration "
                                f"from {existing_path}."
                            ),
                        ),
                    )
                    continue

                availability_reason = self._availability_reason(loaded_skill)
                if availability_reason is not None:
                    report.skipped.append(
                        SkillLoadEvent(
                            status="skipped",
                            path=loaded_skill.directory,
                            name=loaded_skill.name,
                            source_directory=loaded_skill.source_directory,
                            reason=availability_reason,
                        ),
                    )
                    continue

                if loaded_skill.auto_activate:
                    try:
                        toolkit.register_agent_skill(loaded_skill.directory)
                    except Exception as exc:
                        report.failed.append(
                            SkillLoadEvent(
                                status="failed",
                                path=loaded_skill.directory,
                                name=loaded_skill.name,
                                source_directory=loaded_skill.source_directory,
                                reason=f"AgentScope registration failed: {exc}",
                            ),
                        )
                        continue
                    report.loaded.append(loaded_skill)
                else:
                    report.manual_available.append(loaded_skill)

                registered_names[loaded_skill.canonical_name] = loaded_skill.directory
                seen_paths.add(loaded_skill.directory)

        return report

    def _iter_candidate_skill_dirs(self, base: Path) -> list[Path]:
        if (base / _SKILL_MARKDOWN).is_file():
            return [base]

        candidates: list[Path] = []
        queue: list[Path] = [base]
        while queue:
            current = queue.pop(0)
            try:
                children = sorted(current.iterdir(), key=lambda item: item.name.lower())
            except OSError:
                continue
            for child in children:
                if not child.is_dir():
                    continue
                if child.is_symlink():
                    continue
                if self._should_skip_child_dir(child):
                    continue
                if (child / _SKILL_MARKDOWN).is_file():
                    candidates.append(child)
                    continue
                queue.append(child)
        return candidates

    def _should_skip_child_dir(self, path: Path) -> bool:
        return path.name in _IGNORED_CHILD_DIRS or path.name.startswith(".")

    def _load_skill(self, skill_dir: Path, source_directory: Path) -> LoadedSkill:
        skill_file = skill_dir / _SKILL_MARKDOWN
        metadata, body = _parse_skill_file(skill_file)

        raw_name = metadata.get("name")
        raw_description = metadata.get("description")
        name = str(raw_name or "").strip()
        description = str(raw_description or "").strip()
        if not name or not description:
            raise ValueError("SKILL.md front matter must include non-empty 'name' and 'description'.")

        activation_mode = _parse_activation_mode(
            metadata.get("activation"),
            metadata.get("manual_only"),
        )
        requires_tools = _coerce_string_list(metadata.get("requires_tools"), "requires_tools")
        requires_browser = _coerce_bool(metadata.get("requires_browser"), "requires_browser")
        requires_sandbox = _coerce_bool(metadata.get("requires_sandbox"), "requires_sandbox")
        host_patterns = [_normalize_host(item) for item in _coerce_string_list(metadata.get("host_patterns"), "host_patterns")]
        host_patterns = [item for item in host_patterns if item]
        scripts = _discover_skill_scripts(skill_dir)
        scripts_dir = str((skill_dir / _SKILL_SCRIPTS_DIR).resolve()) if scripts else None

        return LoadedSkill(
            name=name,
            description=description,
            directory=str(skill_dir.resolve()),
            source_directory=str(source_directory.resolve()),
            body=body,
            activation_mode=activation_mode,
            requires_tools=requires_tools,
            requires_browser=requires_browser,
            requires_sandbox=requires_sandbox,
            host_patterns=host_patterns,
            scripts_dir=scripts_dir,
            scripts=scripts,
        )

    def _availability_reason(self, skill: LoadedSkill) -> str | None:
        missing_tools = [tool for tool in skill.requires_tools if tool not in self.context.available_tools]
        if missing_tools:
            return f"Missing required tools: {', '.join(missing_tools)}."

        if skill.requires_browser and not self.context.browser_available:
            return "Browser tooling is unavailable for this run."

        if skill.requires_sandbox and not self.context.sandbox_enabled:
            return "Sandbox support is disabled for this run."

        if skill.host_patterns:
            if not self.context.active_hosts:
                return "No active hosts are available to evaluate this skill's host_patterns."

            matched = any(
                fnmatchcase(host, pattern)
                for host in self.context.active_hosts
                for pattern in skill.host_patterns
            )
            if not matched:
                patterns = ", ".join(skill.host_patterns)
                hosts = ", ".join(sorted(self.context.active_hosts))
                return f"Host patterns [{patterns}] do not match the active hosts [{hosts}]."

        return None


def _active_tool_names(toolkit: Toolkit) -> set[str]:
    tools = getattr(toolkit, "tools", {}) or {}
    groups = getattr(toolkit, "groups", {}) or {}
    active_tools: set[str] = set()

    for name, registered in tools.items():
        group_name = getattr(registered, "group", "basic")
        if group_name == "basic":
            active_tools.add(str(name))
            continue
        group = groups.get(group_name)
        if group is not None and bool(getattr(group, "active", False)):
            active_tools.add(str(name))
    return active_tools


def _discover_skill_scripts(skill_dir: Path) -> list[SkillScript]:
    scripts_root = skill_dir / _SKILL_SCRIPTS_DIR
    if not scripts_root.is_dir():
        return []

    scripts: list[SkillScript] = []
    queue: list[Path] = [scripts_root]
    while queue:
        current = queue.pop(0)
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue

        for child in children:
            if child.is_symlink():
                continue
            if child.is_dir():
                if child.name in _IGNORED_CHILD_DIRS or child.name.startswith("."):
                    continue
                queue.append(child)
                continue

            runner = _SCRIPT_RUNNERS_BY_SUFFIX.get(child.suffix.lower())
            if runner is None:
                continue
            scripts.append(
                SkillScript(
                    name=child.name,
                    relative_path=child.relative_to(skill_dir).as_posix(),
                    absolute_path=str(child.resolve()),
                    runner=runner,
                ),
            )

    return scripts


def _parse_skill_file(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Unable to read {path.name}: {exc}") from exc

    metadata_text, body = _split_front_matter(raw)
    try:
        metadata = yaml.safe_load(metadata_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML front matter: {exc}") from exc

    if not isinstance(metadata, dict):
        raise ValueError("SKILL.md front matter must be a YAML mapping.")
    return metadata, body.strip()


def _split_front_matter(raw: str) -> tuple[str, str]:
    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must begin with YAML front matter delimited by '---'.")

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            metadata = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :])
            return metadata, body

    raise ValueError("SKILL.md front matter is missing a closing '---' delimiter.")


def _coerce_string_list(raw: Any, field_name: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, list):
        values: list[str] = []
        for item in raw:
            text = str(item).strip()
            if text:
                values.append(text)
        return values
    raise ValueError(f"Front matter field '{field_name}' must be a string or a list of strings.")


def _coerce_bool(raw: Any, field_name: str) -> bool:
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    raise ValueError(f"Front matter field '{field_name}' must be a boolean.")


def _parse_activation_mode(raw_activation: Any, raw_manual_only: Any) -> str:
    if _coerce_bool(raw_manual_only, "manual_only"):
        return "manual"

    activation = str(raw_activation or "auto").strip().lower()
    if activation not in _VALID_ACTIVATION_MODES:
        allowed = ", ".join(sorted(_VALID_ACTIVATION_MODES))
        raise ValueError(f"Front matter field 'activation' must be one of: {allowed}.")
    return activation


def _safe_host(raw_url: Any) -> str | None:
    if not raw_url:
        return None
    try:
        return urlparse(str(raw_url)).hostname
    except Exception:
        return None


def _normalize_host(host: str | None) -> str:
    return str(host or "").strip().lower()
