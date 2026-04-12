"""Tests for complete permission pipeline."""

import pytest
from typing import Any

from autosongshu_agent.core.permissions.pipeline import (
    PermissionBehavior,
    PermissionMode,
    PermissionDecision,
    DecisionReason,
    SafetyCheckResult,
    PermissionRule,
    DenialTracker,
    PermissionPipeline,
    check_path_safety,
    SENSITIVE_PATHS,
    FORBIDDEN_PATH_PATTERNS,
    create_default_pipeline,
)
from autosongshu_agent.core.permissions.context import ToolPermissionContext


class TestPermissionBehavior:
    """Tests for PermissionBehavior enum."""

    def test_all_behaviors_exist(self):
        assert PermissionBehavior.ALLOW.value == "allow"
        assert PermissionBehavior.ASK.value == "ask"
        assert PermissionBehavior.DENY.value == "deny"
        assert PermissionBehavior.PASSTHROUGH.value == "passthrough"


class TestPermissionMode:
    """Tests for PermissionMode enum."""

    def test_all_modes_exist(self):
        assert PermissionMode.DEFAULT.value == "default"
        assert PermissionMode.AUTO.value == "auto"
        assert PermissionMode.BYPASS.value == "bypassPermissions"
        assert PermissionMode.DONT_ASK.value == "dontAsk"
        assert PermissionMode.PLAN.value == "plan"


class TestCheckPathSafety:
    """Tests for check_path_safety()."""

    def test_safe_path(self):
        result = check_path_safety("/home/user/documents/file.txt")
        assert result.triggered is False

    def test_sensitive_git_path(self):
        result = check_path_safety(".git/config")
        assert result.triggered is True
        assert result.classifier_approvable is True
        assert ".git/" in str(result.reason)

    def test_sensitive_env_path(self):
        result = check_path_safety(".env")
        assert result.triggered is True

    def test_forbidden_double_dot(self):
        result = check_path_safety("../secret/file.txt")
        assert result.triggered is True
        assert result.classifier_approvable is False

    def test_forbidden_ssh_path(self):
        result = check_path_safety("~/.ssh/id_rsa")
        assert result.triggered is True
        assert result.classifier_approvable is False


class TestPermissionRule:
    """Tests for PermissionRule."""

    def test_exact_match(self):
        rule = PermissionRule(
            tool_pattern="bash",
            behavior=PermissionBehavior.DENY,
            source="test",
        )
        assert rule.matches_tool("bash") is True
        assert rule.matches_tool("Bash") is True
        assert rule.matches_tool("bash_tool") is False

    def test_wildcard_match(self):
        rule = PermissionRule(
            tool_pattern="*",
            behavior=PermissionBehavior.ASK,
            source="test",
        )
        assert rule.matches_tool("anything") is True

    def test_prefix_match(self):
        rule = PermissionRule(
            tool_pattern="sandbox_*",
            behavior=PermissionBehavior.DENY,
            source="test",
        )
        assert rule.matches_tool("sandbox_run") is True
        assert rule.matches_tool("sandbox_write") is True
        assert rule.matches_tool("other_tool") is False

    def test_content_pattern_match(self):
        rule = PermissionRule(
            tool_pattern="bash",
            behavior=PermissionBehavior.ASK,
            source="test",
            content_pattern="npm publish*",
        )
        assert rule.matches_content("npm publish package") is True
        assert rule.matches_content("npm install") is False


class TestDenialTracker:
    """Tests for DenialTracker."""

    def test_record_denial(self):
        tracker = DenialTracker()
        tracker.record_denial("test_tool", "test_reason")
        assert tracker.consecutive_denials == 1
        assert tracker.total_denials == 1

    def test_record_allow_resets_consecutive(self):
        tracker = DenialTracker()
        tracker.record_denial("tool1", "reason")
        tracker.record_denial("tool2", "reason")
        assert tracker.consecutive_denials == 2

        tracker.record_allow()
        assert tracker.consecutive_denials == 0
        assert tracker.total_denials == 2

    def test_should_abort_on_consecutive(self):
        tracker = DenialTracker()
        for i in range(3):
            tracker.record_denial(f"tool_{i}", "reason")
        assert tracker.should_abort() is True

    def test_should_abort_on_total(self):
        tracker = DenialTracker()
        tracker.CONSECUTIVE_THRESHOLD = 100
        for i in range(20):
            tracker.record_allow()
            tracker.record_denial(f"tool_{i}", "reason")
        assert tracker.should_abort() is True

    def test_reset(self):
        tracker = DenialTracker()
        tracker.record_denial("tool", "reason")
        tracker.reset()
        assert tracker.consecutive_denials == 0
        assert tracker.total_denials == 0


