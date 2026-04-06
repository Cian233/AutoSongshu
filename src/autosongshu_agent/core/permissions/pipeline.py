"""
Complete permission pipeline - 7-step decision process.

Inspired by claw-code's hasPermissionsToUseTool() architecture:
- Inner pipeline: 7-step decision process
- Outer wrapper: Mode-level transformation
- Denial tracking: Circuit breaker for infinite retries

Steps:
1a. Whole-tool deny rules → Reject if matched (highest priority)
1b. Whole-tool ask rules → Require manual confirmation if matched
1c. tool.checkPermissions() → Tool's own permission logic
1d. Tool returns deny → Reject
1e. requiresUserInteraction + ask → Even bypass needs manual confirmation
1f. Content-level ask rules → Bypass cannot skip
1g. Safety check → Bypass cannot skip

2a. bypass mode → Allow after all above pass
2b. Whole-tool allow rules → Allow if matched

3. passthrough → Convert to ask, let user decide
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Literal

from .context import ToolPermissionContext, ToolRiskLevel


class PermissionBehavior(str, Enum):
    """Permission decision behavior."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"
    PASSTHROUGH = "passthrough"


class PermissionMode(str, Enum):
    """Permission system modes."""

    DEFAULT = "default"
    AUTO = "auto"
    BYPASS = "bypassPermissions"
    DONT_ASK = "dontAsk"
    PLAN = "plan"


@dataclass
class DecisionReason:
    """Reason for a permission decision."""

    type: str  # "rule", "safety_check", "tool_internal", "mode", "default"
    source: str | None = None
    rule_behavior: str | None = None
    message: str = ""


@dataclass
class PermissionDecision:
    """Final permission decision."""

    behavior: PermissionBehavior
    decision_reason: DecisionReason | None = None
    message: str = ""
    updated_input: dict[str, Any] | None = None


@dataclass
class SafetyCheckResult:
    """Result of a safety check."""

    triggered: bool
    classifier_approvable: bool = False
    reason: str = ""
    sensitive_paths: list[str] = field(default_factory=list)


SENSITIVE_PATHS = [
    ".git/",
    ".claude/",
    ".autosongshu/",
    ".env",
    ".ssh/",
    ".vscode/",
    "__pycache__/",
    "node_modules/",
]

FORBIDDEN_PATH_PATTERNS = [
    "..",
    "~/.ssh/",
    "/etc/passwd",
    "/etc/shadow",
]


def check_path_safety(path: str) -> SafetyCheckResult:
    """
    Check if a path is sensitive or forbidden.

    Returns SafetyCheckResult with details.
    """
    normalized = path.replace("\\", "/").lower()

    for forbidden in FORBIDDEN_PATH_PATTERNS:
        if forbidden.lower() in normalized:
            return SafetyCheckResult(
                triggered=True,
                classifier_approvable=False,
                reason=f"Path contains forbidden pattern: {forbidden}",
                sensitive_paths=[path],
            )

    sensitive_found = []
    for sensitive in SENSITIVE_PATHS:
        if sensitive.lower() in normalized:
            sensitive_found.append(sensitive)

    if sensitive_found:
        return SafetyCheckResult(
            triggered=True,
            classifier_approvable=True,
            reason=f"Path matches sensitive patterns: {sensitive_found}",
            sensitive_paths=sensitive_found,
        )

    return SafetyCheckResult(triggered=False)


@dataclass
class PermissionRule:
    """A permission rule from settings."""

    tool_pattern: str
    behavior: PermissionBehavior
    source: str
    content_pattern: str | None = None

    def matches_tool(self, tool_name: str) -> bool:
        """Check if this rule matches a tool."""
        pattern_lower = self.tool_pattern.lower()
        name_lower = tool_name.lower()

        if pattern_lower == "*" or pattern_lower == name_lower:
            return True

        if pattern_lower.endswith("*"):
            prefix = pattern_lower[:-1]
            return name_lower.startswith(prefix)

        return False

    def matches_content(self, content: str | None) -> bool:
        """Check if content pattern matches."""
        if not self.content_pattern:
            return True

        if content is None:
            return False

        pattern_lower = self.content_pattern.lower()
        content_lower = content.lower()

        if pattern_lower == "*":
            return True

        if pattern_lower.endswith("*"):
            prefix = pattern_lower[:-1]
            return content_lower.startswith(prefix)

        if pattern_lower.startswith("*") and pattern_lower.endswith("*"):
            return pattern_lower[1:-1] in content_lower

        return pattern_lower == content_lower


