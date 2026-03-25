from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from agentscope.tool import Toolkit

from .models import (
    IGNORED_CHILD_DIRS,
    SKILL_MARKDOWN,
    SKILL_SCRIPTS_DIR,
    SCRIPT_RUNNERS_BY_SUFFIX,
    VALID_ACTIVATION_MODES,
    LoadedSkill,
    SkillLoadEvent,
    SkillLoadReport,
    SkillRuntimeContext,
    SkillScript,
)


class SkillRegistry:
    def __init__(
        self, directories: list[str], context: SkillRuntimeContext | None = None
    ) -> None:
        self.directories = directories
        self.context = context or SkillRuntimeContext()

    def register(self, toolkit: Toolkit) -> SkillLoadReport:
        report = SkillLoadReport(
            configured_directories=[
                str(Path(item).resolve()) for item in self.directories
            ]
        )
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
        if (base / SKILL_MARKDOWN).is_file():
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
                if (child / SKILL_MARKDOWN).is_file():
                    candidates.append(child)
                    continue
                queue.append(child)
        return candidates

    def _should_skip_child_dir(self, path: Path) -> bool:
        return path.name in IGNORED_CHILD_DIRS or path.name.startswith(".")

    def _load_skill(self, skill_dir: Path, source_directory: Path) -> LoadedSkill:
        skill_file = skill_dir / SKILL_MARKDOWN
        metadata, body = _parse_skill_file(skill_file)

        raw_name = metadata.get("name")
        raw_description = metadata.get("description")
        name = str(raw_name or "").strip()
        description = str(raw_description or "").strip()
        if not name or not description:
            raise ValueError(
                "SKILL.md front matter must include non-empty 'name' and 'description'."
            )

        activation_mode = _parse_activation_mode(
            metadata.get("activation"),
            metadata.get("manual_only"),
        )
        requires_tools = _coerce_string_list(
            metadata.get("requires_tools"), "requires_tools"
        )
        requires_browser = _coerce_bool(
            metadata.get("requires_browser"), "requires_browser"
        )
        requires_sandbox = _coerce_bool(
            metadata.get("requires_sandbox"), "requires_sandbox"
        )
        host_patterns = [
            _normalize_host(item)
            for item in _coerce_string_list(
                metadata.get("host_patterns"), "host_patterns"
            )
        ]
        host_patterns = [item for item in host_patterns if item]
        scripts = _discover_skill_scripts(skill_dir)
        scripts_dir = (
            str((skill_dir / SKILL_SCRIPTS_DIR).resolve()) if scripts else None
        )

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
        missing_tools = [
            tool
            for tool in skill.requires_tools
            if tool not in self.context.available_tools
        ]
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
    scripts_root = skill_dir / SKILL_SCRIPTS_DIR
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
                if child.name in IGNORED_CHILD_DIRS or child.name.startswith("."):
                    continue
                queue.append(child)
                continue

            runner = SCRIPT_RUNNERS_BY_SUFFIX.get(child.suffix.lower())
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
        raise ValueError(
            "SKILL.md must begin with YAML front matter delimited by '---'."
        )

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
    raise ValueError(
        f"Front matter field '{field_name}' must be a string or a list of strings."
    )


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
    if activation not in VALID_ACTIVATION_MODES:
        allowed = ", ".join(sorted(VALID_ACTIVATION_MODES))
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


__all__ = [
    "SkillRegistry",
    "_active_tool_names",
    "_discover_skill_scripts",
    "_parse_skill_file",
    "_split_front_matter",
    "_coerce_string_list",
    "_coerce_bool",
    "_parse_activation_mode",
    "_safe_host",
    "_normalize_host",
]
