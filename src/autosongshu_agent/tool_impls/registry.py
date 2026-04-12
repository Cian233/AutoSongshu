from __future__ import annotations

import hashlib
import inspect
import json
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable

from agentscope.tool import ToolResponse, Toolkit

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .utils import _tool_response, _error_response

_ToolPolicyValue = bool | Callable[[dict[str, Any]], bool]

# Transient errors that are worth retrying
_RETRYABLE_ERROR_PATTERNS = (
    "timeout",
    "timed out",
    "connection",
    "connect error",
    "broken pipe",
    "connection reset",
    "temporary failure",
    "502",
    "503",
    "504",
    "429",
    "certif",
    "ssl",
    "tls",
    "cdp",
    "browser.*disconnect",
    "browser.*not connected",
    "target.*closed",
)


@dataclass(frozen=True)
class _ToolExecutionPolicy:
    dedupe: _ToolPolicyValue = True
    invalidates_cache: _ToolPolicyValue = False
    requires_approval: bool = False
    risk_level: ToolRiskLevel = ToolRiskLevel.MEDIUM
    permission_context_name: str | None = None
    max_retries: int = 0
    retry_delay: float = 1.0
    retry_backoff: float = 2.0


def _policy_enabled(policy: _ToolPolicyValue, arguments: dict[str, Any]) -> bool:
    return bool(policy(arguments) if callable(policy) else policy)


def _tool_call_cache_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(f"{tool_name}:{payload}".encode("utf-8")).hexdigest()


def _is_retryable(exc: Exception) -> bool:
    """Check if an exception is transient and worth retrying."""
    msg = str(exc).lower()
    return any(pattern in msg for pattern in _RETRYABLE_ERROR_PATTERNS)


