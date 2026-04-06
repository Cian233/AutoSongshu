"""Tests for permission persistence."""

import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from autosongshu_agent.core.permissions.persistence import (
    PermissionRuleSource,
    PERMISSION_RULE_SOURCES,
    PERSISTENT_SOURCES,
    SESSION_ONLY_SOURCES,
    PersistenceMode,
    StoredPermissionRule,
    PermissionStore,
    UserPermissionDecision,
    PermissionHistory,
    create_permission_store_with_persistence,
)
from autosongshu_agent.core.permissions.pipeline import (
    PermissionBehavior,
    PermissionRule,
)


class TestPermissionRuleSources:
    """Tests for permission rule sources."""

    def test_all_sources_defined(self):
        assert len(PERMISSION_RULE_SOURCES) == 8
        assert "userSettings" in PERMISSION_RULE_SOURCES
        assert "session" in PERMISSION_RULE_SOURCES

    def test_persistent_sources(self):
        assert "userSettings" in PERSISTENT_SOURCES
        assert "projectSettings" in PERSISTENT_SOURCES
        assert "session" not in PERSISTENT_SOURCES

    def test_session_only_sources(self):
        assert "session" in SESSION_ONLY_SOURCES
        assert "userSettings" not in SESSION_ONLY_SOURCES


class TestPersistenceMode:
    """Tests for PersistenceMode enum."""

    def test_all_modes_exist(self):
        assert PersistenceMode.PERSISTENT.value == "persistent"
        assert PersistenceMode.SESSION_ONLY.value == "session_only"
        assert PersistenceMode.HYBRID.value == "hybrid"


class TestStoredPermissionRule:
    """Tests for StoredPermissionRule."""

    def test_create_stored_rule(self):
        rule = PermissionRule(
            tool_pattern="Bash",
            behavior=PermissionBehavior.ALLOW,
            source="userSettings",
        )
        stored = StoredPermissionRule(rule=rule, source="userSettings")
        assert stored.rule == rule
        assert stored.is_expired() is False

    def test_expired_rule(self):
        rule = PermissionRule(
            tool_pattern="Bash",
            behavior=PermissionBehavior.ALLOW,
            source="session",
        )
        stored = StoredPermissionRule(
            rule=rule,
            source="session",
            expires_at=datetime.now() - timedelta(hours=1),
        )
        assert stored.is_expired() is True

    def test_not_expired_rule(self):
        rule = PermissionRule(
            tool_pattern="Bash",
            behavior=PermissionBehavior.ALLOW,
            source="session",
        )
        stored = StoredPermissionRule(
            rule=rule,
            source="session",
            expires_at=datetime.now() + timedelta(hours=1),
        )
        assert stored.is_expired() is False


class TestPermissionStore:
    """Tests for PermissionStore."""

    def test_add_rule(self):
        store = PermissionStore(persistence_mode=PersistenceMode.SESSION_ONLY)
        rule = PermissionRule(
            tool_pattern="Bash",
            behavior=PermissionBehavior.ALLOW,
            source="session",
        )
        store.add_rule(rule, "session")
        assert len(store.rules["session"]) == 1

    def test_remove_rule(self):
        store = PermissionStore(persistence_mode=PersistenceMode.SESSION_ONLY)
        rule = PermissionRule(
            tool_pattern="Bash",
            behavior=PermissionBehavior.ALLOW,
            source="session",
        )
        store.add_rule(rule, "session")
        removed = store.remove_rule("Bash", PermissionBehavior.ALLOW, "session")
        assert removed is True
        assert len(store.rules["session"]) == 0

    def test_get_all_rules(self):
        store = PermissionStore(persistence_mode=PersistenceMode.SESSION_ONLY)
        rule1 = PermissionRule(
            tool_pattern="Bash",
            behavior=PermissionBehavior.ALLOW,
            source="session",
        )
        rule2 = PermissionRule(
            tool_pattern="FileEdit",
            behavior=PermissionBehavior.DENY,
            source="session",
        )
        store.add_rule(rule1, "session")
        store.add_rule(rule2, "session")
        all_rules = store.get_all_rules()
        assert len(all_rules) == 2

    def test_get_rules_by_behavior(self):
        store = PermissionStore(persistence_mode=PersistenceMode.SESSION_ONLY)
        rule1 = PermissionRule(
            tool_pattern="Bash",
            behavior=PermissionBehavior.ALLOW,
            source="session",
        )
        rule2 = PermissionRule(
            tool_pattern="FileEdit",
            behavior=PermissionBehavior.DENY,
            source="session",
        )
        store.add_rule(rule1, "session")
        store.add_rule(rule2, "session")
        allow_rules = store.get_rules_by_behavior(PermissionBehavior.ALLOW)
        assert len(allow_rules) == 1
        assert allow_rules[0].rule.tool_pattern == "Bash"

    def test_clear_session_rules(self):
        store = PermissionStore(persistence_mode=PersistenceMode.SESSION_ONLY)
        rule = PermissionRule(
            tool_pattern="Bash",
            behavior=PermissionBehavior.ALLOW,
            source="session",
        )
        store.add_rule(rule, "session")
        store.add_rule(rule, "cliArg")
        store.clear_session_rules()
        assert len(store.rules["session"]) == 0
        assert len(store.rules["cliArg"]) == 0

    def test_clear_expired_rules(self):
        store = PermissionStore(persistence_mode=PersistenceMode.SESSION_ONLY)
        rule = PermissionRule(
            tool_pattern="Bash",
            behavior=PermissionBehavior.ALLOW,
            source="session",
        )
        store.add_rule(rule, "session")
        expired_rule = StoredPermissionRule(
            rule=rule,
            source="session",
            expires_at=datetime.now() - timedelta(hours=1),
        )
        store.rules["session"].append(expired_rule)
        count = store.clear_expired_rules()
        assert count == 1
        assert len(store.rules["session"]) == 1

    def test_export_import_rules(self):
        store = PermissionStore(persistence_mode=PersistenceMode.SESSION_ONLY)
        rule1 = PermissionRule(
            tool_pattern="Bash",
            behavior=PermissionBehavior.ALLOW,
            source="session",
            content_pattern="npm install",
        )
        rule2 = PermissionRule(
            tool_pattern="FileEdit",
            behavior=PermissionBehavior.DENY,
            source="session",
        )
        store.add_rule(rule1, "session")
        store.add_rule(rule2, "session")

        exported = store.export_rules_to_dict()
        assert "session" in exported
        assert "allow" in exported["session"]
        assert "deny" in exported["session"]

        new_store = PermissionStore(persistence_mode=PersistenceMode.SESSION_ONLY)
        count = new_store.import_rules_from_dict(exported)
        assert count == 2


