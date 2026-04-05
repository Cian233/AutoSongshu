from __future__ import annotations

import unittest

from autosongshu_agent.permissions import (
    ToolPermissionContext,
    ToolRiskLevel,
    InteractivePermissionInterceptor,
    PermissionDenial,
    build_default_permission_context,
    DEFAULT_HIGH_RISK_TOOLS,
    DEFAULT_CRITICAL_PREFIXES,
)


class ToolPermissionContextTests(unittest.TestCase):
    def test_empty_context_blocks_none(self) -> None:
        ctx = ToolPermissionContext()
        self.assertFalse(ctx.blocks("any_tool"))
        self.assertFalse(ctx.requires_approval("any_tool"))
        result = ctx.check_tool("any_tool")
        self.assertTrue(result["allowed"])
        self.assertFalse(result["requires_approval"])

    def test_deny_names_blocks_exact_match(self) -> None:
        ctx = ToolPermissionContext.from_iterables(deny_names=["dangerous_tool"])
        self.assertTrue(ctx.blocks("dangerous_tool"))
        self.assertTrue(ctx.blocks("DANGEROUS_TOOL"))
        self.assertFalse(ctx.blocks("safe_tool"))

    def test_deny_prefixes_blocks_prefix_match(self) -> None:
        ctx = ToolPermissionContext.from_iterables(deny_prefixes=["sandbox_"])
        self.assertTrue(ctx.blocks("sandbox_run_python"))
        self.assertTrue(ctx.blocks("sandbox_write_file"))
        self.assertFalse(ctx.blocks("http_get"))

    def test_require_approval_names(self) -> None:
        ctx = ToolPermissionContext.from_iterables(
            require_approval_names=["high_risk_tool"]
        )
        self.assertFalse(ctx.blocks("high_risk_tool"))
        self.assertTrue(ctx.requires_approval("high_risk_tool"))
        self.assertFalse(ctx.requires_approval("low_risk_tool"))

    def test_require_approval_prefixes(self) -> None:
        ctx = ToolPermissionContext.from_iterables(
            require_approval_prefixes=["run_skill_"]
        )
        self.assertTrue(ctx.requires_approval("run_skill_script"))
        self.assertFalse(ctx.requires_approval("http_get"))

    def test_require_approval_risk_levels(self) -> None:
        ctx = ToolPermissionContext.from_iterables(
            require_approval_risk_levels=[ToolRiskLevel.HIGH, ToolRiskLevel.CRITICAL]
        )
        self.assertTrue(
            ctx.requires_approval("any_tool", risk_level=ToolRiskLevel.HIGH)
        )
        self.assertTrue(ctx.requires_approval("any_tool", risk_level="critical"))
        self.assertFalse(
            ctx.requires_approval("any_tool", risk_level=ToolRiskLevel.LOW)
        )

    def test_check_tool_returns_correct_structure(self) -> None:
        ctx = ToolPermissionContext.from_iterables(
            deny_names=["blocked"],
            require_approval_names=["needs_approval"],
        )
        blocked_result = ctx.check_tool("blocked")
        self.assertFalse(blocked_result["allowed"])
        self.assertEqual(blocked_result["reason"], "blocked")

        approval_result = ctx.check_tool("needs_approval")
        self.assertTrue(approval_result["allowed"])
        self.assertTrue(approval_result["requires_approval"])

        safe_result = ctx.check_tool("safe_tool")
        self.assertTrue(safe_result["allowed"])
        self.assertFalse(safe_result["requires_approval"])


