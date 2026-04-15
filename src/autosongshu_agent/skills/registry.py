from __future__ import annotations

import logging
import os
import threading
from collections import deque
from dataclasses import dataclass, replace
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


@dataclass(slots=True)
class _SkillParseCacheEntry:
    skill_mtime_ns: int
    skill_size: int
    scripts_root_exists: bool
    tracked_dir_mtimes: dict[str, int]
    loaded_skill: LoadedSkill

    def is_valid(self, skill_file: Path, scripts_root: Path) -> bool:
        try:
            skill_stat = skill_file.stat()
        except OSError:
            return False

        if (
            skill_stat.st_mtime_ns != self.skill_mtime_ns
            or skill_stat.st_size != self.skill_size
        ):
            return False

        if scripts_root.is_dir() != self.scripts_root_exists:
            return False

        for dir_path, expected_mtime in self.tracked_dir_mtimes.items():
            try:
                current_mtime = Path(dir_path).stat().st_mtime_ns
            except OSError:
                return False
            if current_mtime != expected_mtime:
                return False

        return True


_SKILL_PARSE_CACHE: dict[str, _SkillParseCacheEntry] = {}
_SKILL_PARSE_CACHE_LOCK = threading.RLock()


class SkillRegistry:
    _log = logging.getLogger("autosongshu.skills")

    def __init__(
        self, directories: list[str], context: SkillRuntimeContext | None = None
    ) -> None:
        self.directories = directories
        self.context = context or SkillRuntimeContext()
        self._bin_lookup_cache: dict[str, bool] = {}

    def register(self, toolkit: Toolkit) -> SkillLoadReport:
        report = SkillLoadReport(
            configured_directories=[
                str(Path(item).resolve()) for item in self.directories
            ]
        )
        registered_names: dict[str, str] = {}
        seen_paths: set[str] = set()

        self._log.info(
            "Skill loading started: directories=%s, available_tools=%s",
            self.directories,
            self.context.available_tools if self.context else "N/A",
        )

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
                    self._log.warning("Failed to load skill from %s: %s", resolved_skill_dir, exc)
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
                existing_skill = (
                    self._find_registered_skill(report, existing_path)
                    if existing_path is not None
                    else None
                )

                availability_reason = self._availability_reason(loaded_skill)
                if availability_reason is not None:
                    self._log.info("Skipped skill %s: %s", loaded_skill.name, availability_reason)
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
                        self._log.warning("Failed to register skill %s with AgentScope: %s", loaded_skill.name, exc)
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
                    self._log.info("Loaded skill: %s (%s)", loaded_skill.name, loaded_skill.directory)
                    report.loaded.append(loaded_skill)
                else:
                    report.manual_available.append(loaded_skill)

                if existing_path is not None:
                    replaced = self._pop_registered_skill(report, existing_path)
                    if replaced is not None and replaced.auto_activate:
                        self._try_unregister_agent_skill(toolkit, replaced.name)
                    report.skipped.append(
                        SkillLoadEvent(
                            status="skipped",
                            path=existing_path,
                            name=(
                                replaced.name
                                if replaced is not None
                                else (
                                    existing_skill.name
                                    if existing_skill is not None
                                    else loaded_skill.name
                                )
                            ),
                            source_directory=(
                                replaced.source_directory
                                if replaced is not None
                                else (
                                    existing_skill.source_directory
                                    if existing_skill is not None
                                    else loaded_skill.source_directory
                                )
                            ),
                            reason=(
                                "Skill name overridden by a later registration from "
                                f"{loaded_skill.directory}."
                            ),
                        ),
                    )

                registered_names[loaded_skill.canonical_name] = loaded_skill.directory
                seen_paths.add(loaded_skill.directory)

        self._log.info(
            "Skill loading finished: %d loaded, %d manual, %d skipped, %d failed",
            len(report.loaded),
            len(report.manual_available),
            len(report.skipped),
            len(report.failed),
        )
        if report.skipped:
            for evt in report.skipped:
                self._log.info("  skipped: %s — %s", evt.name, evt.reason)
        if report.failed:
            for evt in report.failed:
                self._log.warning("  failed: %s — %s", evt.name or evt.path, evt.reason)

        return report

    def _iter_candidate_skill_dirs(self, base: Path) -> list[Path]:
        if (base / SKILL_MARKDOWN).is_file():
            return [base]

        candidates: list[Path] = []
        queue: deque[Path] = deque([base])
        while queue:
            current = queue.popleft()
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
        scripts_root = skill_dir / SKILL_SCRIPTS_DIR
        resolved_dir = str(skill_dir.resolve())
        resolved_source = str(source_directory.resolve())

        with _SKILL_PARSE_CACHE_LOCK:
            cache_entry = _SKILL_PARSE_CACHE.get(resolved_dir)

        if cache_entry is not None and cache_entry.is_valid(skill_file, scripts_root):
            return self._clone_cached_skill(
                cache_entry.loaded_skill, source_directory=resolved_source
            )

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
        version = str(metadata.get("version") or "").strip()
        tags = _coerce_string_list(metadata.get("tags"), "tags")
        env_required = _coerce_string_list(metadata.get("env_required"), "env_required")
        requires_bins = _coerce_string_list(metadata.get("requires_bins"), "requires_bins")
        timeout = int(metadata.get("timeout") or 0)
        when_to_use = str(metadata.get("when_to_use") or "").strip()
        scripts, tracked_dir_mtimes = _discover_skill_scripts_with_tracking(skill_dir)
        scripts_dir = (
            str((skill_dir / SKILL_SCRIPTS_DIR).resolve()) if scripts else None
        )
        loaded_skill = LoadedSkill(
            name=name,
            description=description,
            directory=resolved_dir,
            source_directory=resolved_source,
            body=body,
            activation_mode=activation_mode,
            requires_tools=requires_tools,
            requires_browser=requires_browser,
            requires_sandbox=requires_sandbox,
            host_patterns=host_patterns,
            version=version,
            tags=tags,
            env_required=env_required,
            requires_bins=requires_bins,
            timeout=timeout,
            when_to_use=when_to_use,
            scripts_dir=scripts_dir,
            scripts=scripts,
        )

        try:
            skill_stat = skill_file.stat()
        except OSError:
            return loaded_skill

        with _SKILL_PARSE_CACHE_LOCK:
            _SKILL_PARSE_CACHE[resolved_dir] = _SkillParseCacheEntry(
                skill_mtime_ns=skill_stat.st_mtime_ns,
                skill_size=skill_stat.st_size,
                scripts_root_exists=scripts_root.is_dir(),
                tracked_dir_mtimes=tracked_dir_mtimes,
                loaded_skill=loaded_skill,
            )

        return loaded_skill

    def _clone_cached_skill(
        self, cached: LoadedSkill, *, source_directory: str
    ) -> LoadedSkill:
        if cached.source_directory == source_directory:
            return cached
        return replace(cached, source_directory=source_directory)

    def _find_registered_skill(
        self, report: SkillLoadReport, skill_path: str | None
    ) -> LoadedSkill | None:
        if not skill_path:
            return None
        for collection in (report.loaded, report.manual_available):
            for item in collection:
                if item.directory == skill_path:
                    return item
        return None

    def _pop_registered_skill(
        self, report: SkillLoadReport, skill_path: str | None
    ) -> LoadedSkill | None:
        if not skill_path:
            return None
        for collection in (report.loaded, report.manual_available):
            for index, item in enumerate(collection):
                if item.directory == skill_path:
                    return collection.pop(index)
        return None

    def _try_unregister_agent_skill(self, toolkit: Toolkit, skill_name: str) -> None:
        remove_skill = getattr(toolkit, "remove_agent_skill", None)
        if not callable(remove_skill):
            return
        try:
            remove_skill(skill_name)
        except Exception as exc:
            self._log.warning(
                "Failed to unregister overridden skill %s: %s",
                skill_name,
                exc,
            )

    def _availability_reason(self, skill: LoadedSkill) -> str | None:
        missing_tools = [
            tool
            for tool in skill.requires_tools
            if tool not in self.context.available_tools
        ]
        if missing_tools:
            self._log.warning(
                "Skill %s skipped: missing tools %s (available: %s)",
                skill.name,
                missing_tools,
                sorted(self.context.available_tools) if self.context.available_tools else "(empty)",
            )
            return f"Missing required tools: {', '.join(missing_tools)}."

        if skill.requires_browser and not self.context.browser_available:
            return "Browser tooling is unavailable for this run."

        if skill.requires_sandbox and not self.context.sandbox_enabled:
            return "Sandbox support is disabled for this run."

        if skill.requires_bins:
            import shutil

            missing_bins: list[str] = []
            for bin_name in skill.requires_bins:
                available = self._bin_lookup_cache.get(bin_name)
                if available is None:
                    available = shutil.which(bin_name) is not None
                    self._bin_lookup_cache[bin_name] = available
                if not available:
                    missing_bins.append(bin_name)
            if missing_bins:
                self._log.warning("Skill %s skipped: missing binaries %s", skill.name, missing_bins)
                return f"Missing required binaries: {', '.join(missing_bins)}."

        if skill.env_required:
            missing_env = [
                env_name for env_name in skill.env_required
                if not os.environ.get(env_name)
            ]
            if missing_env:
                self._log.warning("Skill %s skipped: missing env vars %s", skill.name, missing_env)
                return f"Missing required environment variables: {', '.join(missing_env)}."

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
    """Return the set of tool names that are currently registered and active.

    Instead of probing AgentScope's internal Toolkit structure (which may
    change between versions), we read from our own registry which tracks
    every tool registered via @registry.register().
    """
    from ..tool_impls.registry import registry as tool_registry

    active_tools: set[str] = set()
    for info in tool_registry.tools:
        active_tools.add(info.func.__name__)
    _log = logging.getLogger("autosongshu.skills")
    _log.info(
        "_active_tool_names: found %d tools: %s",
        len(active_tools),
        sorted(active_tools),
    )
    return active_tools


def _discover_skill_scripts(skill_dir: Path) -> list[SkillScript]:
    scripts, _ = _discover_skill_scripts_with_tracking(skill_dir)
    return scripts


def _discover_skill_scripts_with_tracking(
    skill_dir: Path,
) -> tuple[list[SkillScript], dict[str, int]]:
    scripts_root = skill_dir / SKILL_SCRIPTS_DIR
    if not scripts_root.is_dir():
        return [], {}

    scripts: list[SkillScript] = []
    tracked_dir_mtimes: dict[str, int] = {}
    queue: deque[Path] = deque([scripts_root])
    while queue:
        current = queue.popleft()
        try:
            tracked_dir_mtimes[str(current.resolve())] = current.stat().st_mtime_ns
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

    return scripts, tracked_dir_mtimes


def _parse_skill_file(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Unable to read {path}: {exc}") from exc

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
