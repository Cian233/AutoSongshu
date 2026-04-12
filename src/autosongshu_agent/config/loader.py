from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from .models import AppConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global config cache & reload lock
# ---------------------------------------------------------------------------
_config_cache: dict[str, AppConfig] = {}
_config_lock = threading.Lock()


_ENV_ONLY_PATTERN = re.compile(
    r"^\$(?:\{[A-Za-z_][A-Za-z0-9_]*\}|[A-Za-z_][A-Za-z0-9_]*)$"
)
_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_ENV_OVERRIDES: dict[tuple[str, ...], tuple[str, ...]] = {
    ("model", "model_name"): ("AUTOSONGSHU_MODEL_NAME",),
    ("model", "api_key"): ("AUTOSONGSHU_MODEL_API_KEY",),
    ("model", "base_url"): ("AUTOSONGSHU_MODEL_BASE_URL",),
    ("model", "temperature"): ("AUTOSONGSHU_MODEL_TEMPERATURE",),
    ("model", "top_p"): ("AUTOSONGSHU_MODEL_TOP_P",),
    ("model", "stream"): ("AUTOSONGSHU_MODEL_STREAM",),
    ("model", "max_tokens"): ("AUTOSONGSHU_MODEL_MAX_TOKENS",),
    ("model", "timeout"): ("AUTOSONGSHU_MODEL_TIMEOUT",),
    ("browser", "mode"): ("AUTOSONGSHU_BROWSER_MODE",),
    ("browser", "cdp_url"): ("AUTOSONGSHU_BROWSER_CDP_URL",),
    ("browser", "fallback_to_launch_on_cdp_error"): (
        "AUTOSONGSHU_BROWSER_FALLBACK_TO_LAUNCH_ON_CDP_ERROR",
    ),
    ("browser", "channel"): ("AUTOSONGSHU_BROWSER_CHANNEL",),
    ("browser", "executable_path"): ("AUTOSONGSHU_BROWSER_EXECUTABLE_PATH",),
    ("browser", "headless"): ("AUTOSONGSHU_BROWSER_HEADLESS",),
    ("browser", "ignore_https_errors"): ("AUTOSONGSHU_BROWSER_IGNORE_HTTPS_ERRORS",),
    ("browser", "timeout_ms"): ("AUTOSONGSHU_BROWSER_TIMEOUT_MS",),
    ("browser", "viewport_width"): ("AUTOSONGSHU_BROWSER_VIEWPORT_WIDTH",),
    ("browser", "viewport_height"): ("AUTOSONGSHU_BROWSER_VIEWPORT_HEIGHT",),
    ("engagement", "name"): ("AUTOSONGSHU_ENGAGEMENT_NAME",),
    ("engagement", "authorization"): (
        "AUTOSONGSHU_ENGAGEMENT_AUTHORIZATION",
        "AUTOSONGSHU_AUTHORIZATION",
    ),
    ("engagement", "start_url"): (
        "AUTOSONGSHU_ENGAGEMENT_START_URL",
        "AUTOSONGSHU_SCOPE_START_URL",
    ),
    ("engagement", "allowed_hosts"): (
        "AUTOSONGSHU_ENGAGEMENT_ALLOWED_HOSTS",
        "AUTOSONGSHU_SCOPE_ALLOWED_HOSTS",
    ),
    ("engagement", "allow_subdomains"): (
        "AUTOSONGSHU_ENGAGEMENT_ALLOW_SUBDOMAINS",
        "AUTOSONGSHU_SCOPE_ALLOW_SUBDOMAINS",
    ),
    ("engagement", "max_requests"): ("AUTOSONGSHU_ENGAGEMENT_MAX_REQUESTS",),
    ("engagement", "notes"): ("AUTOSONGSHU_ENGAGEMENT_NOTES",),
    ("skills", "enabled"): ("AUTOSONGSHU_SKILLS_ENABLED",),
    ("skills", "directories"): ("AUTOSONGSHU_SKILLS_DIRECTORIES",),
    ("artifacts", "root_dir"): ("AUTOSONGSHU_ARTIFACT_ROOT_DIR",),
    ("artifacts", "persist_network_log"): ("AUTOSONGSHU_ARTIFACT_PERSIST_NETWORK_LOG",),
    ("artifacts", "persist_console_log"): ("AUTOSONGSHU_ARTIFACT_PERSIST_CONSOLE_LOG",),
    ("sandbox", "enabled"): ("AUTOSONGSHU_SANDBOX_ENABLED",),
    ("sandbox", "isolation_mode"): ("AUTOSONGSHU_SANDBOX_ISOLATION_MODE",),
    ("sandbox", "shared_root_dir"): ("AUTOSONGSHU_SANDBOX_SHARED_ROOT_DIR",),
    ("sandbox", "default_user_id"): ("AUTOSONGSHU_SANDBOX_DEFAULT_USER_ID",),
    ("sandbox", "root_subdir"): ("AUTOSONGSHU_SANDBOX_ROOT_SUBDIR",),
    ("sandbox", "workspace_subdir"): ("AUTOSONGSHU_SANDBOX_WORKSPACE_SUBDIR",),
    ("sandbox", "venv_subdir"): ("AUTOSONGSHU_SANDBOX_VENV_SUBDIR",),
    ("sandbox", "allow_package_install"): (
        "AUTOSONGSHU_SANDBOX_ALLOW_PACKAGE_INSTALL",
    ),
    ("sandbox", "bootstrap_timeout_sec"): (
        "AUTOSONGSHU_SANDBOX_BOOTSTRAP_TIMEOUT_SEC",
    ),
    ("sandbox", "install_timeout_sec"): ("AUTOSONGSHU_SANDBOX_INSTALL_TIMEOUT_SEC",),
    ("sandbox", "execution_timeout_sec"): (
        "AUTOSONGSHU_SANDBOX_EXECUTION_TIMEOUT_SEC",
    ),
    ("sandbox", "index_url"): (
        "AUTOSONGSHU_SANDBOX_INDEX_URL",
        "UV_INDEX_URL",
        "PIP_INDEX_URL",
    ),
    ("sandbox", "extra_index_urls"): (
        "AUTOSONGSHU_SANDBOX_EXTRA_INDEX_URLS",
        "UV_EXTRA_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
    ),
    ("sandbox", "trusted_hosts"): (
        "AUTOSONGSHU_SANDBOX_TRUSTED_HOSTS",
        "PIP_TRUSTED_HOST",
    ),
    ("sandbox", "bootstrap_packages"): ("AUTOSONGSHU_SANDBOX_BOOTSTRAP_PACKAGES",),
    ("agent", "max_iters"): ("AUTOSONGSHU_AGENT_MAX_ITERS",),
    ("agent", "max_subtasks"): ("AUTOSONGSHU_AGENT_MAX_SUBTASKS",),
    ("agent", "parallel_tool_calls"): ("AUTOSONGSHU_AGENT_PARALLEL_TOOL_CALLS",),
    ("agent", "enable_meta_tool"): ("AUTOSONGSHU_AGENT_ENABLE_META_TOOL",),
    ("agent", "loop_guard_enabled"): ("AUTOSONGSHU_AGENT_LOOP_GUARD_ENABLED",),
    ("compaction", "auto"): ("AUTOSONGSHU_COMPACTION_AUTO",),
    ("compaction", "prune"): ("AUTOSONGSHU_COMPACTION_PRUNE",),
    ("compaction", "trigger_chars"): ("AUTOSONGSHU_COMPACTION_TRIGGER_CHARS",),
    ("compaction", "reserved_chars"): ("AUTOSONGSHU_COMPACTION_RESERVED_CHARS",),
    ("compaction", "min_turns"): ("AUTOSONGSHU_COMPACTION_MIN_TURNS",),
    ("compaction", "retain_recent_turns"): (
        "AUTOSONGSHU_COMPACTION_RETAIN_RECENT_TURNS",
    ),
}
_BOOL_ENV_FIELDS: set[tuple[str, ...]] = {
    ("model", "stream"),
    ("browser", "fallback_to_launch_on_cdp_error"),
    ("browser", "headless"),
    ("browser", "ignore_https_errors"),
    ("engagement", "allow_subdomains"),
    ("skills", "enabled"),
    ("artifacts", "persist_network_log"),
    ("artifacts", "persist_console_log"),
    ("sandbox", "enabled"),
    ("sandbox", "allow_package_install"),
    ("agent", "parallel_tool_calls"),
    ("agent", "enable_meta_tool"),
    ("agent", "loop_guard_enabled"),
    ("compaction", "auto"),
    ("compaction", "prune"),
}
_INT_ENV_FIELDS: set[tuple[str, ...]] = {
    ("model", "max_tokens"),
    ("browser", "timeout_ms"),
    ("browser", "viewport_width"),
    ("browser", "viewport_height"),
    ("engagement", "max_requests"),
    ("sandbox", "bootstrap_timeout_sec"),
    ("sandbox", "install_timeout_sec"),
    ("sandbox", "execution_timeout_sec"),
    ("agent", "max_iters"),
    ("agent", "max_subtasks"),
    ("compaction", "trigger_chars"),
    ("compaction", "reserved_chars"),
    ("compaction", "min_turns"),
    ("compaction", "retain_recent_turns"),
}
_FLOAT_ENV_FIELDS: set[tuple[str, ...]] = {
    ("model", "temperature"),
    ("model", "top_p"),
    ("model", "timeout"),
}
_LIST_ENV_FIELDS: set[tuple[str, ...]] = {
    ("engagement", "allowed_hosts"),
    ("skills", "directories"),
    ("sandbox", "extra_index_urls"),
    ("sandbox", "trusted_hosts"),
    ("sandbox", "bootstrap_packages"),
}