class InteractivePermissionInterceptorTests(unittest.TestCase):
    def test_blocks_denied_tools(self) -> None:
        ctx = ToolPermissionContext.from_iterables(deny_names=["blocked"])
        interceptor = InteractivePermissionInterceptor(context=ctx)
        result = interceptor.check_permission("blocked", {})
        self.assertFalse(result["allowed"])
        self.assertIn("blocked", result["error"])
        self.assertEqual(len(interceptor.denied_tools), 1)

    def test_approves_without_callback_when_not_required(self) -> None:
        ctx = ToolPermissionContext()
        interceptor = InteractivePermissionInterceptor(context=ctx)
        result = interceptor.check_permission("safe_tool", {})
        self.assertTrue(result["allowed"])

    def test_pending_approval_when_no_callback(self) -> None:
        ctx = ToolPermissionContext.from_iterables(require_approval_names=["high_risk"])
        interceptor = InteractivePermissionInterceptor(context=ctx)
        result = interceptor.check_permission("high_risk", {"arg": "value"})
        self.assertFalse(result["allowed"])
        self.assertTrue(result.get("pending"))
        self.assertEqual(len(interceptor.pending_approvals), 1)

    def test_approval_callback_approves(self) -> None:
        ctx = ToolPermissionContext.from_iterables(require_approval_names=["high_risk"])

        def approve_callback(tool_name: str, request: dict) -> bool:
            return tool_name == "high_risk"

        interceptor = InteractivePermissionInterceptor(
            context=ctx,
            approval_callback=approve_callback,
        )
        result = interceptor.check_permission("high_risk", {"arg": "value"})
        self.assertTrue(result["allowed"])
        self.assertTrue(result.get("approved"))

    def test_approval_callback_denies(self) -> None:
        ctx = ToolPermissionContext.from_iterables(require_approval_names=["high_risk"])

        def deny_callback(tool_name: str, request: dict) -> bool:
            return False

        interceptor = InteractivePermissionInterceptor(
            context=ctx,
            approval_callback=deny_callback,
        )
        result = interceptor.check_permission("high_risk", {"arg": "value"})
        self.assertFalse(result["allowed"])
        self.assertEqual(len(interceptor.denied_tools), 1)

    def test_clear_denials(self) -> None:
        ctx = ToolPermissionContext.from_iterables(deny_names=["blocked"])
        interceptor = InteractivePermissionInterceptor(context=ctx)
        interceptor.check_permission("blocked", {})
        interceptor.check_permission("blocked", {})
        self.assertEqual(len(interceptor.denied_tools), 2)
        denials = interceptor.clear_denials()
        self.assertEqual(len(denials), 2)
        self.assertEqual(len(interceptor.denied_tools), 0)

    def test_clear_pending(self) -> None:
        ctx = ToolPermissionContext.from_iterables(require_approval_names=["high_risk"])
        interceptor = InteractivePermissionInterceptor(context=ctx)
        interceptor.check_permission("high_risk", {})
        interceptor.check_permission("high_risk", {})
        self.assertEqual(len(interceptor.pending_approvals), 2)
        pending = interceptor.clear_pending()
        self.assertEqual(len(pending), 2)
        self.assertEqual(len(interceptor.pending_approvals), 0)


class DefaultPermissionContextTests(unittest.TestCase):
    def test_default_context_has_high_risk_tools(self) -> None:
        ctx = build_default_permission_context()
        for tool_name in DEFAULT_HIGH_RISK_TOOLS:
            self.assertTrue(ctx.requires_approval(tool_name))

    def test_default_context_has_critical_prefixes(self) -> None:
        ctx = build_default_permission_context()
        for prefix in DEFAULT_CRITICAL_PREFIXES:
            self.assertTrue(ctx.require_approval_prefixes)
            matched_tool = f"{prefix}test_action"
            self.assertTrue(ctx.requires_approval(matched_tool))

    def test_default_context_blocks_none_by_default(self) -> None:
        ctx = build_default_permission_context()
        self.assertFalse(ctx.blocks("http_get"))
        self.assertFalse(ctx.blocks("browser_navigate"))

    def test_default_context_with_deny_names(self) -> None:
        ctx = build_default_permission_context(deny_names=["forbidden_tool"])
        self.assertTrue(ctx.blocks("forbidden_tool"))

    def test_default_context_without_high_risk_approval(self) -> None:
        ctx = build_default_permission_context(require_approval_for_high_risk=False)
        self.assertFalse(ctx.requires_approval("sandbox_run_python"))


class PermissionDenialTests(unittest.TestCase):
    def test_denial_creation(self) -> None:
        denial = PermissionDenial(tool_name="blocked_tool", reason="user_denied")
        self.assertEqual(denial.tool_name, "blocked_tool")
        self.assertEqual(denial.reason, "user_denied")


if __name__ == "__main__":
    unittest.main()
