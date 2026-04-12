from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable


class ToolRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Permission rules (ported from claw-code's PermissionRule)
# ---------------------------------------------------------------------------

class _RuleMatcher(str, Enum):
    """How a permission rule matches tool input."""
    ANY = "any"           # Match any input (e.g. sandbox_run_python(*))
    EXACT = "exact"       # Exact match on extracted subject
    PREFIX = "prefix"     # Prefix match on extracted subject


@dataclass(frozen=True)
class PermissionRule:
    """A single allow/deny rule for a specific tool.

    Syntax examples (parsed from string):
        "sandbox_run_python"          -> Any matcher
        "sandbox_run_python(*)"       -> Any matcher
        "http_request(https://*)"     -> Prefix matcher on url
        "bash(git log)"               -> Exact matcher on command
    """
    raw: str
    tool_name: str
    matcher_type: _RuleMatcher = _RuleMatcher.ANY
    matcher_value: str = ""

    @classmethod
    def parse(cls, raw: str) -> "PermissionRule":
        raw = raw.strip()
        if "(" in raw and raw.endswith(")"):
            tool_name = raw[: raw.index("(")].strip()
            inner = raw[raw.index("(") + 1 : -1].strip()
            if inner == "*" or inner == "":
                return cls(raw=raw, tool_name=tool_name.lower(), matcher_type=_RuleMatcher.ANY)
            if inner.endswith("*"):
                return cls(
                    raw=raw,
                    tool_name=tool_name.lower(),
                    matcher_type=_RuleMatcher.PREFIX,
                    matcher_value=inner[:-1],
                )
            return cls(
                raw=raw,
                tool_name=tool_name.lower(),
                matcher_type=_RuleMatcher.EXACT,
                matcher_value=inner,
            )
        return cls(raw=raw, tool_name=raw.lower(), matcher_type=_RuleMatcher.ANY)

    def matches(self, tool_name: str, arguments: dict[str, Any] | None = None) -> bool:
        if tool_name.lower() != self.tool_name:
            return False
        if self.matcher_type == _RuleMatcher.ANY:
            return True
        subject = _extract_permission_subject(arguments)
        if subject is None:
            return self.matcher_type == _RuleMatcher.ANY
        if self.matcher_type == _RuleMatcher.EXACT:
            return subject == self.matcher_value
        if self.matcher_type == _RuleMatcher.PREFIX:
            return subject.startswith(self.matcher_value)
        return False


def _extract_permission_subject(arguments: dict[str, Any] | None) -> str | None:
    """Extract the primary subject from tool arguments for rule matching."""
    if not arguments or not isinstance(arguments, dict):
        return None
    for key in (
        "command", "path", "file_path", "filePath",
        "url", "pattern", "code", "script_path",
        "message", "query", "prompt",
    ):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# ---------------------------------------------------------------------------
# Permission policy with allow/deny rules and persistence
# ---------------------------------------------------------------------------

@dataclass
class PermissionPolicy:
    """Manages allow/deny rules with file-based persistence.

    Decision priority: deny > allow > default context check.
    """
    allow_rules: list[PermissionRule] = field(default_factory=list)
    deny_rules: list[PermissionRule] = field(default_factory=list)
    _persist_path: Path | None = field(default=None, repr=False)

    def check_allow(self, tool_name: str, arguments: dict[str, Any] | None = None) -> bool | None:
        """Check if any allow rule matches. Returns True if allowed, None if no rule matches."""
        for rule in self.allow_rules:
            if rule.matches(tool_name, arguments):
                return True
        return None

    def check_deny(self, tool_name: str, arguments: dict[str, Any] | None = None) -> bool:
        """Check if any deny rule matches."""
        for rule in self.deny_rules:
            if rule.matches(tool_name, arguments):
                return True
        return False

    def add_allow_rule(self, raw: str) -> None:
        rule = PermissionRule.parse(raw)
        # Remove existing rule for same tool+matcher to avoid duplicates
        self.allow_rules = [r for r in self.allow_rules if not (
            r.tool_name == rule.tool_name and r.matcher_type == rule.matcher_type
            and r.matcher_value == rule.matcher_value
        )]
        self.allow_rules.append(rule)
        self._persist()

    def add_deny_rule(self, raw: str) -> None:
        rule = PermissionRule.parse(raw)
        self.deny_rules = [r for r in self.deny_rules if not (
            r.tool_name == rule.tool_name and r.matcher_type == rule.matcher_type
            and r.matcher_value == rule.matcher_value
        )]
        self.deny_rules.append(rule)
        self._persist()

    def remove_allow_rule(self, raw: str) -> bool:
        rule = PermissionRule.parse(raw)
        before = len(self.allow_rules)
        self.allow_rules = [r for r in self.allow_rules if not (
            r.tool_name == rule.tool_name and r.matcher_type == rule.matcher_type
            and r.matcher_value == rule.matcher_value
        )]
        if len(self.allow_rules) < before:
            self._persist()
            return True
        return False

    def clear_allow_rules(self) -> None:
        self.allow_rules.clear()
        self._persist()

    def get_rules_summary(self) -> dict[str, Any]:
        return {
            "allow_rules": [r.raw for r in self.allow_rules],
            "deny_rules": [r.raw for r in self.deny_rules],
        }

    def load(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            self.allow_rules = [PermissionRule.parse(r) for r in data.get("allow_rules", [])]
            self.deny_rules = [PermissionRule.parse(r) for r in data.get("deny_rules", [])]
        except Exception:
            pass

    def _persist(self) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_path.write_text(
                json.dumps(self.get_rules_summary(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tool permission context (original, unchanged)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Permission denial record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PermissionDenial:
    tool_name: str
    reason: str


# ---------------------------------------------------------------------------
# Interactive permission interceptor (updated with policy support)
# ---------------------------------------------------------------------------

ApprovalCallback = Callable[[str, dict[str, Any]], bool]


@dataclass
class InteractivePermissionInterceptor:
    context: ToolPermissionContext = field(default_factory=ToolPermissionContext)
    policy: PermissionPolicy | None = None
    approval_callback: ApprovalCallback | None = None
    denied_tools: list[PermissionDenial] = field(default_factory=list)
    pending_approvals: list[dict[str, Any]] = field(default_factory=list)

    def check_permission(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        risk_level: ToolRiskLevel | str | None = None,
    ) -> dict[str, Any]:
        # 1. Check policy deny rules (highest priority)
        if self.policy is not None and self.policy.check_deny(tool_name, arguments):
            denial = PermissionDenial(tool_name=tool_name, reason="deny_rule")
            self.denied_tools.append(denial)
            return {
                "allowed": False,
                "error": f"Tool '{tool_name}' is blocked by a deny rule.",
                "denial": denial,
            }

        # 2. Check context blocks
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

        # 3. Check policy allow rules (bypass approval)
        if self.policy is not None and self.policy.check_allow(tool_name, arguments):
            return {"allowed": True, "reason": "always_allowed"}

        # 4. Check if approval is required
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


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

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
        "spawn_agent",
        "task_create",
        "team_create",
        "cron_create",
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


def build_persistence_path(config_root: Path | None = None) -> Path:
    """Get the path for permission rule persistence."""
    if config_root is not None:
        return config_root / "permission_rules.json"
    # Fallback to user home
    from pathlib import Path as P
    home = P.home()
    return home / ".autosongshu" / "permission_rules.json"


__all__ = [
    "ToolRiskLevel",
    "PermissionRule",
    "_RuleMatcher",
    "PermissionPolicy",
    "ToolPermissionContext",
    "PermissionDenial",
    "ApprovalCallback",
    "InteractivePermissionInterceptor",
    "DEFAULT_HIGH_RISK_TOOLS",
    "DEFAULT_CRITICAL_PREFIXES",
    "build_default_permission_context",
    "build_persistence_path",
    "_extract_permission_subject",
]