def _expand_env_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand_env_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env_values(item) for item in value]
    if isinstance(value, str):
        expanded = os.path.expandvars(value)
        if expanded == value and _ENV_ONLY_PATTERN.fullmatch(value):
            return None
        return expanded
    return value


def _find_env_file(start_dir: Path) -> Path | None:
    candidate = start_dir / ".env"
    if candidate.is_file():
        return candidate
    return None


def load_project_env(project_root: Path, *, override: bool = False) -> Path | None:
    env_file = (project_root / ".env").resolve()
    if env_file.is_file():
        load_dotenv(env_file, override=override)
        return env_file
    return None


def _load_env_files(config_path: Path) -> None:
    env_file = _find_env_file(config_path.parent.resolve())
    if env_file:
        load_dotenv(env_file, override=False)


def _get_first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return None


def _parse_bool(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(f"Invalid boolean env value: {raw!r}")


def _parse_env_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    stripped = str(raw).strip()
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    normalized = stripped.replace("\r\n", "\n").replace(";", "\n").replace(",", "\n")
    return [item.strip() for item in normalized.split("\n") if item.strip()]


def _coerce_env_value(path: tuple[str, ...], raw: str) -> Any:
    if path in _BOOL_ENV_FIELDS:
        return _parse_bool(raw)
    if path in _INT_ENV_FIELDS:
        return int(raw)
    if path in _FLOAT_ENV_FIELDS:
        return float(raw)
    if path in _LIST_ENV_FIELDS:
        return _parse_env_list(raw)
    return raw


def _set_nested_value(raw: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor: dict[str, Any] = raw
    for depth, key in enumerate(path[:-1], start=1):
        next_cursor = cursor.get(key)
        if next_cursor is None:
            next_cursor = {}
            cursor[key] = next_cursor
        if not isinstance(next_cursor, dict):
            section = ".".join(path[:depth])
            raise ValueError(f"The '{section}' section must be a mapping.")
        cursor = next_cursor
    cursor[path[-1]] = value


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    for path, env_names in _ENV_OVERRIDES.items():
        value = _get_first_env(*env_names)
        if value is None:
            continue
        _set_nested_value(raw, path, _coerce_env_value(path, value))
    return raw


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    _load_env_files(config_path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    expanded = _expand_env_values(raw)
    expanded = _apply_env_overrides(expanded)
    config = AppConfig.model_validate(expanded)
    resolved = config.resolve_paths(config_path.parent)
    # Cache the resolved config for later reloads
    with _config_lock:
        _config_cache[str(config_path)] = resolved
    return resolved


def reload_config(path: str | Path) -> AppConfig:
    """Reload configuration from a YAML file, with thread-safety and error handling.

    This re-reads the YAML file from disk, re-applies environment variable
    overrides, validates the result, and updates the global config cache.
    Existing sessions that already hold a reference to the old ``AppConfig``
    instance are **not** affected -- only future ``load_config`` / ``reload_config``
    calls and callers that explicitly request the reloaded config will see the
    new values.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        The newly loaded :class:`AppConfig`.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the YAML content is invalid.
    """
    config_path = Path(path).resolve()

    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with _config_lock:
        try:
            # Re-read env files so that .env changes are picked up
            _load_env_files(config_path)
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            expanded = _expand_env_values(raw)
            expanded = _apply_env_overrides(expanded)
            config = AppConfig.model_validate(expanded)
            resolved = config.resolve_paths(config_path.parent)
            _config_cache[str(config_path)] = resolved
            logger.info("Configuration reloaded successfully from %s", config_path)
            return resolved
        except (yaml.YAMLError, ValueError) as exc:
            logger.error(
                "Failed to reload configuration from %s: %s", config_path, exc
            )
            raise
        except Exception as exc:
            logger.error(
                "Unexpected error reloading configuration from %s: %s",
                config_path,
                exc,
            )
            raise ValueError(
                f"Unexpected error reloading config: {exc}"
            ) from exc


def save_config(path: str | Path, config: AppConfig) -> None:
    """Persist an ``AppConfig`` back to a YAML file.

    This performs a **shallow merge**: the raw YAML dict currently on disk
    is loaded, the ``model`` section is replaced with the serialised form of
    ``config.model``, and the result is written back.  All other top-level
    sections (agent, sandbox, skills, …) are left untouched.

    Sensitive fields (``api_key``) that were originally stored as
    ``${ENV_VAR}`` references are preserved as-is when the value has not
    changed.

    Args:
        path: Path to the YAML configuration file.
        config: The ``AppConfig`` to persist.
    """
    config_path = Path(path).resolve()

    # Read existing raw YAML
    existing_raw: dict[str, Any] = {}
    if config_path.exists():
        try:
            existing_raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            existing_raw = {}

    # Build the model section to write
    model = config.model
    model_dict: dict[str, Any] = {}

    # Preserve env-var references for api_key if the current value matches
    existing_model = existing_raw.get("model", {})
    _preserve_env_ref(model_dict, existing_model, "api_key", model.api_key)

    model_dict["model_name"] = model.model_name
    if model.base_url:
        _preserve_env_ref(model_dict, existing_model, "base_url", model.base_url)
    model_dict["temperature"] = model.temperature
    model_dict["top_p"] = model.top_p
    if model.max_tokens is not None:
        model_dict["max_tokens"] = model.max_tokens
    model_dict["timeout"] = model.timeout
    model_dict["stream"] = model.stream
    if model.fallbacks:
        model_dict["fallbacks"] = model.fallbacks

    # Multi-model fields
    if model.active:
        model_dict["active"] = model.active
    if model.profiles:
        model_dict["profiles"] = model.profiles

    # Merge into existing config
    existing_raw["model"] = model_dict

    # Persist compaction section if non-default values exist
    compaction = config.compaction
    compaction_dict: dict[str, Any] = {}
    _COMPACTION_DEFAULTS = {
        "auto": True, "prune": True, "trigger_chars": 18000,
        "reserved_chars": 4000, "min_turns": 4, "retain_recent_turns": 2,
        "context_window_tokens": 128000, "reserved_tokens": 8000,
        "compact_after_tokens": 90000, "compact_after_turns": 12,
        "keep_first_turns": 1, "keep_last_turns": 4, "use_token_counting": True,
    }
    for key, default in _COMPACTION_DEFAULTS.items():
        val = getattr(compaction, key, default)
        if val != default:
            compaction_dict[key] = val
    if compaction_dict:
        existing_raw["compaction"] = compaction_dict
    elif "compaction" in existing_raw:
        # Keep existing compaction section if we have nothing to change
        pass

    # Write back
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with _config_lock:
        config_path.write_text(
            yaml.dump(existing_raw, default_flow_style=False, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        # Update cache
        _config_cache[str(config_path)] = config
        logger.info("Configuration saved to %s", config_path)


def _preserve_env_ref(
    target: dict[str, Any],
    source: dict[str, Any],
    key: str,
    current_value: str | None,
) -> None:
    """If *source[key]* is an ``${ENV_VAR}`` reference and the resolved
    value matches *current_value*, keep the reference instead of the
    plain value."""
    raw_val = source.get(key)
    if isinstance(raw_val, str) and raw_val.startswith("${") and raw_val.endswith("}"):
        env_var = raw_val[2:-1]
        env_val = os.environ.get(env_var)
        if env_val and current_value and env_val == current_value:
            target[key] = raw_val
            return
    if current_value is not None:
        target[key] = current_value


def get_cached_config(path: str | Path) -> AppConfig | None:
    """Return the cached config for *path* if available, without re-reading disk."""
    key = str(Path(path).resolve())
    with _config_lock:
        return _config_cache.get(key)


__all__ = [
    "load_config",
    "load_project_env",
    "save_config",
    "_ENV_ONLY_PATTERN",
    "_TRUE_VALUES",
    "_FALSE_VALUES",
    "_ENV_OVERRIDES",
    "_BOOL_ENV_FIELDS",
    "_INT_ENV_FIELDS",
    "_FLOAT_ENV_FIELDS",
    "_LIST_ENV_FIELDS",
    "_expand_env_values",
    "_find_env_file",
    "_load_env_files",
    "_get_first_env",
    "_parse_bool",
    "_parse_env_list",
    "_coerce_env_value",
    "_set_nested_value",
    "_apply_env_overrides",
]