@dataclass
class DenialRecord:
    """Record of a permission denial."""

    tool_name: str
    reason: str
    timestamp: float = 0.0


@dataclass
class DenialTracker:
    """
    Circuit breaker for permission denials.

    Prevents infinite retries when agent is denied.
    """

    consecutive_denials: int = 0
    total_denials: int = 0
    records: list[DenialRecord] = field(default_factory=list)

    CONSECUTIVE_THRESHOLD: int = 3
    TOTAL_THRESHOLD: int = 20

    def record_denial(self, tool_name: str, reason: str) -> None:
        """Record a denial."""
        import time

        self.records.append(
            DenialRecord(
                tool_name=tool_name,
                reason=reason,
                timestamp=time.time(),
            )
        )
        self.consecutive_denials += 1
        self.total_denials += 1

    def record_allow(self) -> None:
        """Reset consecutive denials when allowed."""
        self.consecutive_denials = 0

    def should_abort(self) -> bool:
        """Check if we should abort due to too many denials."""
        if self.consecutive_denials >= self.CONSECUTIVE_THRESHOLD:
            return True
        if self.total_denials >= self.TOTAL_THRESHOLD:
            return True
        return False

    def reset(self) -> None:
        """Reset all counters."""
        self.consecutive_denials = 0
        self.total_denials = 0
        self.records.clear()