class TestPermissionPipeline:
    """Tests for PermissionPipeline."""

    def test_deny_rule_highest_priority(self):
        pipeline = PermissionPipeline(
            permission_context=ToolPermissionContext(),
            mode=PermissionMode.DEFAULT,
        )
        pipeline.add_rule(
            PermissionRule(
                tool_pattern="dangerous_tool",
                behavior=PermissionBehavior.DENY,
                source="test",
            )
        )

        result = pipeline.check_permission("dangerous_tool", {})
        assert result.behavior == PermissionBehavior.DENY
        assert result.decision_reason.type == "rule"

    def test_allow_rule_overrides_default(self):
        pipeline = PermissionPipeline(
            permission_context=ToolPermissionContext(),
            mode=PermissionMode.DEFAULT,
        )
        pipeline.add_rule(
            PermissionRule(
                tool_pattern="safe_tool",
                behavior=PermissionBehavior.ALLOW,
                source="test",
            )
        )

        result = pipeline.check_permission("safe_tool", {})
        assert result.behavior == PermissionBehavior.ALLOW

    def test_bypass_mode_skips_checks(self):
        pipeline = PermissionPipeline(
            permission_context=ToolPermissionContext(),
            mode=PermissionMode.BYPASS,
        )

        result = pipeline.check_permission("any_tool", {})
        assert result.behavior == PermissionBehavior.ALLOW
        assert result.decision_reason.type == "mode"

    def test_bypass_cannot_skip_safety_check(self):
        pipeline = PermissionPipeline(
            permission_context=ToolPermissionContext(),
            mode=PermissionMode.BYPASS,
        )

        result = pipeline.check_permission(
            "file_write",
            {"path": ".git/config"},
            path_field="path",
        )
        assert result.behavior == PermissionBehavior.ASK
        assert result.decision_reason.type == "safety_check"

    def test_dont_ask_mode_converts_ask_to_deny(self):
        pipeline = PermissionPipeline(
            permission_context=ToolPermissionContext(),
            mode=PermissionMode.DONT_ASK,
        )

        result = pipeline.check_permission("unknown_tool", {})
        assert result.behavior == PermissionBehavior.DENY
        assert result.decision_reason.type == "mode"

    def test_auto_mode_with_classifier(self):
        def classifier_approves(tool_name: str, input_data: dict) -> bool:
            return tool_name == "approved_tool"

        pipeline = PermissionPipeline(
            permission_context=ToolPermissionContext(),
            mode=PermissionMode.AUTO,
            auto_approve_classifier=classifier_approves,
        )

        result = pipeline.check_permission("approved_tool", {})
        assert result.behavior == PermissionBehavior.ALLOW

        result = pipeline.check_permission("denied_tool", {})
        assert result.behavior == PermissionBehavior.DENY

    def test_approval_callback(self):
        def approve_if_safe(tool_name: str, input_data: dict) -> bool:
            return input_data.get("safe", False)

        pipeline = PermissionPipeline(
            permission_context=ToolPermissionContext(),
            mode=PermissionMode.DEFAULT,
            approval_callback=approve_if_safe,
        )

        result = pipeline.check_permission("tool", {"safe": True})
        assert result.behavior == PermissionBehavior.ALLOW

        result = pipeline.check_permission("tool", {"safe": False})
        assert result.behavior == PermissionBehavior.DENY

    def test_circuit_breaker_triggers(self):
        pipeline = PermissionPipeline(
            permission_context=ToolPermissionContext(),
            mode=PermissionMode.DONT_ASK,
        )

        for i in range(4):
            result = pipeline.check_permission(f"tool_{i}", {})
            if i < 3:
                assert result.behavior == PermissionBehavior.DENY
            else:
                assert result.decision_reason.type == "circuit_breaker"

    def test_tool_check_permissions_integration(self):
        def tool_check(input_data: dict, context: Any) -> PermissionDecision:
            if input_data.get("forbidden"):
                return PermissionDecision(
                    behavior=PermissionBehavior.DENY,
                    decision_reason=DecisionReason(type="tool_internal"),
                )
            return PermissionDecision(
                behavior=PermissionBehavior.PASSTHROUGH,
            )

        pipeline = PermissionPipeline(
            permission_context=ToolPermissionContext(),
            mode=PermissionMode.DEFAULT,
        )

        result = pipeline.check_permission(
            "tool", {"forbidden": True}, tool_check_permissions=tool_check
        )
        assert result.behavior == PermissionBehavior.DENY

        result = pipeline.check_permission(
            "tool", {}, tool_check_permissions=tool_check
        )
        assert result.behavior == PermissionBehavior.ASK


class TestCreateDefaultPipeline:
    """Tests for create_default_pipeline()."""

    def test_create_with_deny_tools(self):
        pipeline = create_default_pipeline(deny_tools=["dangerous"])

        result = pipeline.check_permission("dangerous", {})
        assert result.behavior == PermissionBehavior.DENY

    def test_create_with_allow_tools(self):
        pipeline = create_default_pipeline(allow_tools=["safe"])

        result = pipeline.check_permission("safe", {})
        assert result.behavior == PermissionBehavior.ALLOW

    def test_create_with_approval_callback(self):
        def approve_all(tool_name: str, input_data: dict) -> bool:
            return True

        pipeline = create_default_pipeline(approval_callback=approve_all)

        result = pipeline.check_permission("any_tool", {})
        assert result.behavior == PermissionBehavior.ALLOW
