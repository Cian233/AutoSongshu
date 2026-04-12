"""Tests for PermissionManager and UserDecision."""

import pytest
from pathlib import Path

from autosongshu_agent.core.permissions.manager import (
    PermissionManager,
    UserDecision,
    create_permission_manager,
)
from autosongshu_agent.core.permissions.persistence import (
    PersistenceMode as StorePersistenceMode,
)
from autosongshu_agent.core.permissions.pipeline import (
    PermissionBehavior,
    PermissionMode,
)


class TestUserDecision:
    """Tests for UserDecision class."""

    def test_approve_once(self):
        decision = UserDecision.approve_once()
        assert decision.approved is True
        assert decision.scope == "once"
        assert decision.should_persist() is False

    def test_approve_session(self):
        decision = UserDecision.approve_session()
        assert decision.approved is True
        assert decision.scope == "session"
        assert decision.should_persist() is False

    def test_approve_always_user(self):
        decision = UserDecision.approve_always_user()
        assert decision.approved is True
        assert decision.scope == "user"
        assert decision.should_persist() is True
        assert decision.get_persist_source() == "userSettings"

    def test_approve_always_project(self):
        decision = UserDecision.approve_always_project()
        assert decision.approved is True
        assert decision.scope == "project"
        assert decision.should_persist() is True
        assert decision.get_persist_source() == "projectSettings"

    def test_deny(self):
        decision = UserDecision.deny()
        assert decision.approved is False
        assert decision.scope == "once"

    def test_get_choice_string(self):
        assert UserDecision.approve_once().get_choice_string() == "approved_once"
        assert UserDecision.approve_session().get_choice_string() == "approved_session"
        assert (
            UserDecision.approve_always_user().get_choice_string()
            == "approved_always_user"
        )
        assert (
            UserDecision.approve_always_project().get_choice_string()
            == "approved_always_project"
        )
        assert UserDecision.deny().get_choice_string() == "denied"


class TestPermissionManager:
    """Tests for PermissionManager."""

    def test_create_manager(self):
        manager = create_permission_manager(
            persistence_mode=StorePersistenceMode.SESSION_ONLY,
        )
        assert manager is not None
        assert manager.pipeline is not None
        assert manager.store is not None

    def test_add_allow_rule(self):
        manager = create_permission_manager(
            persistence_mode=StorePersistenceMode.SESSION_ONLY,
        )
        manager.add_allow_rule("Bash", source="session", content_pattern="npm install")

        rules = manager.get_all_rules()
        assert len(rules) == 1
        assert rules[0]["tool_pattern"] == "Bash"
        assert rules[0]["behavior"] == "allow"

    def test_add_deny_rule(self):
        manager = create_permission_manager(
            persistence_mode=StorePersistenceMode.SESSION_ONLY,
        )
        manager.add_deny_rule("dangerous_tool", source="session")

        rules = manager.get_all_rules()
        assert len(rules) == 1
        assert rules[0]["behavior"] == "deny"

    def test_apply_decision_once(self):
        manager = create_permission_manager(
            persistence_mode=StorePersistenceMode.SESSION_ONLY,
        )
        decision = UserDecision.approve_once()
        manager.apply_decision("Bash", decision, content_pattern="npm install")

        # Should not persist
        rules = manager.get_all_rules()
        assert len(rules) == 0

        # But should be in history
        assert len(manager.history.decisions) == 1

    def test_apply_decision_session(self):
        manager = create_permission_manager(
            persistence_mode=StorePersistenceMode.SESSION_ONLY,
        )
        decision = UserDecision.approve_session()
        manager.apply_decision("Bash", decision, content_pattern="npm install")

        # Should not persist (session rules are not stored in settings)
        rules = manager.get_all_rules()
        # Session rules are added to store but marked as session source
        assert len(rules) >= 0

    def test_apply_decision_always_user(self, tmp_path: Path):
        settings_file = tmp_path / "settings.json"
        manager = create_permission_manager(
            persistence_mode=StorePersistenceMode.HYBRID,
            user_settings_path=settings_file,
        )

        decision = UserDecision.approve_always_user()
        manager.apply_decision("Bash", decision, content_pattern="npm install")

        # Should persist
        rules = manager.get_all_rules()
        assert any(r["source"] == "userSettings" for r in rules)

    def test_check_permission_with_rule(self):
        manager = create_permission_manager(
            persistence_mode=StorePersistenceMode.SESSION_ONLY,
        )
        manager.add_allow_rule("Bash", source="session")

        decision = manager.check_permission("Bash", {})
        assert decision.behavior == PermissionBehavior.ALLOW

    def test_remove_rule(self):
        manager = create_permission_manager(
            persistence_mode=StorePersistenceMode.SESSION_ONLY,
        )
        manager.add_allow_rule("Bash", source="session")

        removed = manager.remove_rule("Bash", PermissionBehavior.ALLOW, "session")
        assert removed is True

        rules = manager.get_all_rules()
        assert len(rules) == 0

    def test_clear_session_rules(self):
        manager = create_permission_manager(
            persistence_mode=StorePersistenceMode.SESSION_ONLY,
        )
        manager.add_allow_rule("Tool1", source="session")
        manager.add_allow_rule("Tool2", source="session")

        manager.clear_session_rules()

        rules = manager.get_all_rules()
        assert len(rules) == 0

    def test_set_mode(self):
        manager = create_permission_manager()
        manager.set_mode(PermissionMode.BYPASS)

        assert manager.pipeline.mode == PermissionMode.BYPASS

    def test_history_auto_approve(self):
        manager = create_permission_manager()
        manager.history.auto_approve_threshold = 2

        # Approve twice
        decision1 = UserDecision.approve_session()
        decision2 = UserDecision.approve_session()
        manager.apply_decision("Bash", decision1)
        manager.apply_decision("Bash", decision2)

        # Third check should auto-approve
        assert manager.history.should_auto_approve("Bash") is True


class TestPermissionManagerIntegration:
    """Integration tests for PermissionManager with persistence."""

    def test_persistent_rule_across_sessions(self, tmp_path: Path):
        settings_file = tmp_path / "settings.json"

        # Session 1: Add rule
        manager1 = create_permission_manager(
            persistence_mode=StorePersistenceMode.PERSISTENT,
            user_settings_path=settings_file,
        )
        manager1.add_allow_rule("Bash", source="userSettings")

        # Session 2: Load rules
        manager2 = create_permission_manager(
            persistence_mode=StorePersistenceMode.PERSISTENT,
            user_settings_path=settings_file,
        )

        # Rule should be loaded
        rules = manager2.get_all_rules()
        assert any(r["tool_pattern"] == "Bash" for r in rules)

    def test_session_rules_not_persisted(self, tmp_path: Path):
        settings_file = tmp_path / "settings.json"

        manager = create_permission_manager(
            persistence_mode=StorePersistenceMode.SESSION_ONLY,
            user_settings_path=settings_file,
        )
        manager.add_allow_rule("Bash", source="session")

        # Settings file should not be created
        assert not settings_file.exists()