class PermissionPipeline:
    """
    Complete permission pipeline - 7-step decision process.

    Implements the full permission decision flow:
    1. Inner pipeline: Check deny, ask, tool internal, safety
    2. Outer wrapper: Apply mode-level transformation
    3. Denial tracking: Circuit breaker protection
    """

    def __init__(
        self,
        permission_context: ToolPermissionContext,
        mode: PermissionMode = PermissionMode.DEFAULT,
        approval_callback: Callable[[str, dict[str, Any]], bool] | None = None,
        auto_approve_classifier: Callable[[str, dict[str, Any]], bool] | None = None,
    ):
        self.context = permission_context
        self.mode = mode
        self.approval_callback = approval_callback
        self.classifier_callback = auto_approve_classifier
        self.denial_tracker = DenialTracker()

        self.rules: list[PermissionRule] = []

    def add_rule(self, rule: PermissionRule) -> None:
        """Add a permission rule."""
        self.rules.append(rule)

    def get_deny_rule(self, tool_name: str) -> PermissionRule | None:
        """Get deny rule matching tool."""
        for rule in self.rules:
            if rule.behavior == PermissionBehavior.DENY and rule.matches_tool(
                tool_name
            ):
                return rule
        return None

    def get_ask_rule(
        self, tool_name: str, content: str | None = None
    ) -> PermissionRule | None:
        """Get ask rule matching tool."""
        for rule in self.rules:
            if rule.behavior == PermissionBehavior.ASK:
                if rule.matches_tool(tool_name) and rule.matches_content(content):
                    return rule
        return None

    def get_allow_rule(self, tool_name: str) -> PermissionRule | None:
        """Get allow rule matching tool."""
        for rule in self.rules:
            if rule.behavior == PermissionBehavior.ALLOW and rule.matches_tool(
                tool_name
            ):
                return rule
        return None

    def check_permission_inner(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        tool_check_permissions: Callable[[dict, Any], PermissionDecision] | None = None,
        requires_user_interaction: bool = False,
        path_field: str | None = None,
    ) -> PermissionDecision:
        """
        Inner pipeline - 7-step decision process.

        Steps 1a-1g are processed in order, each can short-circuit.
        """
        content_to_match = input_data.get("command", input_data.get("content", None))

        # Step 1a: Whole-tool deny rules (highest priority)
        deny_rule = self.get_deny_rule(tool_name)
        if deny_rule:
            self.denial_tracker.record_denial(tool_name, "deny_rule")
            return PermissionDecision(
                behavior=PermissionBehavior.DENY,
                decision_reason=DecisionReason(
                    type="rule",
                    source=deny_rule.source,
                    rule_behavior="deny",
                    message=f"Tool '{tool_name}' blocked by deny rule from {deny_rule.source}",
                ),
                message=f"Blocked by deny rule: {deny_rule.tool_pattern}",
            )

        # Step 1b: Whole-tool ask rules
        ask_rule = self.get_ask_rule(tool_name)
        if ask_rule and not self._can_sandbox_auto_allow(tool_name, input_data):
            return PermissionDecision(
                behavior=PermissionBehavior.ASK,
                decision_reason=DecisionReason(
                    type="rule",
                    source=ask_rule.source,
                    rule_behavior="ask",
                    message=f"Tool '{tool_name}' requires confirmation per rule from {ask_rule.source}",
                ),
                message=f"Requires confirmation per ask rule: {ask_rule.tool_pattern}",
            )

        # Step 1c: Tool's own permission check
        tool_result: PermissionDecision | None = None
        if tool_check_permissions:
            tool_result = tool_check_permissions(input_data, self.context)

        # Step 1d: Tool returns deny
        if tool_result and tool_result.behavior == PermissionBehavior.DENY:
            self.denial_tracker.record_denial(tool_name, "tool_internal")
            return tool_result

        # Step 1e: requiresUserInteraction + ask (bypass-immune)
        if (
            requires_user_interaction
            and tool_result
            and tool_result.behavior == PermissionBehavior.ASK
        ):
            return tool_result

        # Step 1f: Content-level ask rules (bypass-immune)
        content_ask_rule = self.get_ask_rule(tool_name, content_to_match)
        if content_ask_rule and content_ask_rule.content_pattern:
            return PermissionDecision(
                behavior=PermissionBehavior.ASK,
                decision_reason=DecisionReason(
                    type="rule",
                    source=content_ask_rule.source,
                    rule_behavior="ask",
                    message=f"Content pattern '{content_ask_rule.content_pattern}' requires confirmation",
                ),
                message=f"Content-level ask rule: {content_ask_rule.content_pattern}",
            )

        # Step 1g: Safety check (bypass-immune)
        if path_field and path_field in input_data:
            safety_result = check_path_safety(input_data[path_field])
            if safety_result.triggered:
                return PermissionDecision(
                    behavior=PermissionBehavior.ASK,
                    decision_reason=DecisionReason(
                        type="safety_check",
                        message=safety_result.reason,
                    ),
                    message=f"Safety check triggered: {safety_result.reason}",
                )

        # Step 2a: Bypass mode - skip remaining checks
        if self.mode == PermissionMode.BYPASS:
            self.denial_tracker.record_allow()
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                decision_reason=DecisionReason(
                    type="mode",
                    message="Bypassing permission checks",
                ),
            )

        # Step 2b: Whole-tool allow rules
        allow_rule = self.get_allow_rule(tool_name)
        if allow_rule:
            self.denial_tracker.record_allow()
            return PermissionDecision(
                behavior=PermissionBehavior.ALLOW,
                decision_reason=DecisionReason(
                    type="rule",
                    source=allow_rule.source,
                    rule_behavior="allow",
                    message=f"Tool '{tool_name}' allowed by rule from {allow_rule.source}",
                ),
            )

        # Step 3: Passthrough → Ask
        if tool_result and tool_result.behavior == PermissionBehavior.PASSTHROUGH:
            return PermissionDecision(
                behavior=PermissionBehavior.ASK,
                decision_reason=tool_result.decision_reason,
                message="No explicit rule, requires user decision",
            )

        if tool_result:
            return tool_result

        return PermissionDecision(
            behavior=PermissionBehavior.ASK,
            decision_reason=DecisionReason(
                type="default",
                message="No permission rule matched",
            ),
            message="Default: requires confirmation",
        )

    def check_permission_outer(
        self,
        inner_result: PermissionDecision,
        tool_name: str,
        input_data: dict[str, Any],
    ) -> PermissionDecision:
        """
        Outer wrapper - Mode-level transformation.

        Transforms inner result based on current mode.
        """
        if inner_result.behavior == PermissionBehavior.ALLOW:
            self.denial_tracker.record_allow()
            return inner_result

        if inner_result.behavior == PermissionBehavior.DENY:
            return inner_result

        # inner_result.behavior == ASK
        if self.mode == PermissionMode.DONT_ASK:
            self.denial_tracker.record_denial(tool_name, "dont_ask_mode")
            return PermissionDecision(
                behavior=PermissionBehavior.DENY,
                decision_reason=DecisionReason(
                    type="mode",
                    message="DontAsk mode converts ask to deny",
                ),
                message=f"DontAsk mode: '{tool_name}' denied without asking",
            )

        if self.mode == PermissionMode.AUTO:
            if self.classifier_callback:
                approved = self.classifier_callback(tool_name, input_data)
                if approved:
                    self.denial_tracker.record_allow()
                    return PermissionDecision(
                        behavior=PermissionBehavior.ALLOW,
                        decision_reason=DecisionReason(
                            type="mode",
                            message="Auto-approved by classifier",
                        ),
                    )
                else:
                    self.denial_tracker.record_denial(tool_name, "classifier_denied")
                    return PermissionDecision(
                        behavior=PermissionBehavior.DENY,
                        decision_reason=DecisionReason(
                            type="mode",
                            message="Classifier denied",
                        ),
                    )
            else:
                return PermissionDecision(
                    behavior=PermissionBehavior.ASK,
                    decision_reason=DecisionReason(
                        type="mode",
                        message="Auto mode but no classifier",
                    ),
                )

        if self.approval_callback:
            approved = self.approval_callback(tool_name, input_data)
            if approved:
                self.denial_tracker.record_allow()
                return PermissionDecision(
                    behavior=PermissionBehavior.ALLOW,
                    decision_reason=DecisionReason(
                        type="mode",
                        message="Approved by user",
                    ),
                )
            else:
                self.denial_tracker.record_denial(tool_name, "user_denied")
                return PermissionDecision(
                    behavior=PermissionBehavior.DENY,
                    decision_reason=DecisionReason(
                        type="mode",
                        message="Denied by user",
                    ),
                )

        return inner_result

    def check_permission(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        tool_check_permissions: Callable[[dict, Any], PermissionDecision] | None = None,
        requires_user_interaction: bool = False,
        path_field: str | None = None,
    ) -> PermissionDecision:
        """
        Full permission check - inner + outer pipeline.

        This is the main entry point for permission checking.
        """
        if self.denial_tracker.should_abort():
            return PermissionDecision(
                behavior=PermissionBehavior.DENY,
                decision_reason=DecisionReason(
                    type="circuit_breaker",
                    message="Too many consecutive denials, aborting",
                ),
                message="Circuit breaker triggered: too many denials",
            )

        inner_result = self.check_permission_inner(
            tool_name,
            input_data,
            tool_check_permissions,
            requires_user_interaction,
            path_field,
        )

        return self.check_permission_outer(inner_result, tool_name, input_data)

    def _can_sandbox_auto_allow(
        self, tool_name: str, input_data: dict[str, Any]
    ) -> bool:
        """Check if sandbox can auto-allow in ask mode."""
        if tool_name.lower() != "bash":
            return False

        sandbox_enabled = input_data.get("sandbox", False)
        auto_allow = input_data.get("sandbox_auto_allow", False)

        return sandbox_enabled and auto_allow