class TestPermissionStorePersistence:
    """Tests for PermissionStore file persistence."""

    def test_save_and_load_settings(self, tmp_path: Path):
        settings_file = tmp_path / "settings.json"
        store = PermissionStore(
            user_settings_path=settings_file,
            persistence_mode=PersistenceMode.PERSISTENT,
        )

        rule = PermissionRule(
            tool_pattern="Bash",
            behavior=PermissionBehavior.ALLOW,
            source="userSettings",
            content_pattern="npm install",
        )
        store.add_rule(rule, "userSettings")

        assert settings_file.exists()
        data = json.loads(settings_file.read_text())
        assert "permissions" in data
        assert "allow" in data["permissions"]

        new_store = PermissionStore(
            user_settings_path=settings_file,
            persistence_mode=PersistenceMode.PERSISTENT,
        )
        count = new_store.load_all_persistent_rules()
        assert count >= 1

    def test_session_only_mode_no_persistence(self, tmp_path: Path):
        settings_file = tmp_path / "settings.json"
        store = PermissionStore(
            user_settings_path=settings_file,
            persistence_mode=PersistenceMode.SESSION_ONLY,
        )

        rule = PermissionRule(
            tool_pattern="Bash",
            behavior=PermissionBehavior.ALLOW,
            source="userSettings",
        )
        store.add_rule(rule, "userSettings")

        assert not settings_file.exists()


class TestUserPermissionDecision:
    """Tests for UserPermissionDecision."""

    def test_create_decision(self):
        decision = UserPermissionDecision(
            tool_name="Bash",
            behavior=PermissionBehavior.ALLOW,
            content="npm install",
            user_choice="approved",
            persist=True,
        )
        assert decision.tool_name == "Bash"
        assert decision.user_choice == "approved"

    def test_default_values(self):
        decision = UserPermissionDecision(
            tool_name="Bash",
            behavior=PermissionBehavior.ALLOW,
        )
        assert decision.user_choice == "approved"
        assert decision.persist is False


class TestPermissionHistory:
    """Tests for PermissionHistory."""

    def test_record_decision(self):
        history = PermissionHistory()
        history.record_decision(
            tool_name="Bash",
            behavior=PermissionBehavior.ALLOW,
            content="npm install",
            user_choice="approved",
        )
        assert len(history.decisions) == 1

    def test_auto_approve_threshold(self):
        history = PermissionHistory(auto_approve_threshold=2)
        history.record_decision(
            "Bash", PermissionBehavior.ALLOW, user_choice="approved"
        )
        history.record_decision(
            "Bash", PermissionBehavior.ALLOW, user_choice="approved"
        )

        assert history.should_auto_approve("Bash") is True
        assert history.should_auto_approve("FileEdit") is False

    def test_get_recent_decisions(self):
        history = PermissionHistory()
        for i in range(15):
            history.record_decision(f"Tool{i}", PermissionBehavior.ALLOW)

        recent = history.get_recent_decisions(limit=5)
        assert len(recent) == 5
        assert recent[-1].tool_name == "Tool14"

    def test_clear_old_decisions(self):
        history = PermissionHistory()
        history.record_decision("Bash", PermissionBehavior.ALLOW)

        old_decision = UserPermissionDecision(
            tool_name="OldTool",
            behavior=PermissionBehavior.ALLOW,
            timestamp=datetime.now() - timedelta(hours=48),
        )
        history.decisions.insert(0, old_decision)

        cleared = history.clear_old_decisions(max_age_hours=24)
        assert cleared == 1
        assert len(history.decisions) == 1


class TestCreatePermissionStoreWithPersistence:
    """Tests for create_permission_store_with_persistence factory."""

    def test_create_session_only(self):
        store = create_permission_store_with_persistence(
            persistence_mode=PersistenceMode.SESSION_ONLY,
            load_existing=False,
        )
        assert store.persistence_mode == PersistenceMode.SESSION_ONLY

    def test_create_hybrid(self):
        store = create_permission_store_with_persistence(
            persistence_mode=PersistenceMode.HYBRID,
            load_existing=False,
        )
        assert store.persistence_mode == PersistenceMode.HYBRID

    def test_create_with_paths(self, tmp_path: Path):
        user_path = tmp_path / "user_settings.json"
        project_path = tmp_path / "project_settings.json"

        store = create_permission_store_with_persistence(
            user_settings_path=user_path,
            project_settings_path=project_path,
            persistence_mode=PersistenceMode.PERSISTENT,
            load_existing=False,
        )

        assert store.user_settings_path == user_path
        assert store.project_settings_path == project_path
