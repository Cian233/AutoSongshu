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


class ModelProfileConfig(BaseModel):
    """A single model profile in the multi-model config."""
    name: str = "default"
    display_name: str = ""
    provider: str = "custom"
    model_name: str = ""
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 1.0
    top_p: float = 0.95
    max_tokens: int | None = None
    timeout: float = 120.0
    stream: bool = True
    tasks: list[str] = Field(default_factory=lambda: ["general"])
    enabled: bool = True
    cost_per_1m_input: float = 0.0
    cost_per_1m_output: float = 0.0


class ModelConfig(BaseModel):
    # ── Legacy single-model fields (backward compatible) ──
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

    # ── Multi-model fields ──
    active: str | None = None
    profiles: list[ModelProfileConfig] = Field(
        default_factory=list,
        description="List of model profiles for multi-model routing.",
    )


class SubAgentModelConfig(BaseModel):
    """Independent model configuration for sub-agents."""
    recon_model: str | None = Field(
        default=None,
        description="Model for reconnaissance sub-agent.",
    )
    scanner_model: str | None = Field(
        default=None,
        description="Model for vulnerability scanning sub-agent.",
    )
    exploit_model: str | None = Field(
        default=None,
        description="Model for exploit development sub-agent.",
    )
    report_model: str | None = Field(
        default=None,
        description="Model for report generation sub-agent.",
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
    # OpenCode-aligned timeout strategy (inspired by opencode's bash tool timeout)
    # Default bash timeout in opencode: 2 minutes (120s)
    bootstrap_timeout_sec: int = 120
    install_timeout_sec: int = 300
    execution_timeout_sec: int = 120  # Default: 2 min (matches opencode's DEFAULT_TIMEOUT)
    max_execution_timeout_sec: int = 600  # Max allowed: 10 min (for heavy tasks)
    # Output truncation (opencode: MAX_BYTES = 50KB, MAX_LINES = 2000)
    max_output_bytes: int = 50 * 1024  # 50KB
    max_output_lines: int = 2000
    # Heartbeat detection (detect hung processes)
    heartbeat_interval_sec: int = 30  # Check every 30s for long-running tasks
    # Auto-retry on transient timeout
    retry_on_timeout: bool = False  # Disabled by default for safety
    max_timeout_retries: int = 1
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
    # Timeout configuration (inspired by OpenCode's timeout strategy)
    turn_timeout_sec: int = 600  # Per-turn timeout (10 min default, for complex reasoning)
    tool_call_timeout_sec: int = 300  # Per-tool-call timeout (5 min default)
    max_total_timeout_sec: int = 3600  # Max total session timeout (60 min default)


class CompactionConfig(BaseModel):
    auto: bool = True
    prune: bool = True
    trigger_chars: int = 18000
    reserved_chars: int = 4000
    min_turns: int = 4
    retain_recent_turns: int = 2
    # Large file handling
    max_file_read_chars: int = 24000  # Increased from 12000 for large files
    enable_chunked_read: bool = True  # Enable offset/limit based file reading


class ProjectConfig(BaseModel):
    """Project-level configuration for multi-session workspace sharing.

    Inspired by Codex/OpenCode project-based architecture:
    - One project can have multiple sessions
    - All sessions share a project-level workspace (files, scripts, outputs)
    - Each session has its own conversation artifacts (memory, trajectories)
    - Sandbox venv is shared across all sessions in the project
    """
    project_id: str = ""  # Auto-generated if empty
    name: str = ""
    workspace_dir: str = "./workspace"  # Project-level shared workspace
    artifacts_dir: str = "./artifacts"  # Project-level artifacts root
    # Isolation mode for sandbox:
    # - "session": each session has its own sandbox workspace (legacy)
    # - "user": sandbox workspace shared by user (current default)
    # - "project": sandbox workspace shared by project (Codex-style)
    isolation_mode: Literal["session", "user", "project"] = "project"


class AppConfig(BaseModel):
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    model: ModelConfig
    sub_agent_models: SubAgentModelConfig = Field(default_factory=SubAgentModelConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    engagement: EngagementConfig
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    artifacts: ArtifactConfig = Field(default_factory=ArtifactConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    mcp_servers: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def resolve_paths(self, base_dir: Path) -> "AppConfig":
        self.project.workspace_dir = _resolve_path(base_dir, self.project.workspace_dir)
        self.project.artifacts_dir = _resolve_path(base_dir, self.project.artifacts_dir)
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
    "SubAgentModelConfig",
    "BrowserConfig",
    "EngagementConfig",
    "SkillsConfig",
    "ArtifactConfig",
    "SandboxConfig",
    "AgentConfig",
    "CompactionConfig",
    "AppConfig",
]
