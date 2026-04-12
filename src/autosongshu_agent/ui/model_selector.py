"""
UI components for model selection and switching.

Provides reusable components for CLI and Web interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..core.config.model_config import (
    ModelConfig,
    ModelRegistry,
    Channel,
    Provider,
)
from ..core.config.model_switcher import (
    ModelSwitcher,
    SwitchReason,
)


@dataclass
class ModelOption:
    """Model option for UI display."""

    name: str
    display_name: str
    provider: str
    channel: str
    is_healthy: bool
    is_current: bool


def format_model_display_name(config: ModelConfig) -> str:
    """
    Format model name for display.

    Examples:
        gpt-4-turbo -> "GPT-4 Turbo"
        claude-3-5-sonnet-20241022 -> "Claude 3.5 Sonnet"
    """
    name = config.model_name

    # Common replacements
    replacements = {
        "gpt-4-turbo": "GPT-4 Turbo",
        "gpt-4o": "GPT-4o",
        "gpt-3.5-turbo": "GPT-3.5 Turbo",
        "claude-3-5-sonnet": "Claude 3.5 Sonnet",
        "claude-3-5-haiku": "Claude 3.5 Haiku",
        "claude-3-opus": "Claude 3 Opus",
        "deepseek-chat": "DeepSeek Chat",
        "deepseek-coder": "DeepSeek Coder",
    }

    for key, value in replacements.items():
        if name.startswith(key):
            return value

    # Fallback: capitalize and replace dashes
    return name.replace("-", " ").title()


def get_model_options(
    registry: ModelRegistry,
    current_model: str,
) -> list[ModelOption]:
    """
    Get all available model options for UI.

    Args:
        registry: Model registry
        current_model: Current model name

    Returns:
        List of ModelOption for display
    """
    options = []

    for name, config in registry.configs.items():
        endpoint = config.get_active_endpoint()

        options.append(
            ModelOption(
                name=name,
                display_name=format_model_display_name(config),
                provider=endpoint.provider.value if endpoint else "unknown",
                channel=endpoint.channel.value if endpoint else "unknown",
                is_healthy=endpoint.is_healthy if endpoint else False,
                is_current=(config.resolve_model_name() == current_model),
            )
        )

    return options


class ModelSelectorUI:
    """
    UI component for model selection.

    Works in both CLI and Web contexts.
    """

    def __init__(
        self,
        switcher: ModelSwitcher,
        on_change: Callable[[str], None] | None = None,
    ):
        self.switcher = switcher
        self.on_change = on_change

    def get_current_display_name(self) -> str:
        """Get display name of current model."""
        config = self.switcher.get_current_config()
        if config:
            return format_model_display_name(config)
        return self.switcher.get_current_model()

    def select_model(self, model_name: str) -> bool:
        """
        Select a model.

        Args:
            model_name: Model name or alias

        Returns:
            True if successful
        """
        success = self.switcher.switch(model_name, SwitchReason.MANUAL)

        if success and self.on_change:
            self.on_change(self.switcher.get_current_model())

        return success

    def render_cli(self) -> str:
        """
        Render CLI menu for model selection.

        Returns:
            Formatted string for CLI display
        """
        options = get_model_options(
            self.switcher.registry,
            self.switcher.get_current_model(),
        )

        lines = [
            "Available Models:",
            "-" * 40,
        ]

        for opt in options:
            marker = "→" if opt.is_current else " "
            health = "✓" if opt.is_healthy else "✗"
            lines.append(f"{marker} {opt.display_name:25} [{opt.provider:10}] {health}")

        lines.append("-" * 40)
        lines.append(f"Current: {self.get_current_display_name()}")

        return "\n".join(lines)

    def render_web(self) -> dict[str, Any]:
        """
        Render data for Web UI.

        Returns:
            Dict with model data for JSON response
        """
        options = get_model_options(
            self.switcher.registry,
            self.switcher.get_current_model(),
        )

        return {
            "current_model": self.switcher.get_current_model(),
            "current_display_name": self.get_current_display_name(),
            "current_channel": self.switcher.current_channel.value,
            "options": [
                {
                    "name": opt.name,
                    "display_name": opt.display_name,
                    "provider": opt.provider,
                    "channel": opt.channel,
                    "is_healthy": opt.is_healthy,
                    "is_current": opt.is_current,
                }
                for opt in options
            ],
            "history": [
                {
                    "from": event.from_model,
                    "to": event.to_model,
                    "reason": event.reason.value,
                    "timestamp": event.timestamp,
                }
                for event in self.switcher.get_switch_history(limit=5)
            ],
        }


class ChannelSelectorUI:
    """
    UI component for channel selection.
    """

    def __init__(
        self,
        switcher: ModelSwitcher,
        on_change: Callable[[Channel], None] | None = None,
    ):
        self.switcher = switcher
        self.on_change = on_change

    def get_available_channels(self) -> list[dict[str, Any]]:
        """Get available channels for current model."""
        config = self.switcher.get_current_config()
        if not config:
            return []

        channels = []
        for channel, endpoint in config.endpoints.items():
            channels.append(
                {
                    "name": channel.value,
                    "base_url": endpoint.base_url,
                    "is_healthy": endpoint.is_healthy,
                    "is_current": (channel == self.switcher.current_channel),
                }
            )

        return channels

    def select_channel(self, channel: Channel) -> bool:
        """Select a channel."""
        # This would update the switcher's current channel
        # Implementation depends on how we want to handle channel switching
        if self.on_change:
            self.on_change(channel)
        return True


__all__ = [
    "ModelOption",
    "format_model_display_name",
    "get_model_options",
    "ModelSelectorUI",
    "ChannelSelectorUI",
]
