"""
Model switching and channel management.

Inspired by claw-code's model routing system.

Features:
- Runtime model switching
- Channel-based routing
- Automatic failover
- Cost optimization (route to cheaper models)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from enum import Enum

from .model_config import (
    ModelConfig,
    ModelRegistry,
    Channel,
    Provider,
)


class SwitchReason(str, Enum):
    """Reasons for model switch."""

    MANUAL = "manual"  # User-initiated
    FALLBACK = "fallback"  # Primary model failed
    COST_OPTIMIZATION = "cost"  # Switching to cheaper model
    PERFORMANCE = "performance"  # Switching for better performance
    CAPABILITY = "capability"  # Model lacks required capability


@dataclass
class ModelSwitchEvent:
    """Event emitted when model is switched."""

    from_model: str
    to_model: str
    reason: SwitchReason
    channel: Channel
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelSwitcher:
    """
    Manages runtime model switching.

    Features:
    - Switch models at runtime
    - Track switch history
    - Automatic failover
    - Cost-based routing

    Example:
        switcher = ModelSwitcher(registry)

        # Switch model
        switcher.switch("claude-3-5-sonnet", SwitchReason.MANUAL)

        # Get current model
        current = switcher.get_current_model()

        # Auto failover on error
        try:
            result = await call_model(current)
        except RateLimitError:
            switcher.switch_to_fallback()
    """

    registry: ModelRegistry
    current_model: str = ""
    current_channel: Channel = Channel.OFFICIAL

    # Switch history
    history: list[ModelSwitchEvent] = field(default_factory=list)
    max_history: int = 100

    # Callbacks
    on_switch: Callable[[ModelSwitchEvent], None] | None = None

    # Failover config
    auto_failover: bool = True
    failover_delay_seconds: float = 1.0

    def __post_init__(self):
        if not self.current_model:
            self.current_model = self.registry.default_model

    def switch(
        self,
        model_name: str,
        reason: SwitchReason = SwitchReason.MANUAL,
        channel: Channel | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Switch to a different model.

        Args:
            model_name: Target model name
            reason: Reason for switch
            channel: Optional channel override
            metadata: Additional metadata

        Returns:
            True if switch successful, False if model not found
        """
        config = self.registry.get(model_name)
        if not config:
            return False

        from_model = self.current_model
        self.current_model = config.resolve_model_name(model_name)

        if channel:
            self.current_channel = channel

        event = ModelSwitchEvent(
            from_model=from_model,
            to_model=self.current_model,
            reason=reason,
            channel=self.current_channel,
            timestamp=self._get_timestamp(),
            metadata=metadata or {},
        )

        self._record_switch(event)

        if self.on_switch:
            self.on_switch(event)

        return True

    def switch_to_fallback(self) -> bool:
        """
        Switch to fallback model.

        Returns:
            True if switched to fallback, False if no fallback available
        """
        config = self.registry.get(self.current_model)
        if not config:
            return False

        fallback_chain = config.get_fallback_chain()

        for model in fallback_chain[1:]:  # Skip current model
            if self.switch(model, SwitchReason.FALLBACK):
                return True

        return False

    def switch_to_cheaper(self) -> bool:
        """
        Switch to a cheaper model for cost optimization.

        Returns:
            True if switched, False if already using cheapest
        """
        # Define cost hierarchy (cheaper models first)
        cost_hierarchy = [
            "gpt-3.5-turbo",
            "claude-3-5-haiku-20241022",
            "deepseek-chat",
            "gpt-4-turbo",
            "claude-3-5-sonnet-20241022",
            "gpt-4",
            "claude-3-opus-20240229",
        ]

        current_index = -1
        for i, model in enumerate(cost_hierarchy):
            if model == self.current_model:
                current_index = i
                break

        if current_index > 0:
            cheaper_model = cost_hierarchy[current_index - 1]
            return self.switch(cheaper_model, SwitchReason.COST_OPTIMIZATION)

        return False

    def get_current_model(self) -> str:
        """Get current model name."""
        return self.current_model

    def get_current_config(self) -> ModelConfig | None:
        """Get current model configuration."""
        return self.registry.get(self.current_model)

    def get_switch_history(self, limit: int = 10) -> list[ModelSwitchEvent]:
        """Get recent switch history."""
        return self.history[-limit:]

    def _record_switch(self, event: ModelSwitchEvent) -> None:
        """Record switch event in history."""
        self.history.append(event)

        # Trim history if needed
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]

    def _get_timestamp(self) -> float:
        """Get current timestamp."""
        import time

        return time.time()


@dataclass
class ChannelRouter:
    """
    Routes API calls through different channels.

    Features:
    - Channel selection based on availability
    - Load balancing across channels
    - Health checking
    """

    channels: dict[Channel, Any] = field(default_factory=dict)
    health_status: dict[Channel, bool] = field(default_factory=dict)

    def select_channel(
        self,
        preferred: Channel = Channel.OFFICIAL,
        exclude: list[Channel] | None = None,
    ) -> Channel | None:
        """
        Select best available channel.

        Args:
            preferred: Preferred channel
            exclude: Channels to exclude

        Returns:
            Selected channel or None if all unavailable
        """
        exclude = exclude or []

        # Try preferred first
        if preferred not in exclude and self.is_healthy(preferred):
            return preferred

        # Try others
        for channel in Channel:
            if channel not in exclude and self.is_healthy(channel):
                return channel

        return None

    def is_healthy(self, channel: Channel) -> bool:
        """Check if channel is healthy."""
        return self.health_status.get(channel, True)

    def mark_unhealthy(self, channel: Channel) -> None:
        """Mark channel as unhealthy."""
        self.health_status[channel] = False

    def mark_healthy(self, channel: Channel) -> None:
        """Mark channel as healthy."""
        self.health_status[channel] = True


__all__ = [
    "SwitchReason",
    "ModelSwitchEvent",
    "ModelSwitcher",
    "ChannelRouter",
]
