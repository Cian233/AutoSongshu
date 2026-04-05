from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable

from agentscope.tool import ToolResponse, Toolkit

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .utils import _tool_response

_ToolPolicyValue = bool | Callable[[dict[str, Any]], bool]


@dataclass(frozen=True)
class _ToolExecutionPolicy:
    dedupe: _ToolPolicyValue = True
    invalidates_cache: _ToolPolicyValue = False
    requires_approval: bool = False
    risk_level: ToolRiskLevel = ToolRiskLevel.MEDIUM
    permission_context_name: str | None = None


def _policy_enabled(policy: _ToolPolicyValue, arguments: dict[str, Any]) -> bool:
    return bool(policy(arguments) if callable(policy) else policy)


def _tool_call_cache_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    payload = json.dumps(arguments, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(f"{tool_name}:{payload}".encode("utf-8")).hexdigest()


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
            response = tool_func(runtime, *args, **kwargs)
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
            response = tool_func(runtime, *args, **kwargs)
        except Exception as exc:
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


@dataclass
class RegisteredToolInfo:
    func: Callable[..., ToolResponse]
    group_name: str
    policy: _ToolExecutionPolicy


class ToolRegistry:
    def __init__(self) -> None:
        self.groups: dict[str, ToolGroupInfo] = {}
        self.tools: list[RegisteredToolInfo] = []

    def create_group(
        self,
        name: str,
        description: str,
        active: bool | Callable[[PentestRuntime], bool] = True,
        notes: str = "",
    ) -> None:
        self.groups[name] = ToolGroupInfo(name, description, active, notes)

    def register(
        self, group_name: str, **policy_kwargs: Any
    ) -> Callable[[Callable[..., ToolResponse]], Callable[..., ToolResponse]]:
        def decorator(func: Callable[..., ToolResponse]) -> Callable[..., ToolResponse]:
            self.tools.append(
                RegisteredToolInfo(
                    func=func,
                    group_name=group_name,
                    policy=_ToolExecutionPolicy(**policy_kwargs),
                )
            )
            return func

        return decorator

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


registry = ToolRegistry()
