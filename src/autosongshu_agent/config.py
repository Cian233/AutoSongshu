from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator


_ENV_ONLY_PATTERN = re.compile(r"^\$(?:\{[A-Za-z_][A-Za-z0-9_]*\}|[A-Za-z_][A-Za-z0-9_]*)$")
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
    ("browser", "fallback_to_launch_on_cdp_error"): ("AUTOSONGSHU_BROWSER_FALLBACK_TO_LAUNCH_ON_CDP_ERROR",),
    ("browser", "channel"): ("AUTOSONGSHU_BROWSER_CHANNEL",),
    ("browser", "executable_path"): ("AUTOSONGSHU_BROWSER_EXECUTABLE_PATH",),
    ("browser", "headless"): ("AUTOSONGSHU_BROWSER_HEADLESS",),
    ("browser", "ignore_https_errors"): ("AUTOSONGSHU_BROWSER_IGNORE_HTTPS_ERRORS",),
    ("browser", "timeout_ms"): ("AUTOSONGSHU_BROWSER_TIMEOUT_MS",),
    ("browser", "viewport_width"): ("AUTOSONGSHU_BROWSER_VIEWPORT_WIDTH",),
    ("browser", "viewport_height"): ("AUTOSONGSHU_BROWSER_VIEWPORT_HEIGHT",),
    ("engagement", "name"): ("AUTOSONGSHU_ENGAGEMENT_NAME",),
    ("engagement", "authorization"): ("AUTOSONGSHU_ENGAGEMENT_AUTHORIZATION", "AUTOSONGSHU_AUTHORIZATION"),
    ("engagement", "start_url"): ("AUTOSONGSHU_ENGAGEMENT_START_URL", "AUTOSONGSHU_SCOPE_START_URL"),
    ("engagement", "allowed_hosts"): ("AUTOSONGSHU_ENGAGEMENT_ALLOWED_HOSTS", "AUTOSONGSHU_SCOPE_ALLOWED_HOSTS"),
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
    ("sandbox", "allow_package_install"): ("AUTOSONGSHU_SANDBOX_ALLOW_PACKAGE_INSTALL",),
    ("sandbox", "bootstrap_timeout_sec"): ("AUTOSONGSHU_SANDBOX_BOOTSTRAP_TIMEOUT_SEC",),
    ("sandbox", "install_timeout_sec"): ("AUTOSONGSHU_SANDBOX_INSTALL_TIMEOUT_SEC",),
    ("sandbox", "execution_timeout_sec"): ("AUTOSONGSHU_SANDBOX_EXECUTION_TIMEOUT_SEC",),
    ("sandbox", "index_url"): ("AUTOSONGSHU_SANDBOX_INDEX_URL", "UV_INDEX_URL", "PIP_INDEX_URL"),
    ("sandbox", "extra_index_urls"): (
        "AUTOSONGSHU_SANDBOX_EXTRA_INDEX_URLS",
        "UV_EXTRA_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
    ),
    ("sandbox", "trusted_hosts"): ("AUTOSONGSHU_SANDBOX_TRUSTED_HOSTS", "PIP_TRUSTED_HOST"),
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
    ("compaction", "retain_recent_turns"): ("AUTOSONGSHU_COMPACTION_RETAIN_RECENT_TURNS",),
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


def _resolve_path(base_dir: Path, raw_path: str) -> str:
    path = Path(raw_path)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


def _find_env_file(start_dir: Path) -> Path | None:
    for directory in [start_dir, *start_dir.parents]:
        candidate = directory / ".env"
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
    loaded: set[Path] = set()
    for start_dir in (config_path.parent.resolve(), Path.cwd().resolve()):
        env_file = _find_env_file(start_dir)
        if env_file and env_file not in loaded:
            load_dotenv(env_file, override=False)
            loaded.add(env_file)


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


class ModelConfig(BaseModel):
    model_name: str = Field(
        default_factory=lambda: _get_first_env(
            "AUTOSONGSHU_MODEL_NAME",
        )
        or "gpt-4.1-mini",
    )
    api_key: str | None = Field(
        default_factory=lambda: _get_first_env(
            "AUTOSONGSHU_MODEL_API_KEY",
        ),
    )
    base_url: str | None = Field(
        default_factory=lambda: _get_first_env(
            "AUTOSONGSHU_MODEL_BASE_URL",
        ),
    )
    temperature: float = Field(
        default_factory=lambda: float(_get_first_env("AUTOSONGSHU_MODEL_TEMPERATURE") or 1.0),
    )
    top_p: float = Field(
        default_factory=lambda: float(_get_first_env("AUTOSONGSHU_MODEL_TOP_P") or 0.95),
    )
    stream: bool = Field(
        default_factory=lambda: _parse_bool(_get_first_env("AUTOSONGSHU_MODEL_STREAM") or "true"),
    )
    max_tokens: int | None = Field(
        default_factory=lambda: (
            int(value) if (value := _get_first_env("AUTOSONGSHU_MODEL_MAX_TOKENS")) else None
        ),
    )
    timeout: float = Field(
        default_factory=lambda: float(_get_first_env("AUTOSONGSHU_MODEL_TIMEOUT") or 120.0),
    )


