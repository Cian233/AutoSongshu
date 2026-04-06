"""Enhanced tool registry with lookup and caching.

Provides frozen dataclass-based tool information and case-insensitive
lookup, inspired by claw-code's execution registry pattern.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from agentscope.tool import ToolResponse

from ..permissions import ToolRiskLevel
from ..runtime import PentestRuntime


@dataclass(frozen=True)
class ToolInfo:
    """Frozen tool metadata for fast lookup.

    Similar to claw-code's MirroredTool pattern.
    """

    name: str
    description: str
    group_name: str
    risk_level: ToolRiskLevel
    requires_approval: bool = False
    source_hint: str = ""

    @property
    def name_lower(self) -> str:
        """Lowercase name for case-insensitive lookup."""
        return self.name.lower()


@dataclass(frozen=True)
class ToolSnapshot:
    """Snapshot of all available tools for fast loading.

    Inspired by claw-code's JSON snapshot pattern.
    """

    tools: tuple[ToolInfo, ...] = field(default_factory=tuple)
    groups: tuple[str, ...] = field(default_factory=tuple)

    def get_tool(self, name: str) -> ToolInfo | None:
        """Case-insensitive tool lookup."""
        name_lower = name.lower()
        for tool in self.tools:
            if tool.name_lower == name_lower:
                return tool
        return None

    def get_tools_by_group(self, group_name: str) -> list[ToolInfo]:
        """Get all tools in a group."""
        return [t for t in self.tools if t.group_name == group_name]

    def get_tools_by_risk(self, risk_level: ToolRiskLevel) -> list[ToolInfo]:
        """Get tools by risk level."""
        return [t for t in self.tools if t.risk_level == risk_level]

    def has_tool(self, name: str) -> bool:
        """Check if tool exists (case-insensitive)."""
        return self.get_tool(name) is not None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "group_name": t.group_name,
                    "risk_level": t.risk_level.value,
                    "requires_approval": t.requires_approval,
                }
                for t in self.tools
            ],
            "groups": list(self.groups),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolSnapshot":
        """Deserialize from dict."""
        tools = tuple(
            ToolInfo(
                name=t["name"],
                description=t.get("description", ""),
                group_name=t.get("group_name", "general"),
                risk_level=ToolRiskLevel(t.get("risk_level", "medium")),
                requires_approval=t.get("requires_approval", False),
            )
            for t in data.get("tools", [])
        )
        groups = tuple(data.get("groups", []))
        return cls(tools=tools, groups=groups)

    def save(self, path: Path) -> None:
        """Save snapshot to JSON file."""
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "ToolSnapshot":
        """Load snapshot from JSON file."""
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(data)


class ToolRegistryEnhanced:
    """Enhanced tool registry with fast lookup and caching.

    Wraps the existing ToolRegistry with immutable lookup structures.
    """

    def __init__(self) -> None:
        self._tool_map: dict[str, ToolInfo] = {}
        self._tool_list: list[ToolInfo] = []
        self._snapshot: ToolSnapshot | None = None
        self._groups: set[str] = set()

    def register_tool(
        self,
        name: str,
        description: str,
        group_name: str,
        risk_level: ToolRiskLevel = ToolRiskLevel.MEDIUM,
        requires_approval: bool = False,
    ) -> ToolInfo:
        """Register a tool and return its immutable info."""
        info = ToolInfo(
            name=name,
            description=description,
            group_name=group_name,
            risk_level=risk_level,
            requires_approval=requires_approval,
        )
        self._tool_map[name.lower()] = info
        self._tool_list.append(info)
        self._groups.add(group_name)
        self._snapshot = None  # Invalidate cache
        return info

    def get_tool(self, name: str) -> ToolInfo | None:
        """Case-insensitive tool lookup."""
        return self._tool_map.get(name.lower())

    def get_tools_by_group(self, group_name: str) -> list[ToolInfo]:
        """Get all tools in a group."""
        return [t for t in self._tool_list if t.group_name == group_name]

    def get_tools_by_risk(self, risk_level: ToolRiskLevel) -> list[ToolInfo]:
        """Get tools by risk level."""
        return [t for t in self._tool_list if t.risk_level == risk_level]

    def has_tool(self, name: str) -> bool:
        """Check if tool exists."""
        return name.lower() in self._tool_map

    @property
    def tool_count(self) -> int:
        """Total number of registered tools."""
        return len(self._tool_list)

    @property
    def all_tools(self) -> tuple[ToolInfo, ...]:
        """All registered tools as immutable tuple."""
        return tuple(self._tool_list)

    @property
    def all_groups(self) -> tuple[str, ...]:
        """All group names as immutable tuple."""
        return tuple(sorted(self._groups))

    def build_snapshot(self) -> ToolSnapshot:
        """Build a snapshot for fast loading."""
        if self._snapshot is None:
            self._snapshot = ToolSnapshot(
                tools=tuple(self._tool_list),
                groups=tuple(sorted(self._groups)),
            )
        return self._snapshot

    def summary(self) -> dict[str, Any]:
        """Get registry summary."""
        by_risk = {}
        for level in ToolRiskLevel:
            count = len(self.get_tools_by_risk(level))
            if count > 0:
                by_risk[level.value] = count

        return {
            "total_tools": self.tool_count,
            "groups": list(self.all_groups),
            "by_risk": by_risk,
        }


# Global enhanced registry instance
enhanced_registry = ToolRegistryEnhanced()


__all__ = [
    "ToolInfo",
    "ToolSnapshot",
    "ToolRegistryEnhanced",
    "enhanced_registry",
]