def _execute_with_retry(
    tool_func: Callable,
    runtime: PentestRuntime,
    args: tuple,
    kwargs: dict,
    policy: _ToolExecutionPolicy,
) -> ToolResponse:
    """Execute a tool with optional retry on transient errors."""
    max_retries = policy.max_retries
    if max_retries <= 0:
        return tool_func(runtime, *args, **kwargs)

    last_exc: Exception | None = None
    delay = policy.retry_delay

    for attempt in range(max_retries + 1):
        try:
            return tool_func(runtime, *args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries and _is_retryable(exc):
                import logging
                logger = logging.getLogger(f"autosongshu.tool.{tool_func.__name__}")
                logger.warning(
                    "Tool %s failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    tool_func.__name__,
                    attempt + 1,
                    max_retries + 1,
                    exc,
                    delay,
                )
                time.sleep(delay)
                delay *= policy.retry_backoff
            else:
                raise

    # Should not reach here, but just in case
    if last_exc:
        raise last_exc
    return _error_response(last_exc or Exception("Unknown error"))


def _run_post_hooks(tool_func, arguments, result, duration, runtime):
    """Run post-tool-use hooks (non-critical)."""
    try:
        from ..hooks import get_hook_runner
        get_hook_runner().run_post_tool_use(
            tool_func.__name__, arguments, result,
            duration_ms=duration * 1000,
            session_id=getattr(runtime, "session_id", ""),
        )
    except Exception:
        pass


def _run_post_failure_hooks(tool_func, arguments, error, duration, runtime):
    """Run post-tool-use-failure hooks (non-critical)."""
    try:
        from ..hooks import get_hook_runner
        get_hook_runner().run_post_tool_use_failure(
            tool_func.__name__, arguments, error,
            duration_ms=duration * 1000,
            session_id=getattr(runtime, "session_id", ""),
        )
    except Exception:
        pass


def _wrap_registered_tool(
    tool_func: Callable[..., ToolResponse],
    runtime: PentestRuntime,
    *,
    policy: _ToolExecutionPolicy | None = None,
    permission_interceptor: Any | None = None,
) -> Callable[..., ToolResponse]:
    original_sig = inspect.signature(tool_func)
    new_params = [p for name, p in original_sig.parameters.items() if name != "runtime"]
    exposed_sig = original_sig.replace(parameters=new_params)

    execution_policy = policy or _ToolExecutionPolicy()

    @wraps(tool_func)
    def wrapped(*args: Any, **kwargs: Any) -> ToolResponse:
        bound_arguments = exposed_sig.bind_partial(*args, **kwargs)
        bound_arguments.apply_defaults()
        call_arguments = dict(bound_arguments.arguments)

        # ── Pre-tool hooks ──
        try:
            from ..hooks import get_hook_runner
            hook_runner = get_hook_runner()
            denied, deny_reason, modified_args = hook_runner.run_pre_tool_use(
                tool_func.__name__, call_arguments,
                session_id=getattr(runtime, "session_id", ""),
            )
            if denied:
                return _tool_response({"ok": False, "error": deny_reason or "Denied by hook"})
            if modified_args is not None:
                call_arguments = modified_args
        except Exception:
            pass  # Hooks are non-critical

        permission_result: dict[str, Any] | None = None
        if permission_interceptor is not None:
            permission_result = permission_interceptor.check_permission(
                tool_func.__name__,
                call_arguments,
                risk_level=execution_policy.risk_level,
            )
            if permission_result is not None and not permission_result.get("allowed"):
                error_msg = permission_result.get("error", "Permission denied")
                return _tool_response({"ok": False, "error": error_msg})

        if execution_policy.requires_approval and permission_result is None:
            print(
                f"\n[Warning] The agent wants to execute a high-risk tool: {tool_func.__name__}"
            )
            print(
                f"Arguments: {json.dumps(call_arguments, ensure_ascii=False, indent=2, default=str)}"
            )
            choice = input("Allow execution? [y/N]: ").strip().lower()
            if choice != "y":
                return _tool_response({"ok": False, "error": "Permission Denied"})

        cache = getattr(runtime, "tool_call_cache", None)
        if cache is None:
            return tool_func(runtime, *args, **kwargs)

        dedupe_enabled = _policy_enabled(execution_policy.dedupe, call_arguments)
        invalidates_cache = _policy_enabled(
            execution_policy.invalidates_cache, call_arguments
        )

        if not dedupe_enabled:
            t0 = time.monotonic()
            try:
                response = _execute_with_retry(tool_func, runtime, args, kwargs, execution_policy)
            except Exception as exc:
                _run_post_failure_hooks(tool_func, call_arguments, exc, time.monotonic() - t0, runtime)
                raise
            _run_post_hooks(tool_func, call_arguments, response, time.monotonic() - t0, runtime)
            if invalidates_cache:
                cache.invalidate()
            return response

        call_signature = _tool_call_cache_signature(tool_func.__name__, call_arguments)
        mode, payload = cache.begin_call(call_signature)
        if mode == "cached":
            return payload
        if mode == "wait":
            return cache.wait_for_call(payload)

        try:
            t0 = time.monotonic()
            response = _execute_with_retry(tool_func, runtime, args, kwargs, execution_policy)
            _run_post_hooks(tool_func, call_arguments, response, time.monotonic() - t0, runtime)
        except Exception as exc:
            _run_post_failure_hooks(tool_func, call_arguments, exc, time.monotonic() - t0, runtime)
            cache.fail_call(call_signature, exc)
            raise

        cache.complete_call(
            call_signature, response, invalidates_cache=invalidates_cache
        )
        return response

    wrapped.__signature__ = exposed_sig
    return wrapped


@dataclass
class ToolGroupInfo:
    name: str
    description: str
    active: bool | Callable[[PentestRuntime], bool] = True
    notes: str = ""
    default_risk_level: ToolRiskLevel = ToolRiskLevel.MEDIUM
    default_requires_approval: bool = False


@dataclass
class RegisteredToolInfo:
    func: Callable[..., ToolResponse]
    group_name: str
    policy: _ToolExecutionPolicy


class ToolRegistry:
    def __init__(self) -> None:
        self.groups: dict[str, ToolGroupInfo] = {}
        self.tools: list[RegisteredToolInfo] = []
        self._tool_descriptions: dict[str, str] = {}

    def create_group(
        self,
        name: str,
        description: str,
        active: bool | Callable[[PentestRuntime], bool] = True,
        notes: str = "",
        risk_level: ToolRiskLevel = ToolRiskLevel.MEDIUM,
        requires_approval: bool = False,
    ) -> None:
        self.groups[name] = ToolGroupInfo(
            name, description, active, notes,
            default_risk_level=risk_level,
            default_requires_approval=requires_approval,
        )

    def register(
        self,
        group_name: str,
        *,
        description: str = "",
        risk_level: ToolRiskLevel = ToolRiskLevel.MEDIUM,
        dedupe: _ToolPolicyValue = True,
        invalidates_cache: _ToolPolicyValue = False,
        requires_approval: bool = False,
        max_retries: int = 0,
        retry_delay: float = 1.0,
        retry_backoff: float = 2.0,
    ) -> Callable[[Callable[..., ToolResponse]], Callable[..., ToolResponse]]:
        """Decorator to register a tool function with the registry.

        Usage::

            @registry.register("http", description="Send HTTP request", risk_level=ToolRiskLevel.LOW)
            def http_request(runtime, url: str, method: str = "GET") -> ToolResponse:
                ...

        Args:
            group_name: Tool group to assign this tool to.
            description: Human-readable description for the tool.
            risk_level: Risk level for permission checks.
            dedupe: Whether to deduplicate identical calls within a turn.
            invalidates_cache: Whether this tool invalidates the call cache.
            requires_approval: Whether this tool requires explicit user approval.
            max_retries: Maximum number of retries on transient errors (0 = no retry).
            retry_delay: Initial delay between retries in seconds.
            retry_backoff: Multiplier for exponential backoff.
        """
        policy = _ToolExecutionPolicy(
            dedupe=dedupe,
            invalidates_cache=invalidates_cache,
            requires_approval=requires_approval,
            risk_level=risk_level,
            max_retries=max_retries,
            retry_delay=retry_delay,
            retry_backoff=retry_backoff,
        )

        def decorator(func: Callable[..., ToolResponse]) -> Callable[..., ToolResponse]:
            tool_name = func.__name__
            if description:
                self._tool_descriptions[tool_name] = description
            self.tools.append(
                RegisteredToolInfo(
                    func=func,
                    group_name=group_name,
                    policy=policy,
                )
            )
            return func

        return decorator

    def register_tool(
        self,
        group_name: str,
        *,
        description: str = "",
        risk_level: ToolRiskLevel = ToolRiskLevel.MEDIUM,
        dedupe: _ToolPolicyValue = True,
        invalidates_cache: _ToolPolicyValue = False,
        requires_approval: bool = False,
    ) -> Callable[[Callable[..., ToolResponse]], Callable[..., ToolResponse]]:
        """Semantic alias for :meth:`register`."""
        return self.register(
            group_name,
            description=description,
            risk_level=risk_level,
            dedupe=dedupe,
            invalidates_cache=invalidates_cache,
            requires_approval=requires_approval,
        )

    def register_all_to_toolkit(
        self,
        toolkit: Toolkit,
        runtime: PentestRuntime,
        permission_interceptor: Any | None = None,
    ) -> None:
        for name, info in self.groups.items():
            active = info.active(runtime) if callable(info.active) else info.active
            kwargs = {"description": info.description, "active": active}
            if info.notes:
                kwargs["notes"] = info.notes
            toolkit.create_tool_group(name, **kwargs)

        for tool_info in self.tools:
            wrapped = _wrap_registered_tool(
                tool_info.func,
                runtime,
                policy=tool_info.policy,
                permission_interceptor=permission_interceptor,
            )
            toolkit.register_tool_function(wrapped, group_name=tool_info.group_name)

    def list_tools(self) -> list[dict[str, str]]:
        """Return a summary of all registered tools."""
        return [
            {
                "name": info.func.__name__,
                "group": info.group_name,
                "description": self._tool_descriptions.get(info.func.__name__, ""),
                "risk_level": info.policy.risk_level.value,
            }
            for info in self.tools
        ]

    def get_tool_description(self, tool_name: str) -> str:
        """Return the description for a registered tool."""
        return self._tool_descriptions.get(tool_name, "")


registry = ToolRegistry()
