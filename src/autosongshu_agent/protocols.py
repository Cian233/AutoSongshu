"""Abstract interfaces (Protocols) for key subsystems.

Using :mod:`typing.Protocol` allows any implementation to satisfy the
interface without inheriting from a common base class, making the system
easy to test and extend.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BrowserSession(Protocol):
    """Minimal interface that the browser subsystem must expose."""

    def start(self) -> None: ...
    def close(self) -> None: ...
    def navigate(self, url: str) -> dict[str, Any]: ...
    def current_url(self) -> str: ...
    def status(self) -> dict[str, Any]: ...
    def snapshot(self, **kwargs: Any) -> dict[str, Any]: ...
    def click(self, selector: str) -> dict[str, Any]: ...
    def fill(self, selector: str, text: str, *, submit: bool = False) -> dict[str, Any]: ...
    def screenshot(self, name: str = "page") -> str: ...


@runtime_checkable
class HttpClient(Protocol):
    """Minimal interface for the scoped HTTP client."""

    def request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]: ...
    def close(self) -> None: ...


@runtime_checkable
class Sandbox(Protocol):
    """Minimal interface for the Python execution sandbox."""

    def execute(self, code: str, *, timeout: int | None = None) -> dict[str, Any]: ...
    def close(self) -> None: ...


@runtime_checkable
class KnowledgeSearchProvider(Protocol):
    """Interface for knowledge-base search callbacks."""

    def __call__(
        self,
        knowledge_base_ids: list[str],
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]: ...


@runtime_checkable
class ToolCallCache(Protocol):
    """Interface for tool-call deduplication caches."""

    def reset_turn(self) -> None: ...
    def begin_call(self, signature: str) -> tuple[str, Any]: ...
    def complete_call(self, signature: str, response: Any, *, invalidates_cache: bool = False) -> None: ...
    def fail_call(self, signature: str, exc: Exception) -> None: ...
    def invalidate(self) -> None: ...


__all__ = [
    "BrowserSession",
    "HttpClient",
    "Sandbox",
    "KnowledgeSearchProvider",
    "ToolCallCache",
]
