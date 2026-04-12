from __future__ import annotations

from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator


def _resolve_path(base_dir: Path, raw_path: str) -> str:
    path = Path(raw_path)
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return str(path)


class ModelConfig(BaseModel):
    model_name: str = "gpt-4.1-mini"
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 1.0
    top_p: float = 0.95
    stream: bool = True
    max_tokens: int | None = None
    timeout: float = 120.0
    fallbacks: list[str] = Field(
        default_factory=list,
        description="List of fallback model names to try when the primary model fails "
                    "(e.g. on 429/500/503 errors).",
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
            raise ValueError(
                "browser.cdp_url is required when browser.mode=connect_over_cdp"
            )
        return self


class EngagementConfig(BaseModel):
    name: str = "web-assessment"
    authorization: str = ""
    start_url: str = ""
    allowed_hosts: list[str] = Field(default_factory=list)
    allow_subdomains: bool = True
    max_requests: int = 200
    notes: str | None = None

    @model_validator(mode="after")
    def infer_allowed_hosts(self) -> "EngagementConfig":
        if self.start_url and not self.allowed_hosts:
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
    index_url: str | None = None
    extra_index_urls: list[str] = Field(default_factory=list)
    trusted_hosts: list[str] = Field(default_factory=list)
    bootstrap_packages: list[str] = Field(
        default_factory=lambda: [
            "requests",
            "httpx",
            "beautifulsoup4",
            "lxml",
            "pyyaml",
        ]
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
        self.bootstrap_packages = [
            item.strip() for item in self.bootstrap_packages if item.strip()
        ]
        return self


class AgentConfig(BaseModel):
    max_iters: int = 12
    max_subtasks: int = 8
    parallel_tool_calls: bool = False
    enable_meta_tool: bool = True
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
        self.sandbox.shared_root_dir = _resolve_path(
            base_dir, self.sandbox.shared_root_dir
        )
        self.skills.directories = [
            _resolve_path(base_dir, item) for item in self.skills.directories
        ]
        if self.browser.executable_path:
            self.browser.executable_path = _resolve_path(
                base_dir, self.browser.executable_path
            )
        return self


__all__ = [
    "ModelConfig",
    "BrowserConfig",
    "EngagementConfig",
    "SkillsConfig",
    "ArtifactConfig",
    "SandboxConfig",
    "AgentConfig",
    "CompactionConfig",
    "AppConfig",
]