class BrowserConfig(BaseModel):
    mode: Literal["launch", "connect_over_cdp"] = "launch"
    cdp_url: str | None = None
    fallback_to_launch_on_cdp_error: bool = True
    channel: str | None = None
    executable_path: str | None = None
    headless: bool = True
    ignore_https_errors: bool = True
    timeout_ms: int = 12000
    viewport_width: int = 1440
    viewport_height: int = 900

    @model_validator(mode="after")
    def validate_browser_mode(self) -> "BrowserConfig":
        if self.mode == "connect_over_cdp" and not self.cdp_url:
            raise ValueError("browser.cdp_url is required when browser.mode=connect_over_cdp")
        return self


class EngagementConfig(BaseModel):
    name: str = "authorized-web-assessment"
    authorization: str = "REQUIRED"
    start_url: str
    allowed_hosts: list[str] = Field(default_factory=list)
    allow_subdomains: bool = True
    max_requests: int = 200
    notes: str | None = None

    @model_validator(mode="after")
    def infer_allowed_hosts(self) -> "EngagementConfig":
        if not self.allowed_hosts:
            parsed = urlparse(self.start_url)
            if parsed.hostname:
                self.allowed_hosts = [parsed.hostname]
        return self


class SkillsConfig(BaseModel):
    enabled: bool = True
    directories: list[str] = Field(default_factory=list)


class ArtifactConfig(BaseModel):
    root_dir: str = "./artifacts"
    persist_network_log: bool = True
    persist_console_log: bool = True


class SandboxConfig(BaseModel):
    enabled: bool = True
    isolation_mode: Literal["session", "user"] = "user"
    shared_root_dir: str = "./data/sandboxes"
    default_user_id: str = "local-default-user"
    root_subdir: str = "sandbox"
    workspace_subdir: str = "workspace"
    venv_subdir: str = ".venv"
    allow_package_install: bool = True
    bootstrap_timeout_sec: int = 120
    install_timeout_sec: int = 300
    execution_timeout_sec: int = 120
    index_url: str | None = Field(
        default_factory=lambda: _get_first_env(
            "AUTOSONGSHU_SANDBOX_INDEX_URL",
            "UV_INDEX_URL",
            "PIP_INDEX_URL",
        ),
    )
    extra_index_urls: list[str] = Field(
        default_factory=lambda: _parse_env_list(
            _get_first_env(
                "AUTOSONGSHU_SANDBOX_EXTRA_INDEX_URLS",
                "UV_EXTRA_INDEX_URL",
                "PIP_EXTRA_INDEX_URL",
            ),
        ),
    )
    trusted_hosts: list[str] = Field(
        default_factory=lambda: _parse_env_list(
            _get_first_env(
                "AUTOSONGSHU_SANDBOX_TRUSTED_HOSTS",
                "PIP_TRUSTED_HOST",
            ),
        ),
    )
    bootstrap_packages: list[str] = Field(
        default_factory=lambda: _parse_env_list(_get_first_env("AUTOSONGSHU_SANDBOX_BOOTSTRAP_PACKAGES"))
        or ["requests", "httpx", "beautifulsoup4", "lxml", "pyyaml"],
    )

    @model_validator(mode="after")
    def validate_subdirs(self) -> "SandboxConfig":
        if not self.default_user_id.strip():
            raise ValueError("sandbox.default_user_id must not be empty")
        for field_name in ("root_subdir", "workspace_subdir", "venv_subdir"):
            raw_value = getattr(self, field_name)
            if not raw_value.strip():
                raise ValueError(f"sandbox.{field_name} must not be empty")
            if Path(raw_value).is_absolute():
                raise ValueError(f"sandbox.{field_name} must be a relative path")
        self.bootstrap_packages = [item.strip() for item in self.bootstrap_packages if item.strip()]
        return self


class AgentConfig(BaseModel):
    max_iters: int = 12
    max_subtasks: int = 8
    parallel_tool_calls: bool = False
    enable_meta_tool: bool = False
    loop_guard_enabled: bool = True
    mode: Literal["auto", "semi-auto"] = "auto"


class CompactionConfig(BaseModel):
    auto: bool = True
    prune: bool = True
    trigger_chars: int = 18000
    reserved_chars: int = 4000
    min_turns: int = 4
    retain_recent_turns: int = 2


class AppConfig(BaseModel):
    model: ModelConfig
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    engagement: EngagementConfig
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    artifacts: ArtifactConfig = Field(default_factory=ArtifactConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    mcp_servers: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def resolve_paths(self, base_dir: Path) -> "AppConfig":
        self.artifacts.root_dir = _resolve_path(base_dir, self.artifacts.root_dir)
        self.sandbox.shared_root_dir = _resolve_path(base_dir, self.sandbox.shared_root_dir)
        self.skills.directories = [
            _resolve_path(base_dir, item) for item in self.skills.directories
        ]
        if self.browser.executable_path:
            self.browser.executable_path = _resolve_path(base_dir, self.browser.executable_path)
        return self


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).resolve()
    _load_env_files(config_path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    expanded = _expand_env_values(raw)
    expanded = _apply_env_overrides(expanded)
    config = AppConfig.model_validate(expanded)
    return config.resolve_paths(config_path.parent)