def create_default_pipeline(
    *,
    deny_tools: list[str] | None = None,
    ask_tools: list[str] | None = None,
    allow_tools: list[str] | None = None,
    mode: PermissionMode = PermissionMode.DEFAULT,
    approval_callback: Callable[[str, dict], bool] | None = None,
) -> PermissionPipeline:
    """Create a permission pipeline with default rules."""
    from .context import build_default_permission_context

    context = build_default_permission_context(
        deny_names=deny_tools,
        require_approval_for_high_risk=True,
    )

    pipeline = PermissionPipeline(
        permission_context=context,
        mode=mode,
        approval_callback=approval_callback,
    )

    for tool in deny_tools or []:
        pipeline.add_rule(
            PermissionRule(
                tool_pattern=tool,
                behavior=PermissionBehavior.DENY,
                source="default",
            )
        )

    for tool in ask_tools or []:
        pipeline.add_rule(
            PermissionRule(
                tool_pattern=tool,
                behavior=PermissionBehavior.ASK,
                source="default",
            )
        )

    for tool in allow_tools or []:
        pipeline.add_rule(
            PermissionRule(
                tool_pattern=tool,
                behavior=PermissionBehavior.ALLOW,
                source="default",
            )
        )

    return pipeline


__all__ = [
    "PermissionBehavior",
    "PermissionMode",
    "DecisionReason",
    "PermissionDecision",
    "SafetyCheckResult",
    "PermissionRule",
    "DenialRecord",
    "DenialTracker",
    "PermissionPipeline",
    "check_path_safety",
    "SENSITIVE_PATHS",
    "FORBIDDEN_PATH_PATTERNS",
    "create_default_pipeline",
]
