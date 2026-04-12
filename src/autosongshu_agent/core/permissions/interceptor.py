"""
Permission interceptor - Interactive permission checking.

Inspired by claw-code's InteractivePermissionInterceptor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .context import ToolPermissionContext, ToolRiskLevel


@dataclass
class PermissionResult:
    """Result of a permission check."""

    allowed: bool
    reason: str
    requires_approval: bool = False
    error: str | None = None


class PermissionInterceptor:
    """
    Permission interceptor for tool execution.

    Checks tool permissions before execution and optionally requests approval.
    """

    def __init__(
        self,
        context: ToolPermissionContext,
        request_approval_callback: Callable[[str, dict, str], bool] | None = None,
        auto_approve_low_risk: bool = False,
    ):
        self.context = context
        self.request_approval = request_approval_callback
        self.auto_approve_low_risk = auto_approve_low_risk

    def check_permission(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        risk_level: ToolRiskLevel | str | None = None,
    ) -> PermissionResult | None:
        """
        Check if tool execution is allowed.

        Returns None if allowed, otherwise returns PermissionResult with denial reason.
        """
        # Check if tool is blocked
        if self.context.blocks(tool_name):
            return PermissionResult(
                allowed=False,
                reason="blocked",
                error=f"Tool '{tool_name}' is blocked by permission policy",
            )

        # Check if approval is required
        requires_approval = self.context.requires_approval(tool_name, risk_level)

        if requires_approval:
            # If we have an approval callback, use it
            if self.request_approval:
                approved = self.request_approval(
                    tool_name, arguments, risk_level or "unknown"
                )
                return PermissionResult(
                    allowed=approved,
                    reason="approved" if approved else "denied",
                    requires_approval=True,
                    error=None if approved else "User denied approval",
                )

            # Auto-approve low risk if enabled
            if self.auto_approve_low_risk and risk_level == ToolRiskLevel.LOW:
                return PermissionResult(
                    allowed=True,
                    reason="auto_approved",
                    requires_approval=True,
                )

            # Need approval but no callback provided
            return PermissionResult(
                allowed=False,
                reason="approval_required",
                requires_approval=True,
                error="Tool requires approval but no approval callback provided",
            )

        # Tool is allowed
        return PermissionResult(
            allowed=True,
            reason="approved",
        )


def build_default_permission_context(
    deny_names: list[str] | None = None,
    deny_prefixes: list[str] | None = None,
    require_approval_names: list[str] | None = None,
    require_approval_prefixes: list[str] | None = None,
    require_approval_for_high_risk: bool = True,
    require_approval_for_critical: bool = True,
) -> ToolPermissionContext:
    """
    Build a default permission context with common settings.

    Args:
        deny_names: Tool names to block
        deny_prefixes: Tool name prefixes to block
        require_approval_names: Tool names requiring approval
        require_approval_prefixes: Tool name prefixes requiring approval
        require_approval_for_high_risk: Auto-require approval for HIGH risk tools
        require_approval_for_critical: Auto-require approval for CRITICAL risk tools

    Returns:
        Configured ToolPermissionContext
    """
    approval_risk_levels = []
    if require_approval_for_high_risk:
        approval_risk_levels.append(ToolRiskLevel.HIGH)
    if require_approval_for_critical:
        approval_risk_levels.append(ToolRiskLevel.CRITICAL)

    return ToolPermissionContext.from_iterables(
        deny_names=deny_names or [],
        deny_prefixes=deny_prefixes or [],
        require_approval_names=require_approval_names or [],
        require_approval_prefixes=require_approval_prefixes or [],
        require_approval_risk_levels=approval_risk_levels,
    )
