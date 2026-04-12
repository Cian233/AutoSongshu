"""Centralized exception hierarchy for AutoSongshu.

All domain-specific exceptions inherit from :class:`AutoSongshuError` so that
callers can catch the entire family with a single ``except AutoSongshuError``.
"""


class AutoSongshuError(Exception):
    """Base exception for all AutoSongshu errors."""

    def __init__(self, message: str = "", *, detail: str = "") -> None:
        self.detail = detail
        full = f"{message}: {detail}" if detail else message
        super().__init__(full)


class ConfigurationError(AutoSongshuError):
    """Raised when the configuration is invalid or missing required values."""


class ScopeViolationError(AutoSongshuError):
    """Raised when an operation targets a resource outside the authorized scope."""

    def __init__(self, url: str, *, reason: str = "") -> None:
        self.url = url
        super().__init__(f"Scope violation for {url}", detail=reason)


class BrowserConnectionError(AutoSongshuError):
    """Raised when the browser cannot be launched or connected to."""


class BrowserOperationError(AutoSongshuError):
    """Raised when a browser operation (navigate, click, etc.) fails."""


class SandboxExecutionError(AutoSongshuError):
    """Raised when code execution inside the sandbox fails."""

    def __init__(
        self,
        message: str = "Sandbox execution failed",
        *,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(message)


class ToolExecutionError(AutoSongshuError):
    """Raised when a tool invocation fails."""

    def __init__(
        self,
        tool_name: str,
        message: str = "Tool execution failed",
        *,
        arguments: dict | None = None,
    ) -> None:
        self.tool_name = tool_name
        self.arguments = arguments
        super().__init__(f"[{tool_name}] {message}")


class KnowledgeStoreError(AutoSongshuError):
    """Raised when a knowledge-base operation fails."""


class PermissionDeniedError(AutoSongshuError):
    """Raised when a tool is blocked by the permission system."""

    def __init__(self, tool_name: str, *, reason: str = "blocked") -> None:
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' denied", detail=reason)


class SessionNotFoundError(AutoSongshuError):
    """Raised when a referenced session does not exist."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Session not found: {session_id}")


__all__ = [
    "AutoSongshuError",
    "ConfigurationError",
    "ScopeViolationError",
    "BrowserConnectionError",
    "BrowserOperationError",
    "SandboxExecutionError",
    "ToolExecutionError",
    "KnowledgeStoreError",
    "PermissionDeniedError",
    "SessionNotFoundError",
]
