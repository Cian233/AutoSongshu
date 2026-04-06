"""
Permission persistence - Store permission rules in settings files.

Inspired by claw-code's multi-source permission rules:
- 8 rule sources: userSettings, projectSettings, localSettings, flagSettings, policySettings, cliArg, command, session
- "session" source is temporary (per-session)
- Other sources are persistent (stored in JSON files)

This module provides:
1. Persistent permission storage (settings files)
2. Session-only permissions (temporary, cleared on restart)
3. Optional persistence mode

Rule format in settings.json:
{
  "permissions": {
    "allow": ["Bash(npm install:*)", "FileEdit"],
    "deny": ["Bash(rm -rf:*)"],
    "ask": ["Bash(npm publish:*)"]
  }
}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from .pipeline import PermissionBehavior, PermissionRule


PermissionRuleSource = Literal[
    "userSettings",
    "projectSettings",
    "localSettings",
    "flagSettings",
    "policySettings",
    "cliArg",
    "command",
    "session",
]

PERMISSION_RULE_SOURCES: list[PermissionRuleSource] = [
    "userSettings",
    "projectSettings",
    "localSettings",
    "flagSettings",
    "policySettings",
    "cliArg",
    "command",
    "session",
]

PERSISTENT_SOURCES: frozenset[PermissionRuleSource] = frozenset(
    [
        "userSettings",
        "projectSettings",
        "localSettings",
        "flagSettings",
        "policySettings",
    ]
)

SESSION_ONLY_SOURCES: frozenset[PermissionRuleSource] = frozenset(
    [
        "session",
    ]
)


class PersistenceMode(str, Enum):
    """Permission persistence modes."""

    PERSISTENT = "persistent"  # Save to settings files
    SESSION_ONLY = "session_only"  # Temporary, cleared on restart
    HYBRID = "hybrid"  # Allow both, user chooses per decision


@dataclass
class StoredPermissionRule:
    """A permission rule with metadata."""

    rule: PermissionRule
    source: PermissionRuleSource
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime | None = None

    def is_expired(self) -> bool:
        """Check if rule has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at


