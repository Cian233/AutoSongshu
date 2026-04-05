from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class HistoryEvent:
    title: str
    detail: str
    category: str = "general"
    timestamp: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "detail": self.detail,
            "category": self.category,
            "timestamp": self.timestamp,
        }


@dataclass
class HistoryLog:
    events: list[HistoryEvent] = field(default_factory=list)
    session_id: str = ""
    max_events: int = 500

    def add(self, title: str, detail: str, category: str = "general") -> HistoryEvent:
        event = HistoryEvent(title=title, detail=detail, category=category)
        self.events.append(event)
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events :]
        return event

    def add_tool_call(
        self, tool_name: str, arguments: dict[str, Any] | None = None
    ) -> HistoryEvent:
        args_summary = ""
        if arguments:
            try:
                import json

                args_str = json.dumps(arguments, ensure_ascii=False, default=str)
                if len(args_str) > 200:
                    args_str = args_str[:197] + "..."
                args_summary = f" | args: {args_str}"
            except Exception:
                pass
        return self.add(
            title=f"Tool: {tool_name}",
            detail=f"Called tool {tool_name}{args_summary}",
            category="tool_call",
        )

    def add_tool_result(
        self, tool_name: str, success: bool, summary: str | None = None
    ) -> HistoryEvent:
        status = "succeeded" if success else "failed"
        detail = f"Tool {tool_name} {status}"
        if summary:
            truncated = summary[:300] if len(summary) > 300 else summary
            detail = f"{detail}: {truncated}"
        return self.add(
            title=f"Tool Result: {tool_name}",
            detail=detail,
            category="tool_result",
        )

    def add_model_call(
        self, model_name: str, input_tokens: int, output_tokens: int
    ) -> HistoryEvent:
        return self.add(
            title="Model Call",
            detail=f"Model {model_name} | {input_tokens} in / {output_tokens} out tokens",
            category="model",
        )

    def add_user_message(self, content: str) -> HistoryEvent:
        truncated = content[:200] if len(content) > 200 else content
        return self.add(
            title="User Message",
            detail=truncated,
            category="user",
        )

    def add_assistant_message(self, content: str) -> HistoryEvent:
        truncated = content[:200] if len(content) > 200 else content
        return self.add(
            title="Assistant Message",
            detail=truncated,
            category="assistant",
        )

    def add_error(self, error_message: str, context: str | None = None) -> HistoryEvent:
        detail = error_message
        if context:
            detail = f"{context}: {error_message}"
        return self.add(
            title="Error",
            detail=detail[:500],
            category="error",
        )

    def add_session_event(self, event_type: str, description: str) -> HistoryEvent:
        return self.add(
            title=f"Session: {event_type}",
            detail=description,
            category="session",
        )

    def clear(self) -> None:
        self.events.clear()

    def get_events_by_category(self, category: str) -> list[HistoryEvent]:
        return [event for event in self.events if event.category == category]

    def get_recent_events(self, limit: int = 20) -> list[HistoryEvent]:
        return list(self.events[-limit:])

    def to_dict_list(self) -> list[dict[str, str]]:
        return [event.to_dict() for event in self.events]

    def as_markdown(self) -> str:
        lines = ["# Session History", ""]
        if self.session_id:
            lines.append(f"Session: {self.session_id}")
            lines.append("")
        if not self.events:
            lines.append("_No events recorded._")
            return "\n".join(lines)

        current_category: str | None = None
        for event in self.events:
            if event.category != current_category:
                current_category = event.category
                lines.append(f"## {current_category.title()}")
            lines.append(f"- [{event.timestamp}] {event.title}: {event.detail}")
        return "\n".join(lines)

    def summary_dict(self) -> dict[str, Any]:
        category_counts: dict[str, int] = {}
        for event in self.events:
            category_counts[event.category] = category_counts.get(event.category, 0) + 1
        return {
            "session_id": self.session_id,
            "total_events": len(self.events),
            "category_counts": category_counts,
            "first_event": self.events[0].timestamp if self.events else None,
            "last_event": self.events[-1].timestamp if self.events else None,
        }


__all__ = ["HistoryEvent", "HistoryLog"]
