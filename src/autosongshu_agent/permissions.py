from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ToolRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ToolPermissionContext:
    deny_names: frozenset[str] = field(default_factory=frozenset)
    deny_prefixes: tuple[str, ...] = ()
    require_approval_names: frozenset[str] = field(default_factory=frozenset)
    require_approval_prefixes: tuple[str, ...] = ()
    require_approval_risk_levels: frozenset[ToolRiskLevel] = field(
        default_factory=frozenset
    )

    @classmethod
    def from_iterables(
        cls,
        deny_names: list[str] | None = None,
        deny_prefixes: list[str] | None = None,
        require_approval_names: list[str] | None = None,
        require_approval_prefixes: list[str] | None = None,
        require_approval_risk_levels: list[str | ToolRiskLevel] | None = None,
    ) -> "ToolPermissionContext":
        normalized_risk_levels: frozenset[ToolRiskLevel] = frozenset()
        if require_approval_risk_levels:
            levels: list[ToolRiskLevel] = []
            for item in require_approval_risk_levels:
                if isinstance(item, ToolRiskLevel):
                    levels.append(item)
                else:
                    try:
                        levels.append(ToolRiskLevel(str(item).lower()))
                    except ValueError:
                        continue
            normalized_risk_levels = frozenset(levels)

        return cls(
            deny_names=frozenset(name.lower() for name in (deny_names or [])),
            deny_prefixes=tuple(prefix.lower() for prefix in (deny_prefixes or [])),
            require_approval_names=frozenset(
                name.lower() for name in (require_approval_names or [])
            ),
            require_approval_prefixes=tuple(
                prefix.lower() for prefix in (require_approval_prefixes or [])
            ),
            require_approval_risk_levels=normalized_risk_levels,
        )

    def blocks(self, tool_name: str) -> bool:
        lowered = tool_name.lower()
        return lowered in self.deny_names or any(
            lowered.startswith(prefix) for prefix in self.deny_prefixes
        )

    def requires_approval(
        self,
        tool_name: str,
        risk_level: ToolRiskLevel | str | None = None,
    ) -> bool:
        lowered = tool_name.lower()
        if lowered in self.require_approval_names:
            return True
        if any(lowered.startswith(prefix) for prefix in self.require_approval_prefixes):
            return True
        if risk_level is not None and self.require_approval_risk_levels:
            normalized_level = (
                risk_level
                if isinstance(risk_level, ToolRiskLevel)
                else ToolRiskLevel(str(risk_level).lower())
            )
            if normalized_level in self.require_approval_risk_levels:
                return True
        return False

    def check_tool(
        self,
        tool_name: str,
        risk_level: ToolRiskLevel | str | None = None,
    ) -> dict[str, Any]:
        lowered = tool_name.lower()
        if self.blocks(lowered):
            return {
                "allowed": False,
                "reason": "blocked",
                "requires_approval": False,
            }
        needs_approval = self.requires_approval(lowered, risk_level)
        return {
            "allowed": True,
            "reason": "approved" if not needs_approval else "pending_approval",
            "requires_approval": needs_approval,
        }


@dataclass(frozen=True)
class PermissionDenial:
    tool_name: str
    reason: str


ApprovalCallback = Callable[[str, dict[str, Any]], bool]


@dataclass
class InteractivePermissionInterceptor:
    context: ToolPermissionContext = field(default_factory=ToolPermissionContext)
    approval_callback: ApprovalCallback | None = None
    denied_tools: list[PermissionDenial] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)

    def check_permission(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        risk_level: ToolRiskLevel | str | None = None,
    ) -> dict[str, Any]:
        result = self.context.check_tool(tool_name, risk_level)
        if not result.get("allowed"):
            denial = PermissionDenial(
                tool_name=tool_name,
                reason=result.get("reason", "blocked"),
            )
            self.denied_tools.append(denial)
            return {
                "allowed": False,
                "error": f"Tool '{tool_name}' is blocked by permission context.",
                "denial": denial,
            }

        if result.get("requires_approval"):
            if self.approval_callback is not None:
                approval_request = {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "risk_level": str(risk_level or ToolRiskLevel.MEDIUM),
                }
                approved = self.approval_callback(tool_name, approval_request)
                if not approved:
                    denial = PermissionDenial(
                        tool_name=tool_name,
                        reason="user_denied",
                    )
                    self.denied_tools.append(denial)
                    return {
                        "allowed": False,
                        "error": f"Tool '{tool_name}' was denied by user.",
                        "denial": denial,
                    }
                return {"allowed": True, "approved": True}

            self.pending_approvals.append(
                {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "risk_level": str(risk_level or ToolRiskLevel.MEDIUM),
                }
            )
            return {
                "allowed": False,
                "error": f"Tool '{tool_name}' requires approval but no callback registered.",
                "pending": True,
            }

        return {"allowed": True}

    def clear_denials(self) -> list[PermissionDenial]:
        denials = list(self.denied_tools)
        self.denied_tools.clear()
        return denials

    def clear_pending(self) -> list[dict[str, Any]]:
        pending = list(self.pending_approvals)
        self.pending_approvals.clear()
        return pending


DEFAULT_HIGH_RISK_TOOLS: frozenset[str] = frozenset(
    {
        "sandbox_run_python",
        "sandbox_write_file",
        "sandbox_edit_file",
        "sandbox_multiedit_file",
        "run_skill_script",
        "browser_execute_script",
        "http_post",
        "http_put",
        "http_delete",
    }
)

DEFAULT_CRITICAL_PREFIXES: tuple[str, ...] = (
    "sandbox_",
    "run_skill_",
)


def build_default_permission_context(
    *,
    deny_names: list[str] | None = None,
    require_approval_for_high_risk: bool = True,
) -> ToolPermissionContext:
    approval_names: list[str] = []
    approval_prefixes: list[str] = []
    approval_levels: list[ToolRiskLevel] = []

    if require_approval_for_high_risk:
        approval_names.extend(DEFAULT_HIGH_RISK_TOOLS)
        approval_prefixes.extend(DEFAULT_CRITICAL_PREFIXES)
        approval_levels.extend([ToolRiskLevel.HIGH, ToolRiskLevel.CRITICAL])

    return ToolPermissionContext.from_iterables(
        deny_names=deny_names,
        require_approval_names=approval_names,
        require_approval_prefixes=approval_prefixes,
        require_approval_risk_levels=approval_levels,
    )


__all__ = [
    "ToolRiskLevel",
    "ToolPermissionContext",
    "PermissionDenial",
    "ApprovalCallback",
    "InteractivePermissionInterceptor",
    "DEFAULT_HIGH_RISK_TOOLS",
    "DEFAULT_CRITICAL_PREFIXES",
    "build_default_permission_context",
]