@dataclass
class PermissionStore:
    """
    Permission rule store with persistence support.

    Features:
    - Multi-source rule management (8 sources)
    - Persistent storage (settings files)
    - Session-only temporary rules
    - Rule expiration support
    """

    user_settings_path: Path | None = None
    project_settings_path: Path | None = None
    persistence_mode: PersistenceMode = PersistenceMode.HYBRID

    rules: dict[PermissionRuleSource, list[StoredPermissionRule]] = field(
        default_factory=lambda: {src: [] for src in PERMISSION_RULE_SOURCES}
    )

    def add_rule(
        self,
        rule: PermissionRule,
        source: PermissionRuleSource,
        expires_at: datetime | None = None,
    ) -> None:
        """Add a rule to the store."""
        stored = StoredPermissionRule(
            rule=rule,
            source=source,
            expires_at=expires_at,
        )
        self.rules[source].append(stored)

        if (
            source in PERSISTENT_SOURCES
            and self.persistence_mode != PersistenceMode.SESSION_ONLY
        ):
            self._save_to_settings(source)

    def remove_rule(
        self,
        tool_pattern: str,
        behavior: PermissionBehavior,
        source: PermissionRuleSource,
    ) -> bool:
        """Remove a rule from the store."""
        for i, stored in enumerate(self.rules[source]):
            if (
                stored.rule.tool_pattern == tool_pattern
                and stored.rule.behavior == behavior
            ):
                self.rules[source].pop(i)
                if source in PERSISTENT_SOURCES:
                    self._save_to_settings(source)
                return True
        return False

    def get_all_rules(
        self, include_expired: bool = False
    ) -> list[StoredPermissionRule]:
        """Get all rules, optionally filtering expired."""
        all_rules = []
        for source_rules in self.rules.values():
            for stored in source_rules:
                if include_expired or not stored.is_expired():
                    all_rules.append(stored)
        return all_rules

    def get_rules_by_source(
        self,
        source: PermissionRuleSource,
        include_expired: bool = False,
    ) -> list[StoredPermissionRule]:
        """Get rules from a specific source."""
        if include_expired:
            return self.rules[source]
        return [r for r in self.rules[source] if not r.is_expired()]

    def get_rules_by_behavior(
        self,
        behavior: PermissionBehavior,
        include_expired: bool = False,
    ) -> list[StoredPermissionRule]:
        """Get rules by behavior type."""
        return [
            r
            for r in self.get_all_rules(include_expired)
            if r.rule.behavior == behavior
        ]

    def clear_session_rules(self) -> None:
        """Clear all session-only rules."""
        self.rules["session"].clear()
        self.rules["cliArg"].clear()
        self.rules["command"].clear()

    def clear_expired_rules(self) -> int:
        """Remove all expired rules."""
        count = 0
        for source in PERMISSION_RULE_SOURCES:
            before = len(self.rules[source])
            self.rules[source] = [r for r in self.rules[source] if not r.is_expired()]
            count += before - len(self.rules[source])
        return count

    def _get_settings_path(self, source: PermissionRuleSource) -> Path | None:
        """Get settings file path for a source."""
        if source == "userSettings":
            return (
                self.user_settings_path
                or Path.home() / ".autosongshu" / "settings.json"
            )
        if source == "projectSettings":
            return self.project_settings_path
        if source == "localSettings":
            if self.project_settings_path:
                return self.project_settings_path.parent / "settings.local.json"
        return None

    def _save_to_settings(self, source: PermissionRuleSource) -> bool:
        """Save rules to settings file."""
        if self.persistence_mode == PersistenceMode.SESSION_ONLY:
            return False

        path = self._get_settings_path(source)
        if path is None:
            return False

        try:
            path.parent.mkdir(parents=True, exist_ok=True)

            existing: dict[str, Any] = {}
            if path.exists():
                content = path.read_text(encoding="utf-8")
                if content.strip():
                    existing = json.loads(content)

            allow_rules = [
                self._rule_to_string(r.rule)
                for r in self.rules[source]
                if r.rule.behavior == PermissionBehavior.ALLOW and not r.is_expired()
            ]
            deny_rules = [
                self._rule_to_string(r.rule)
                for r in self.rules[source]
                if r.rule.behavior == PermissionBehavior.DENY and not r.is_expired()
            ]
            ask_rules = [
                self._rule_to_string(r.rule)
                for r in self.rules[source]
                if r.rule.behavior == PermissionBehavior.ASK and not r.is_expired()
            ]

            existing["permissions"] = {
                "allow": allow_rules,
                "deny": deny_rules,
                "ask": ask_rules,
            }

            path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return True
        except Exception:
            return False

    def _load_from_settings(self, source: PermissionRuleSource) -> int:
        """Load rules from settings file."""
        path = self._get_settings_path(source)
        if path is None or not path.exists():
            return 0

        try:
            content = path.read_text(encoding="utf-8")
            if not content.strip():
                return 0

            data = json.loads(content)
            permissions = data.get("permissions", {})

            count = 0
            for behavior_str, rule_strings in permissions.items():
                try:
                    behavior = PermissionBehavior(behavior_str)
                except ValueError:
                    continue

                for rule_string in rule_strings:
                    rule = self._parse_rule_string(rule_string, behavior, source)
                    if rule:
                        self.add_rule(rule, source)
                        count += 1

            return count
        except Exception:
            return 0

    def _rule_to_string(self, rule: PermissionRule) -> str:
        """Convert rule to string format."""
        if rule.content_pattern:
            return f"{rule.tool_pattern}({rule.content_pattern})"
        return rule.tool_pattern

    def _parse_rule_string(
        self,
        rule_string: str,
        behavior: PermissionBehavior,
        source: PermissionRuleSource,
    ) -> PermissionRule | None:
        """Parse a rule string to PermissionRule."""
        import re

        match = re.match(r"^([^(]+)\(([^)]+)\)$", rule_string)
        if match:
            tool_pattern = match.group(1).strip()
            content_pattern = match.group(2).strip()
            return PermissionRule(
                tool_pattern=tool_pattern,
                behavior=behavior,
                source=source,
                content_pattern=content_pattern,
            )

        return PermissionRule(
            tool_pattern=rule_string.strip(),
            behavior=behavior,
            source=source,
        )

    def load_all_persistent_rules(self) -> int:
        """Load all persistent rules from settings files."""
        total = 0
        for source in PERSISTENT_SOURCES:
            total += self._load_from_settings(source)
        return total

    def export_rules_to_dict(self) -> dict[str, Any]:
        """Export all rules to a dictionary."""
        result: dict[str, Any] = {}
        for source in PERMISSION_RULE_SOURCES:
            rules_by_behavior: dict[str, list[str]] = {
                "allow": [],
                "deny": [],
                "ask": [],
            }
            for stored in self.rules[source]:
                if not stored.is_expired():
                    behavior_str = stored.rule.behavior.value
                    rule_str = self._rule_to_string(stored.rule)
                    rules_by_behavior[behavior_str].append(rule_str)

            if any(rules_by_behavior.values()):
                result[source] = rules_by_behavior
        return result

    def import_rules_from_dict(self, data: dict[str, Any]) -> int:
        """Import rules from a dictionary."""
        count = 0
        for source_str, rules_by_behavior in data.items():
            if source_str not in PERMISSION_RULE_SOURCES:
                continue
            source_key = source_str

            for behavior_str, rule_strings in rules_by_behavior.items():
                try:
                    behavior = PermissionBehavior(behavior_str)
                except ValueError:
                    continue

                for rule_string in rule_strings:
                    rule = self._parse_rule_string(rule_string, behavior, source_key)
                    if rule:
                        self.rules[source_key].append(
                            StoredPermissionRule(
                                rule=rule,
                                source=source_key,
                            )
                        )
                        count += 1
        return count


