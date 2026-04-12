"""Tests for multi-layer settings system."""

import json
import pytest
from pathlib import Path
from typing import Any

from autosongshu_agent.core.config.settings import (
    ValidationError,
    ValidationErrorKind,
    SettingsJson,
    SettingsWithErrors,
    SettingsLoader,
    SettingSource,
    SETTING_SOURCES_ORDER,
    TRUSTED_SETTING_SOURCES,
    deep_merge,
    merge_arrays,
    settings_merge_customizer,
    get_settings_file_path,
    parse_settings_file,
    get_settings_loader,
    reset_settings_loader,
)


class TestMergeArrays:
    """Tests for merge_arrays()."""

    def test_merge_empty_arrays(self):
        assert merge_arrays([], []) == []

    def test_merge_with_duplicates(self):
        target = [1, 2, 3]
        source = [2, 3, 4]
        result = merge_arrays(target, source)
        assert result == [1, 2, 3, 4]

    def test_merge_preserves_order(self):
        target = ["a", "b"]
        source = ["c", "a"]
        result = merge_arrays(target, source)
        assert result == ["a", "b", "c"]

    def test_merge_with_dicts(self):
        target = [{"id": 1}]
        source = [{"id": 2}, {"id": 1}]
        result = merge_arrays(target, source)
        assert result == [{"id": 1}, {"id": 2}]


class TestDeepMerge:
    """Tests for deep_merge()."""

    def test_merge_empty_dicts(self):
        assert deep_merge({}, {}) == {}

    def test_merge_scalars(self):
        target = {"a": 1, "b": 2}
        source = {"b": 3, "c": 4}
        result = deep_merge(target, source)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_nested_dicts(self):
        target = {"nested": {"x": 1, "y": 2}}
        source = {"nested": {"y": 3, "z": 4}}
        result = deep_merge(target, source)
        assert result == {"nested": {"x": 1, "y": 3, "z": 4}}

    def test_merge_with_customizer(self):
        def customizer(obj_val: Any, src_val: Any, key: str) -> Any | None:
            if isinstance(obj_val, list) and isinstance(src_val, list):
                return obj_val + src_val
            return None

        target = {"list": [1, 2], "scalar": "old"}
        source = {"list": [3, 4], "scalar": "new"}
        result = deep_merge(target, source, customizer)
        assert result["list"] == [1, 2, 3, 4]
        assert result["scalar"] == "new"


class TestSettingsMergeCustomizer:
    """Tests for settings_merge_customizer()."""

    def test_arrays_are_concatenated(self):
        result = settings_merge_customizer([1, 2], [2, 3], "test_key")
        assert result == [1, 2, 3]

    def test_scalars_return_none(self):
        result = settings_merge_customizer(1, 2, "test_key")
        assert result is None


class TestGetSettingsFilePath:
    """Tests for get_settings_file_path()."""

    def test_user_settings_path(self):
        path = get_settings_file_path("userSettings")
        assert path is not None
        assert path.name == "settings.json"
        assert ".autosongshu" in str(path)

    def test_project_settings_path(self):
        project_dir = Path("/tmp/test_project")
        path = get_settings_file_path("projectSettings", project_dir=project_dir)
        assert path is not None
        assert path == project_dir / ".autosongshu" / "settings.json"

    def test_project_settings_without_project_dir(self):
        path = get_settings_file_path("projectSettings")
        assert path is None

    def test_non_file_sources(self):
        assert get_settings_file_path("pluginSettings") is None
        assert get_settings_file_path("flagSettings") is None
        assert get_settings_file_path("policySettings") is None


