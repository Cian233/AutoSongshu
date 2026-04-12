"""
UI components for permission management.

Provides interactive permission approval components with persistence support.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..core.permissions import ToolPermissionContext, ToolRiskLevel
from ..core.permissions.persistence import (
    PersistenceMode,
    PermissionStore,
    PermissionRuleSource,
)


@dataclass
class PermissionRequest:
    """Permission request for UI display."""

    tool_name: str
    risk_level: str
    arguments: dict[str, Any]
    reason: str
    can_remember: bool
    can_persist: bool = False
    persistence_mode: PersistenceMode = PersistenceMode.HYBRID


@dataclass
class PermissionDecision:
    """User's decision on permission request."""

    approved: bool
    remember_for_session: bool = False
    remember_for_project: bool = False
    persist_to_user_settings: bool = False
    source: PermissionRuleSource = "session"


class PermissionPromptUI:
    """
    UI component for permission prompts.

    Works in both CLI and Web contexts.
    Supports session-only and persistent permission storage.
    """

    def __init__(
        self,
        on_decision: Callable[[PermissionDecision], None] | None = None,
        persistence_mode: PersistenceMode = PersistenceMode.HYBRID,
    ):
        self.on_decision = on_decision
        self.persistence_mode = persistence_mode

    def format_permission_prompt(self, request: PermissionRequest) -> str:
        """
        Format permission prompt for CLI display.

        Args:
            request: Permission request details

        Returns:
            Formatted string for CLI
        """
        risk_emoji = {
            "LOW": "🟢",
            "MEDIUM": "🟡",
            "HIGH": "🟠",
            "CRITICAL": "🔴",
        }

        emoji = risk_emoji.get(request.risk_level, "⚪")

        lines = [
            "",
            f"{emoji} Permission Required",
            "=" * 50,
            f"Tool: {request.tool_name}",
            f"Risk Level: {request.risk_level}",
            "",
            f"Reason: {request.reason}",
            "",
            "Arguments:",
        ]

        for key, value in request.arguments.items():
            value_str = str(value)
            if len(value_str) > 50:
                value_str = value_str[:47] + "..."
            lines.append(f"  {key}: {value_str}")

        lines.extend(["", "=" * 50])

        options = ["[A] Approve once", "[D] Deny"]
        if request.can_remember:
            options.append("[S] Approve for this session")
        if (
            request.can_persist
            and self.persistence_mode != PersistenceMode.SESSION_ONLY
        ):
            options.append("[U] Always allow (save to user settings)")
            options.append("[P] Always allow (save to project settings)")
        lines.append("  ".join(options))

        return "\n".join(lines)

    def render_web(self, request: PermissionRequest) -> dict[str, Any]:
        """
        Render permission request for Web UI.

        Args:
            request: Permission request details

        Returns:
            Dict for JSON response
        """
        options = [
            {"key": "a", "label": "Approve", "action": "approve"},
            {"key": "d", "label": "Deny", "action": "deny"},
        ]

        if request.can_remember:
            options.append(
                {
                    "key": "s",
                    "label": "Approve for session",
                    "action": "approve_session",
                }
            )

        if (
            request.can_persist
            and self.persistence_mode != PersistenceMode.SESSION_ONLY
        ):
            options.extend(
                [
                    {
                        "key": "p",
                        "label": "Save to user settings",
                        "action": "persist_user",
                    },
                    {
                        "key": "r",
                        "label": "Save to project settings",
                        "action": "persist_project",
                    },
                ]
            )

        return {
            "type": "permission_request",
            "tool_name": request.tool_name,
            "risk_level": request.risk_level,
            "reason": request.reason,
            "arguments": request.arguments,
            "can_remember": request.can_remember,
            "can_persist": request.can_persist,
            "persistence_mode": self.persistence_mode.value,
            "options": options,
        }

    def handle_cli_input(self, user_input: str) -> PermissionDecision:
        """
        Handle CLI user input.

        Args:
            user_input: User's input character

        Returns:
            Permission decision
        """
        user_input = user_input.lower().strip()

        if user_input == "a":
            return PermissionDecision(approved=True)
        elif user_input == "d":
            return PermissionDecision(approved=False)
        elif user_input == "s":
            return PermissionDecision(approved=True, remember_for_session=True)
        elif user_input == "u":
            return PermissionDecision(
                approved=True,
                persist_to_user_settings=True,
                source="userSettings",
            )
        elif user_input == "p":
            return PermissionDecision(
                approved=True,
                remember_for_project=True,
                source="projectSettings",
            )
        else:
            return PermissionDecision(approved=False)

    def handle_web_response(self, response: dict[str, Any]) -> PermissionDecision:
        """
        Handle Web UI response.

        Args:
            response: Web UI response dict

        Returns:
            Permission decision
        """
        action = response.get("action", "deny")

        if action == "approve":
            return PermissionDecision(approved=True)
        elif action == "approve_session":
            return PermissionDecision(approved=True, remember_for_session=True)
        elif action == "approve_project":
            return PermissionDecision(approved=True, remember_for_project=True)
        elif action == "persist_user":
            return PermissionDecision(
                approved=True,
                persist_to_user_settings=True,
                source="userSettings",
            )
        elif action == "persist_project":
            return PermissionDecision(
                approved=True,
                persist_to_user_settings=True,
                source="projectSettings",
            )
        else:
            return PermissionDecision(approved=False)