@dataclass
class UserPermissionDecision:
    """
    Record of a user's permission decision.

    Used to track and optionally persist user choices.
    """

    tool_name: str
    behavior: PermissionBehavior
    content: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)
    user_choice: str = "approved"  # "approved", "denied", "ask_always"
    persist: bool = False
    expires_after_hours: int | None = None


@dataclass
class PermissionHistory:
    """
    History of permission decisions for learning/auto-approval.

    Features:
    - Track user decisions per tool
    - Optional persistence to settings
    - Expiration support
    """

    decisions: list[UserPermissionDecision] = field(default_factory=list)
    auto_approve_threshold: int = 3  # Approve after N consistent approvals

    def record_decision(
        self,
        tool_name: str,
        behavior: PermissionBehavior,
        content: str | None = None,
        user_choice: str = "approved",
        persist: bool = False,
        expires_after_hours: int | None = None,
    ) -> None:
        """Record a user decision."""
        decision = UserPermissionDecision(
            tool_name=tool_name,
            behavior=behavior,
            content=content,
            user_choice=user_choice,
            persist=persist,
            expires_after_hours=expires_after_hours,
        )
        self.decisions.append(decision)

    def should_auto_approve(self, tool_name: str, content: str | None = None) -> bool:
        """Check if tool should be auto-approved based on history."""
        recent = [
            d
            for d in self.decisions[-self.auto_approve_threshold * 2 :]
            if d.tool_name == tool_name
            and d.content == content
            and d.user_choice.startswith("approved")
        ]
        return len(recent) >= self.auto_approve_threshold

    def get_recent_decisions(self, limit: int = 10) -> list[UserPermissionDecision]:
        """Get recent decisions."""
        return self.decisions[-limit:]

    def clear_old_decisions(self, max_age_hours: int = 24) -> int:
        """Clear decisions older than max_age_hours."""
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        before = len(self.decisions)
        self.decisions = [d for d in self.decisions if d.timestamp > cutoff]
        return before - len(self.decisions)


def create_permission_store_with_persistence(
    *,
    user_settings_path: Path | None = None,
    project_settings_path: Path | None = None,
    persistence_mode: PersistenceMode = PersistenceMode.HYBRID,
    load_existing: bool = True,
) -> PermissionStore:
    """
    Create a permission store with optional persistence.

    Args:
        user_settings_path: Path to user settings file
        project_settings_path: Path to project settings file
        persistence_mode: How to handle rule persistence
        load_existing: Whether to load existing rules from files

    Returns:
        Configured PermissionStore
    """
    store = PermissionStore(
        user_settings_path=user_settings_path,
        project_settings_path=project_settings_path,
        persistence_mode=persistence_mode,
    )

    if load_existing and persistence_mode != PersistenceMode.SESSION_ONLY:
        store.load_all_persistent_rules()

    return store


__all__ = [
    "PermissionRuleSource",
    "PERMISSION_RULE_SOURCES",
    "PERSISTENT_SOURCES",
    "SESSION_ONLY_SOURCES",
    "PersistenceMode",
    "StoredPermissionRule",
    "PermissionStore",
    "UserPermissionDecision",
    "PermissionHistory",
    "create_permission_store_with_persistence",
]