class TestParseSettingsFile:
    """Tests for parse_settings_file()."""

    def test_parse_valid_file(self, tmp_path: Path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(
            json.dumps(
                {
                    "model": "gpt-4",
                    "temperature": 0.7,
                    "env": {"API_KEY": "test"},
                }
            )
        )

        result = parse_settings_file(settings_file)
        assert result.errors == []
        assert result.settings.model == "gpt-4"
        assert result.settings.temperature == 0.7
        assert result.settings.env == {"API_KEY": "test"}

    def test_parse_invalid_json(self, tmp_path: Path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text("{ invalid json }")

        result = parse_settings_file(settings_file)
        assert len(result.errors) == 1
        assert result.errors[0].kind == ValidationErrorKind.INVALID_JSON

    def test_parse_nonexistent_file(self, tmp_path: Path):
        settings_file = tmp_path / "nonexistent.json"

        result = parse_settings_file(settings_file)
        assert len(result.errors) == 1
        assert result.errors[0].kind == ValidationErrorKind.FILE_NOT_FOUND

    def test_parse_with_custom_fields(self, tmp_path: Path):
        settings_file = tmp_path / "settings.json"
        settings_file.write_text(
            json.dumps(
                {
                    "model": "gpt-4",
                    "custom_field": "custom_value",
                }
            )
        )

        result = parse_settings_file(settings_file)
        assert result.errors == []
        assert result.settings.custom["custom_field"] == "custom_value"


class TestSettingsLoader:
    """Tests for SettingsLoader."""

    def test_empty_loader(self):
        loader = SettingsLoader()
        result = loader.load_settings_from_disk()
        assert isinstance(result.settings, SettingsJson)

    def test_plugin_settings_as_base(self):
        plugin_settings = SettingsJson(model="plugin-model", temperature=0.5)
        loader = SettingsLoader(plugin_settings=plugin_settings)
        result = loader.load_settings_from_disk()
        assert result.settings.model == "plugin-model"
        assert result.settings.temperature == 0.5

    def test_flag_settings_override(self):
        plugin_settings = SettingsJson(model="plugin-model")
        flag_settings = SettingsJson(model="flag-model", temperature=0.8)
        loader = SettingsLoader(
            plugin_settings=plugin_settings,
            flag_settings=flag_settings,
        )
        result = loader.load_settings_from_disk()
        assert result.settings.model == "flag-model"
        assert result.settings.temperature == 0.8

    def test_policy_settings_highest_priority(self):
        plugin_settings = SettingsJson(model="plugin-model")
        flag_settings = SettingsJson(model="flag-model")
        policy_settings = SettingsJson(model="policy-model", temperature=0.1)
        loader = SettingsLoader(
            plugin_settings=plugin_settings,
            flag_settings=flag_settings,
            policy_settings=policy_settings,
        )
        result = loader.load_settings_from_disk()
        assert result.settings.model == "policy-model"
        assert result.settings.temperature == 0.1

    def test_is_source_trusted(self):
        loader = SettingsLoader()

        assert loader.is_source_trusted("userSettings") is True
        assert loader.is_source_trusted("flagSettings") is True
        assert loader.is_source_trusted("policySettings") is True

        assert loader.is_source_trusted("projectSettings") is False
        assert loader.is_source_trusted("localSettings") is False
        assert loader.is_source_trusted("pluginSettings") is False

    def test_get_safe_env_vars_trusted_source(self):
        settings = SettingsJson(
            env={
                "API_KEY": "secret",
                "PATH": "/usr/bin",
            }
        )
        loader = SettingsLoader(plugin_settings=settings)
        loader._cache = SettingsWithErrors(settings=settings)

        env = loader.get_safe_env_vars("userSettings")
        assert env == {"API_KEY": "secret", "PATH": "/usr/bin"}

    def test_get_safe_env_vars_untrusted_source(self):
        settings = SettingsJson(
            env={
                "API_KEY": "secret",
                "PATH": "/usr/bin",
            }
        )
        loader = SettingsLoader(plugin_settings=settings)
        loader._cache = SettingsWithErrors(settings=settings)

        env = loader.get_safe_env_vars("projectSettings")
        assert "API_KEY" not in env
        assert env == {"PATH": "/usr/bin"}

    def test_get_settings_cached(self):
        loader = SettingsLoader()
        result1 = loader.get_settings()
        result2 = loader.get_settings()
        assert result1 == result2


class TestSettingSourcesOrder:
    """Tests for SETTING_SOURCES_ORDER."""

    def test_order_correct(self):
        assert SETTING_SOURCES_ORDER == [
            "pluginSettings",
            "userSettings",
            "projectSettings",
            "localSettings",
            "flagSettings",
            "policySettings",
        ]

    def test_policy_is_last(self):
        assert SETTING_SOURCES_ORDER[-1] == "policySettings"


class TestTrustedSettingSources:
    """Tests for TRUSTED_SETTING_SOURCES."""

    def test_trusted_sources(self):
        assert "userSettings" in TRUSTED_SETTING_SOURCES
        assert "flagSettings" in TRUSTED_SETTING_SOURCES
        assert "policySettings" in TRUSTED_SETTING_SOURCES

    def test_untrusted_sources_not_included(self):
        assert "projectSettings" not in TRUSTED_SETTING_SOURCES
        assert "localSettings" not in TRUSTED_SETTING_SOURCES
        assert "pluginSettings" not in TRUSTED_SETTING_SOURCES


class TestGlobalLoader:
    """Tests for global loader functions."""

    def test_get_settings_loader(self):
        reset_settings_loader()
        loader = get_settings_loader()
        assert isinstance(loader, SettingsLoader)

    def test_reset_settings_loader(self):
        loader1 = get_settings_loader()
        reset_settings_loader()
        loader2 = get_settings_loader()
        assert loader1 is not loader2