class PermissionRulesUI:
    """
    UI component for managing permission rules.

    Provides interface for viewing and editing stored permission rules.
    """

    def __init__(self, store: PermissionStore):
        self.store = store

    def render_cli(self) -> str:
        """Render permission rules for CLI display."""
        lines = [
            "",
            "Permission Rules",
            "=" * 60,
        ]

        sources: list[PermissionRuleSource] = [
            "userSettings",
            "projectSettings",
            "session",
        ]
        for source in sources:
            rules = self.store.get_rules_by_source(source)
            if rules:
                lines.append(f"\n[{source}]")
                for stored in rules:
                    behavior = stored.rule.behavior.value.upper()
                    pattern = stored.rule.tool_pattern
                    content = stored.rule.content_pattern or ""
                    if content:
                        lines.append(f"  {behavior}: {pattern}({content})")
                    else:
                        lines.append(f"  {behavior}: {pattern}")

        lines.extend(["", "=" * 60])
        return "\n".join(lines)

    def render_web(self) -> dict[str, Any]:
        """Render permission rules for Web UI."""
        rules_by_source: dict[str, list[dict[str, Any]]] = {}

        sources: list[PermissionRuleSource] = [
            "userSettings",
            "projectSettings",
            "localSettings",
            "session",
        ]
        for source in sources:
            rules = self.store.get_rules_by_source(source)
            if rules:
                rules_by_source[source] = [
                    {
                        "tool_pattern": r.rule.tool_pattern,
                        "behavior": r.rule.behavior.value,
                        "content_pattern": r.rule.content_pattern,
                        "created_at": r.created_at.isoformat()
                        if r.created_at
                        else None,
                        "expires_at": r.expires_at.isoformat()
                        if r.expires_at
                        else None,
                    }
                    for r in rules
                ]

        return {
            "type": "permission_rules",
            "persistence_mode": self.store.persistence_mode.value,
            "rules": rules_by_source,
        }

    def add_rule(
        self,
        tool_pattern: str,
        behavior: str,
        source: PermissionRuleSource,
        content_pattern: str | None = None,
    ) -> bool:
        """Add a new permission rule."""
        from ..core.permissions.pipeline import PermissionBehavior, PermissionRule

        try:
            behavior_enum = PermissionBehavior(behavior)
        except ValueError:
            return False

        rule = PermissionRule(
            tool_pattern=tool_pattern,
            behavior=behavior_enum,
            source=source,
            content_pattern=content_pattern,
        )

        self.store.add_rule(rule, source)
        return True

    def remove_rule(
        self,
        tool_pattern: str,
        behavior: str,
        source: PermissionRuleSource,
    ) -> bool:
        """Remove a permission rule."""
        from ..core.permissions.pipeline import PermissionBehavior

        try:
            behavior_enum = PermissionBehavior(behavior)
        except ValueError:
            return False

        return self.store.remove_rule(tool_pattern, behavior_enum, source)


class SessionStatusUI:
    """
    UI component for displaying session status.
    """

    def __init__(self, state: dict[str, Any]):
        self.state = state

    def render_cli(self) -> str:
        """Render session status for CLI."""
        lines = [
            "",
            "Session Status",
            "=" * 50,
            f"Session ID: {self.state.get('session_id', 'N/A')}",
            f"Model: {self.state.get('main_loop_model', 'N/A')}",
            f"Total Cost: ${self.state.get('total_cost', 0):.4f}",
            "",
            "Model Usage:",
        ]

        usage = self.state.get("model_usage", {})
        for model, stats in usage.items():
            lines.append(
                f"  {model}: {stats.get('input_tokens', 0)} in / "
                f"{stats.get('output_tokens', 0)} out"
            )

        return "\n".join(lines)

    def render_web(self) -> dict[str, Any]:
        """Render session status for Web UI."""
        return {
            "type": "session_status",
            "session_id": self.state.get("session_id"),
            "model": self.state.get("main_loop_model"),
            "cost": self.state.get("total_cost", 0),
            "usage": self.state.get("model_usage", {}),
        }


__all__ = [
    "PermissionRequest",
    "PermissionDecision",
    "PermissionPromptUI",
    "PermissionRulesUI",
    "SessionStatusUI",
]
