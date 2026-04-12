"""Configuration tool.

Ported from claw-code's Config tool. Allows the agent to read and modify
runtime configuration during an assessment session.
"""
from __future__ import annotations

import json
from typing import Any

from agentscope.tool import ToolResponse

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime
from .registry import registry
from .utils import _tool_response, _error_response

registry.create_group(
    "config",
    description="配置工具：获取或设置运行时配置。",
    risk_level=ToolRiskLevel.MEDIUM,
)


@registry.register(
    "config",
    description="获取当前运行时配置信息。返回浏览器、沙箱、授权范围等配置详情。",
    risk_level=ToolRiskLevel.LOW,
    dedupe=True,
)
def config_get(
    runtime: PentestRuntime,
    section: str = "",
) -> ToolResponse:
    """Get runtime configuration.

    Args:
        section: Config section to retrieve: "browser", "sandbox", "engagement", "scope", or empty for all.
    """
    try:
        metadata = runtime._session_metadata

        if section.strip():
            section = section.strip().lower()
            result = metadata.get(section, {})
            if not result:
                return _tool_response({"ok": False, "error": f"未知配置段: {section}"})
            return _tool_response({"ok": True, "section": section, "config": result})

        # Return all config (redact sensitive values)
        safe_metadata = json.loads(json.dumps(metadata, default=str))
        return _tool_response({
            "ok": True,
            "config": safe_metadata,
        })
    except Exception as exc:
        return _error_response(exc)


@registry.register(
    "config",
    description="设置运行时配置。允许在评估过程中动态调整配置。",
    risk_level=ToolRiskLevel.MEDIUM,
    dedupe=False,
    invalidates_cache=True,
)
def config_set(
    runtime: PentestRuntime,
    key: str,
    value: str,
) -> ToolResponse:
    """Set a runtime configuration value.

    Args:
        key: Configuration key (dot-separated, e.g. "browser.ignore_https_errors").
        value: New value (will be parsed as JSON if possible).
    """
    try:
        # Parse value
        try:
            parsed_value = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            parsed_value = value

        # Navigate to the config section
        parts = key.strip().split(".")
        target = runtime._session_metadata
        for part in parts[:-1]:
            if isinstance(target, dict):
                target = target.setdefault(part, {})
            else:
                return _tool_response({"ok": False, "error": f"无法设置 {key}: 路径中段不是对象"})

        if isinstance(target, dict):
            target[parts[-1]] = parsed_value
        else:
            return _tool_response({"ok": False, "error": f"无法设置 {key}"})

        return _tool_response({
            "ok": True,
            "key": key,
            "value": parsed_value,
            "message": f"配置 {key} 已更新",
        })
    except Exception as exc:
        return _error_response(exc)
