from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from .artifacts import ArtifactStore, FindingStore
from .browser import CDPBrowserSession
from .config import AppConfig, ScopePolicy
from .http_client import ScopedHttpClient
from .sandbox import PythonSandbox
from .skills import SkillScriptRunner


@dataclass
class _PendingToolCall:
    event: threading.Event = field(default_factory=threading.Event)
    response: Any = None
    error: Exception | None = None


class PerTurnToolCallCache:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache: dict[str, Any] = {}
        self._pending: dict[str, _PendingToolCall] = {}

    def reset_turn(self) -> None:
        with self._lock:
            self._cache.clear()
            self._pending.clear()

    def begin_call(self, signature: str) -> tuple[str, Any]:
        with self._lock:
            if signature in self._cache:
                return "cached", deepcopy(self._cache[signature])

            pending = self._pending.get(signature)
            if pending is not None:
                return "wait", pending

            pending = _PendingToolCall()
            self._pending[signature] = pending
            return "execute", pending

    def wait_for_call(self, pending: _PendingToolCall) -> Any:
        pending.event.wait()
        if pending.error is not None:
            raise pending.error
        return deepcopy(pending.response)

    def complete_call(
        self, signature: str, response: Any, *, invalidates_cache: bool = False
    ) -> None:
        with self._lock:
            pending = self._pending.pop(signature, None)
            if invalidates_cache:
                self._cache.clear()
            self._cache[signature] = deepcopy(response)
            if pending is not None:
                pending.response = deepcopy(response)
                pending.event.set()

    def fail_call(self, signature: str, exc: Exception) -> None:
        with self._lock:
            pending = self._pending.pop(signature, None)
            if pending is not None:
                pending.error = exc
                pending.event.set()

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()


