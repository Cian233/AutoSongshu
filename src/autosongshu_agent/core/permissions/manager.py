"""
Permission manager - Integrates pipeline, store, and UI.

Provides a unified interface for permission management with persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .pipeline import (
    PermissionBehavior,
    PermissionDecision,
    PermissionMode,
    PermissionPipeline,
    PermissionRule,
)
from .persistence import (
    PersistenceMode as StorePersistenceMode,
    PermissionStore,
    PermissionRuleSource,
    PermissionHistory,
    create_permission_store_with_persistence,
)
from .context import ToolPermissionContext


@dataclass
class PermissionManager:
    """
    Unified permission management.

    Integrates:
    - PermissionPipeline: 7-step decision process
    - PermissionStore: Persistent rule storage
    - PermissionHistory: User decision tracking

    Usage:
        manager = PermissionManager()

        # Check permission
        decision = manager.check_permission("Bash", {"command": "npm install"})

        # Handle user decision from UI
        manager.apply_decision("Bash", user_decision, content_pattern="npm install")
    """

    pipeline: PermissionPipeline
    store: PermissionStore
    history: PermissionHistory = field(default_factory=PermissionHistory)
    persistence_mode: StorePersistenceMode = StorePersistenceMode.HYBRID

    @classmethod
    def create(
        cls,
        *,
        persistence_mode: StorePersistenceMode = StorePersistenceMode.HYBRID,
        permission_mode: PermissionMode = PermissionMode.DEFAULT,
        user_settings_path: Path | None = None,
        project_settings_path: Path | None = None,
        load_existing_rules: bool = True,
    ) -> "PermissionManager":
        """
        Create a configured permission manager.

        Args:
            persistence_mode: How to handle rule persistence
            permission_mode: Permission pipeline mode
            user_settings_path: Path to user settings file
            project_settings_path: Path to project settings file
            load_existing_rules: Whether to load existing rules from files

        Returns:
            Configured PermissionManager
        """
        store = create_permission_store_with_persistence(
            user_settings_path=user_settings_path,
            project_settings_path=project_settings_path,
            persistence_mode=persistence_mode,
            load_existing=load_existing_rules,
        )

        pipeline = PermissionPipeline(
            permission_context=ToolPermissionContext(),
            mode=permission_mode,
        )

        # Load rules from store into pipeline
        for stored_rule in store.get_all_rules():
            pipeline.add_rule(stored_rule.rule)

        return cls(
            pipeline=pipeline,
            store=store,
            history=PermissionHistory(),
            persistence_mode=persistence_mode,
        )

    def check_permission(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        *,
        risk_level: str | None = None,
        content: str | None = None,
        path_field: str | None = None,
    ) -> PermissionDecision:
        """
        Check if tool execution is allowed.

        Args:
            tool_name: Name of the tool
            input_data: Tool input arguments
            risk_level: Tool risk level
            content: Content pattern for rule matching
            path_field: Field name containing path for safety check

        Returns:
            PermissionDecision with behavior and reason
        """
        # Check history for auto-approval
        if self.history.should_auto_approve(tool_name, content):
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                decision_reason=None,
                message="Auto-approved based on history",
            )

        # Check pipeline
        result = self.pipeline.check_permission(
            tool_name,
            input_data,
            path_field=path_field,
        )

        return result

    def apply_decision(
        self,
        tool_name: str,
        decision: "UserDecision",
        content_pattern: str | None = None,
    ) -> None:
        """
        Apply a user's permission decision.

        Args:
            tool_name: Tool name
            decision: User's decision from UI
            content_pattern: Optional content pattern for the rule
        """
        from .persistence import UserPermissionDecision

        # Record in history
        self.history.record_decision(
            tool_name=tool_name,
            behavior=PermissionBehavior.ALLOW
            if decision.approved
            else PermissionBehavior.DENY,
            content=content_pattern,
            user_choice=decision.get_choice_string(),
            persist=decision.should_persist(),
        )

        if decision.approved and decision.should_persist():
            source = decision.get_persist_source()
            rule = PermissionRule(
                tool_pattern=tool_name,
                behavior=PermissionBehavior.ALLOW,
                source=source,
                content_pattern=content_pattern,
            )
            self.store.add_rule(rule, source)
            self.pipeline.add_rule(rule)

    def add_allow_rule(
        self,
        tool_pattern: str,
        source: PermissionRuleSource = "userSettings",
        content_pattern: str | None = None,
    ) -> None:
        """Add an allow rule."""
        rule = PermissionRule(
            tool_pattern=tool_pattern,
            behavior=PermissionBehavior.ALLOW,
            source=source,
            content_pattern=content_pattern,
        )
        self.store.add_rule(rule, source)
        self.pipeline.add_rule(rule)

    def add_deny_rule(
        self,
        tool_pattern: str,
        source: PermissionRuleSource = "userSettings",
        content_pattern: str | None = None,
    ) -> None:
        """Add a deny rule."""
        rule = PermissionRule(
            tool_pattern=tool_pattern,
            behavior=PermissionBehavior.DENY,
            source=source,
            content_pattern=content_pattern,
        )
        self.store.add_rule(rule, source)
        self.pipeline.add_rule(rule)

    def remove_rule(
        self,
        tool_pattern: str,
        behavior: PermissionBehavior,
        source: PermissionRuleSource,
    ) -> bool:
        """Remove a rule."""
        return self.store.remove_rule(tool_pattern, behavior, source)

    def get_all_rules(self) -> list[dict[str, Any]]:
        """Get all rules as list of dicts."""
        rules = []
        for stored in self.store.get_all_rules():
            rules.append(
                {
                    "tool_pattern": stored.rule.tool_pattern,
                    "behavior": stored.rule.behavior.value,
                    "source": stored.source,
                    "content_pattern": stored.rule.content_pattern,
                }
            )
        return rules

    def clear_session_rules(self) -> None:
        """Clear all session-only rules."""
        self.store.clear_session_rules()

    def set_mode(self, mode: PermissionMode) -> None:
        """Set permission pipeline mode."""
        self.pipeline.mode = mode

    def set_approval_callback(
        self,
        callback: Callable[[str, dict[str, Any]], bool] | None,
    ) -> None:
        """Set approval callback for interactive mode."""
        self.pipeline.approval_callback = callback


@dataclass
class UserDecision:
    """
    User's permission decision from UI.

    Provides clean API for different decision types.
    """

    approved: bool
    scope: str = "once"  # "once", "session", "user", "project"

    @classmethod
    def approve_once(cls) -> "UserDecision":
        """Approve only this time."""
        return cls(approved=True, scope="once")

    @classmethod
    def approve_session(cls) -> "UserDecision":
        """Approve for this session."""
        return cls(approved=True, scope="session")

    @classmethod
    def approve_always_user(cls) -> "UserDecision":
        """Always allow, save to user settings."""
        return cls(approved=True, scope="user")

    @classmethod
    def approve_always_project(cls) -> "UserDecision":
        """Always allow, save to project settings."""
        return cls(approved=True, scope="project")

    @classmethod
    def deny(cls) -> "UserDecision":
        """Deny."""
        return cls(approved=False, scope="once")

    def should_persist(self) -> bool:
        """Check if this decision should be persisted."""
        return self.approved and self.scope in ("user", "project")

    def get_persist_source(self) -> PermissionRuleSource:
        """Get the source for persistence."""
        if self.scope == "user":
            return "userSettings"
        if self.scope == "project":
            return "projectSettings"
        return "session"

    def get_choice_string(self) -> str:
        """Get string representation of choice."""
        if not self.approved:
            return "denied"
        if self.scope == "once":
            return "approved_once"
        if self.scope == "session":
            return "approved_session"
        if self.scope == "user":
            return "approved_always_user"
        if self.scope == "project":
            return "approved_always_project"
        return "approved"


def create_permission_manager(
    *,
    persistence_mode: StorePersistenceMode = StorePersistenceMode.HYBRID,
    permission_mode: PermissionMode = PermissionMode.DEFAULT,
    user_settings_path: Path | None = None,
    project_settings_path: Path | None = None,
) -> PermissionManager:
    """
    Create a permission manager with default settings.

    This is the recommended way to create a PermissionManager.
    """
    return PermissionManager.create(
        persistence_mode=persistence_mode,
        permission_mode=permission_mode,
        user_settings_path=user_settings_path,
        project_settings_path=project_settings_path,
    )


__all__ = [
    "PermissionManager",
    "UserDecision",
    "create_permission_manager",
]
