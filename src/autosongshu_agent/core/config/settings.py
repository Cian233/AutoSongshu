"""
Multi-layer settings system - Configuration merging with priority chain.

Inspired by claw-code's 6-layer settings architecture:
1. Plugin Settings (base layer - injected defaults)
2. User Settings (~/.autosongshu/settings.json)
3. Project Settings (.autosongshu/settings.json - shared in Git)
4. Local Settings (.autosongshu/settings.local.json - gitignore)
5. Flag Settings (CLI --settings parameter)
6. Policy Settings (highest priority - enterprise policy)

Key design:
- Array order = merge priority (later overrides earlier)
- Scalars: overwrite
- Arrays: concatenate + deduplicate
- Trust boundary: project/local settings untrusted for risky operations
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Literal

SettingSource = Literal[
    "pluginSettings",
    "userSettings",
    "projectSettings",
    "localSettings",
    "flagSettings",
    "policySettings",
]

SETTING_SOURCES_ORDER: list[SettingSource] = [
    "pluginSettings",
    "userSettings",
    "projectSettings",
    "localSettings",
    "flagSettings",
    "policySettings",
]

TRUSTED_SETTING_SOURCES: frozenset[SettingSource] = frozenset(
    [
        "userSettings",
        "flagSettings",
        "policySettings",
    ]
)

PolicySubSource = Literal[
    "remoteApi",
    "mdm",
    "managedFile",
    "hkcuRegistry",
]

POLICY_SUB_ORDER: list[PolicySubSource] = [
    "remoteApi",
    "mdm",
    "managedFile",
    "hkcuRegistry",
]


class ValidationErrorKind(str, Enum):
    """Types of validation errors."""

    INVALID_JSON = "invalidJson"
    INVALID_SCHEMA = "invalidSchema"
    FILE_NOT_FOUND = "fileNotFound"
    PERMISSION_DENIED = "permissionDenied"


@dataclass
class ValidationError:
    """A validation error from settings parsing."""

    kind: ValidationErrorKind
    source: SettingSource
    path: str | None = None
    message: str = ""
    line: int | None = None


@dataclass
class SettingsJson:
    """
    Settings JSON structure.

    This defines the schema for settings files.
    """

    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None

    mcp_servers: dict[str, Any] = field(default_factory=dict)

    permissions: dict[str, Any] = field(default_factory=dict)

    env: dict[str, str] = field(default_factory=dict)

    hooks: dict[str, Any] = field(default_factory=dict)

    agent: dict[str, Any] = field(default_factory=dict)

    custom: dict[str, Any] = field(default_factory=dict)


@dataclass
class SettingsWithErrors:
    """Settings result with validation errors."""

    settings: SettingsJson
    errors: list[ValidationError] = field(default_factory=list)


def merge_arrays(target: list[Any], source: list[Any]) -> list[Any]:
    """Merge two arrays by concatenating and deduplicating."""
    result = list(target)
    for item in source:
        if item not in result:
            result.append(item)
    return result


def settings_merge_customizer(
    obj_value: Any,
    src_value: Any,
    key: str,
) -> Any | None:
    """
    Custom merge logic for settings.

    - Arrays: concatenate + deduplicate
    - Scalars: let default merge handle (src_value overwrites obj_value)
    - Objects: deep merge
    """
    if isinstance(obj_value, list) and isinstance(src_value, list):
        return merge_arrays(obj_value, src_value)
    return None


def deep_merge(
    target: dict[str, Any],
    source: dict[str, Any],
    customizer: Callable[[Any, Any, str], Any | None] | None = None,
) -> dict[str, Any]:
    """
    Deep merge two dictionaries.

    Uses customizer for special merge logic.
    """
    result = dict(target)

    for key, src_value in source.items():
        if key in result:
            obj_value = result[key]

            if customizer:
                custom_result = customizer(obj_value, src_value, key)
                if custom_result is not None:
                    result[key] = custom_result
                    continue

            if isinstance(obj_value, dict) and isinstance(src_value, dict):
                result[key] = deep_merge(obj_value, src_value, customizer)
            else:
                result[key] = src_value
        else:
            result[key] = src_value

    return result


def get_settings_file_path(
    source: SettingSource, project_dir: Path | None = None
) -> Path | None:
    """
    Get file path for a settings source.

    Returns None for non-file sources (plugin, flag, policy).
    """
    home = Path.home()

    if source == "userSettings":
        return home / ".autosongshu" / "settings.json"

    if source == "projectSettings":
        if project_dir:
            return project_dir / ".autosongshu" / "settings.json"
        return None

    if source == "localSettings":
        if project_dir:
            return project_dir / ".autosongshu" / "settings.local.json"
        return None

    return None


def parse_settings_file(path: Path) -> SettingsWithErrors:
    """
    Parse a settings file with validation.

    Returns settings and any errors encountered.
    """
    if not path.exists():
        return SettingsWithErrors(
            settings=SettingsJson(),
            errors=[
                ValidationError(
                    kind=ValidationErrorKind.FILE_NOT_FOUND,
                    source="userSettings",
                    path=str(path),
                    message=f"Settings file not found: {path}",
                )
            ],
        )

    try:
        content = path.read_text(encoding="utf-8")
        raw = json.loads(content)
    except json.JSONDecodeError as e:
        return SettingsWithErrors(
            settings=SettingsJson(),
            errors=[
                ValidationError(
                    kind=ValidationErrorKind.INVALID_JSON,
                    source="userSettings",
                    path=str(path),
                    message=f"Invalid JSON: {e.msg}",
                    line=e.lineno,
                )
            ],
        )

    settings = SettingsJson()

    if raw:
        for key, value in raw.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
            else:
                settings.custom[key] = value

    return SettingsWithErrors(settings=settings)


@dataclass
class SettingsLoader:
    """
    Settings loader with multi-layer support.

    Handles loading, merging, and validation of settings from multiple sources.
    """

    project_dir: Path | None = None
    plugin_settings: SettingsJson | None = None
    flag_settings: SettingsJson | None = None
    policy_settings: SettingsJson | None = None

    _cache: SettingsWithErrors | None = None
    _is_loading: bool = False

    def get_plugin_settings_base(self) -> SettingsJson | None:
        """Get plugin settings (base layer)."""
        return self.plugin_settings

    def get_policy_settings(self) -> SettingsJson | None:
        """
        Get policy settings with first-source-wins logic.

        Policy has internal 4-layer priority:
        1. Remote API (highest)
        2. MDM (HKLM/plist)
        3. Managed file (managed-settings.json)
        4. HKCU registry (lowest)
        """
        if self.policy_settings:
            return self.policy_settings

        for sub_source in POLICY_SUB_ORDER:
            settings = self._load_policy_sub_source(sub_source)
            if settings:
                return settings

        return None

    def _load_policy_sub_source(
        self, sub_source: PolicySubSource
    ) -> SettingsJson | None:
        """Load policy from a specific sub-source."""
        if sub_source == "managedFile":
            home = Path.home()
            managed_path = home / ".autosongshu" / "managed-settings.json"
            if managed_path.exists():
                result = parse_settings_file(managed_path)
                return result.settings if result.errors else None

        return None

    def load_settings_from_disk(self) -> SettingsWithErrors:
        """
        Load and merge all settings from disk.

        This is the core merge function.

        Priority order:
        1. Plugin Settings (base)
        2. User Settings
        3. Project Settings
        4. Local Settings
        5. Flag Settings
        6. Policy Settings (highest)
        """
        if self._is_loading:
            return SettingsWithErrors(settings=SettingsJson())

        self._is_loading = True
        try:
            merged_raw: dict[str, Any] = {}
            all_errors: list[ValidationError] = []
            seen_files: set[str] = set()

            plugin_settings = self.get_plugin_settings_base()
            if plugin_settings:
                merged_raw = deep_merge(
                    merged_raw,
                    self._settings_to_dict(plugin_settings),
                    settings_merge_customizer,
                )

            for source in SETTING_SOURCES_ORDER:
                if source == "pluginSettings":
                    continue

                if source == "policySettings":
                    policy_settings = self.get_policy_settings()
                    if policy_settings:
                        merged_raw = deep_merge(
                            merged_raw,
                            self._settings_to_dict(policy_settings),
                            settings_merge_customizer,
                        )
                    continue

                if source == "flagSettings":
                    if self.flag_settings:
                        merged_raw = deep_merge(
                            merged_raw,
                            self._settings_to_dict(self.flag_settings),
                            settings_merge_customizer,
                        )
                    continue

                path = get_settings_file_path(source, self.project_dir)
                if path:
                    resolved = str(path.resolve())
                    if resolved not in seen_files:
                        seen_files.add(resolved)
                        result = parse_settings_file(path)
                        if result.settings:
                            merged_raw = deep_merge(
                                merged_raw,
                                self._settings_to_dict(result.settings),
                                settings_merge_customizer,
                            )
                        all_errors.extend(result.errors)

            final_settings = self._dict_to_settings(merged_raw)
            self._cache = SettingsWithErrors(settings=final_settings, errors=all_errors)
            return self._cache
        finally:
            self._is_loading = False

    def _settings_to_dict(self, settings: SettingsJson) -> dict[str, Any]:
        """Convert SettingsJson to dict."""
        result: dict[str, Any] = {}
        for key in [
            "model",
            "temperature",
            "max_tokens",
            "mcp_servers",
            "permissions",
            "env",
            "hooks",
            "agent",
        ]:
            value = getattr(settings, key, None)
            if value is not None:
                result[key] = value
        if settings.custom:
            result.update(settings.custom)
        return result

    def _dict_to_settings(self, raw: dict[str, Any]) -> SettingsJson:
        """Convert dict to SettingsJson."""
        settings = SettingsJson()
        for key, value in raw.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
            else:
                settings.custom[key] = value
        return settings

    def get_settings(self) -> SettingsJson:
        """Get current settings (cached or load fresh)."""
        if self._cache:
            return self._cache.settings
        result = self.load_settings_from_disk()
        return result.settings

    def is_source_trusted(self, source: SettingSource) -> bool:
        """Check if a settings source is trusted for risky operations."""
        return source in TRUSTED_SETTING_SOURCES

    def get_safe_env_vars(self, source: SettingSource) -> dict[str, str]:
        """
        Get environment variables that are safe to apply from this source.

        Untrusted sources (project, local) only get whitelisted vars.
        """
        SAFE_ENV_VARS = frozenset(
            [
                "PATH",
                "HOME",
                "USER",
                "TEMP",
                "TMPDIR",
            ]
        )

        settings = self.get_settings()

        if self.is_source_trusted(source):
            return settings.env

        return {k: v for k, v in settings.env.items() if k in SAFE_ENV_VARS}


_global_loader: SettingsLoader | None = None


def get_settings_loader(project_dir: Path | None = None) -> SettingsLoader:
    """Get the global settings loader."""
    global _global_loader
    if _global_loader is None:
        _global_loader = SettingsLoader(project_dir=project_dir)
    return _global_loader


def reset_settings_loader() -> None:
    """Reset the global settings loader (for testing)."""
    global _global_loader
    _global_loader = None