class PentestRuntime:
    def __init__(
        self,
        config: AppConfig,
        artifact_session_name: str | None = None,
        sandbox_user_id: str | None = None,
    ) -> None:
        self.config = config
        self.scope = ScopePolicy(
            start_url=config.engagement.start_url,
            allowed_hosts=config.engagement.allowed_hosts,
            allow_subdomains=config.engagement.allow_subdomains,
        )
        self.artifacts = ArtifactStore(
            root_dir=config.artifacts.root_dir,
            engagement_name=config.engagement.name,
            session_name=artifact_session_name,
        )
        self.findings = FindingStore(self.artifacts)
        self.http = ScopedHttpClient(
            scope=self.scope,
            artifacts=self.artifacts,
            ignore_https_errors=config.browser.ignore_https_errors,
            timeout=config.model.timeout,
            max_requests=config.engagement.max_requests,
        )
        self.browser = CDPBrowserSession(
            settings=config.browser,
            scope=self.scope,
            artifacts=self.artifacts,
        )
        self.sandbox = PythonSandbox(
            settings=config.sandbox,
            scope=self.scope,
            artifacts=self.artifacts,
            engagement_name=config.engagement.name,
            authorization=config.engagement.authorization,
            ignore_https_errors=config.browser.ignore_https_errors,
            user_id=sandbox_user_id,
        )
        self.skill_scripts = SkillScriptRunner(
            self.artifacts,
            scope=self.scope,
            authorization=config.engagement.authorization,
        )
        self.tool_call_cache = PerTurnToolCallCache()
        self.loaded_skills: list[str] = []
        self._knowledge_lock = threading.RLock()
        self._knowledge_search_callback: (
            Callable[[list[str], str, int], list[dict[str, Any]]] | None
        ) = None
        self._knowledge_default_base_ids: list[str] = []
        self._agent_builder = None  # Set by the harness after construction
        self._agents: dict[str, Any] = {}  # Sub-agent registry
        self._session_metadata: dict[str, Any] = {
            "engagement": {
                "name": config.engagement.name,
                "authorization": config.engagement.authorization,
                "start_url": config.engagement.start_url,
                "allowed_hosts": config.engagement.allowed_hosts,
                "allow_subdomains": config.engagement.allow_subdomains,
            },
            "browser": {
                "mode": config.browser.mode,
                "cdp_url": config.browser.cdp_url,
                "fallback_to_launch_on_cdp_error": config.browser.fallback_to_launch_on_cdp_error,
            },
            "sandbox": {
                "enabled": config.sandbox.enabled,
                "allow_package_install": config.sandbox.allow_package_install,
                "user_id": self.sandbox.user_id,
                "isolation_mode": config.sandbox.isolation_mode,
                "shared_root_dir": config.sandbox.shared_root_dir,
                "root_dir": str(self.sandbox.root_dir),
                "workspace_dir": str(self.sandbox.workspace_dir),
                "venv_dir": str(self.sandbox.venv_dir),
            },
            "skill_scripts": self.skill_scripts.describe(),
            "skills": {
                "enabled": config.skills.enabled,
                "configured_directories": list(config.skills.directories),
                "counts": {
                    "loaded": 0,
                    "manual_available": 0,
                    "skipped": 0,
                    "failed": 0,
                },
                "loaded": [],
                "manual_available": [],
                "skipped": [],
                "failed": [],
            },
        }
        self._write_session_metadata()
        self.artifacts.write_json("skills.json", self._session_metadata["skills"])

    def persist_runtime_logs(self) -> None:
        if self.config.artifacts.persist_network_log:
            self.artifacts.write_json(
                "browser-network.json",
                self.browser.get_network_log(limit=None),
            )
            self.artifacts.write_json(
                "browser-cdp-requests.json",
                self.browser.get_cdp_requests(limit=None, body_chars=8000),
            )
            with contextlib.suppress(Exception):
                self.artifacts.write_json(
                    "browser-loaded-resources.json",
                    self.browser.analyze_page_resources(
                        max_resources=400, max_body_chars=4000
                    ),
                )
        if self.config.artifacts.persist_console_log:
            self.artifacts.write_json(
                "browser-console.json",
                self.browser.get_console_log(limit=None),
            )

    def update_session_metadata(self, payload: dict[str, Any]) -> None:
        for key, value in payload.items():
            if isinstance(value, dict) and isinstance(
                self._session_metadata.get(key), dict
            ):
                self._session_metadata[key] = {**self._session_metadata[key], **value}
            else:
                self._session_metadata[key] = value
        self._write_session_metadata()
        if "skills" in payload:
            self.artifacts.write_json("skills.json", self._session_metadata["skills"])

    @staticmethod
    def _normalize_knowledge_base_ids(raw_ids: list[str] | None) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for item in raw_ids or []:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized.append(value)
        return normalized

    def configure_knowledge_search(
        self,
        *,
        search_callback: Callable[[list[str], str, int], list[dict[str, Any]]] | None,
        default_base_ids: list[str] | None = None,
    ) -> None:
        normalized_base_ids = self._normalize_knowledge_base_ids(default_base_ids)
        with self._knowledge_lock:
            callback_changed = search_callback != self._knowledge_search_callback
            ids_changed = normalized_base_ids != self._knowledge_default_base_ids
            if not callback_changed and not ids_changed:
                return
            self._knowledge_search_callback = search_callback
            self._knowledge_default_base_ids = normalized_base_ids

        self.update_session_metadata(
            {
                "knowledge": {
                    "tool_enabled": search_callback is not None,
                    "default_base_ids": normalized_base_ids,
                },
            },
        )

    def resolve_knowledge_base_scope(
        self, requested_ids: list[str] | None = None
    ) -> list[str]:
        normalized_requested = self._normalize_knowledge_base_ids(requested_ids)
        if normalized_requested:
            return normalized_requested
        with self._knowledge_lock:
            return list(self._knowledge_default_base_ids)

    def search_knowledge(
        self,
        *,
        query: str,
        knowledge_base_ids: list[str] | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        query_text = str(query or "").strip()
        safe_limit = max(1, min(int(limit), 8))
        resolved_ids = self.resolve_knowledge_base_scope(knowledge_base_ids)

        with self._knowledge_lock:
            callback = self._knowledge_search_callback

        if callback is None:
            return {
                "available": False,
                "resolved_knowledge_base_ids": resolved_ids,
                "hits": [],
            }
        if not query_text or not resolved_ids:
            return {
                "available": True,
                "resolved_knowledge_base_ids": resolved_ids,
                "hits": [],
            }

        hits = callback(resolved_ids, query_text, safe_limit)
        return {
            "available": True,
            "resolved_knowledge_base_ids": resolved_ids,
            "hits": hits,
        }

    def _write_session_metadata(self) -> None:
        self.artifacts.write_json("session.json", self._session_metadata)

    def close(self) -> None:
        self.persist_runtime_logs()
        self.http.close()
        self.sandbox.close()
        self.browser.close()
