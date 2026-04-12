"""
Multi-provider model configuration with channel support.

Inspired by claw-code's multi-layer configuration system.

Features:
- Multi-provider support (OpenAI, Anthropic, Azure, custom)
- Channel-based routing (official, proxy, enterprise)
- Model aliases and shortcuts
- Fallback chains
- Environment-based configuration
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class Provider(str, Enum):
    """Supported model providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    DEEPSEEK = "deepseek"
    CUSTOM = "custom"


class Channel(str, Enum):
    """API channels for routing."""

    OFFICIAL = "official"  # Official API
    PROXY = "proxy"  # Third-party proxy
    ENTERPRISE = "enterprise"  # Enterprise gateway


@dataclass
class ModelEndpoint:
    """
    Model endpoint configuration.

    Supports multiple channels with automatic fallback.
    """

    provider: Provider
    base_url: str
    api_key: str | None = None
    channel: Channel = Channel.OFFICIAL

    # Rate limiting
    requests_per_minute: int | None = None
    tokens_per_minute: int | None = None

    # Timeout settings
    timeout: float = 120.0
    max_retries: int = 3

    # Health check
    health_check_url: str | None = None
    is_healthy: bool = True


@dataclass
class ModelConfig:
    """
    Enhanced model configuration with multi-provider support.

    Features:
    - Model aliases (e.g., "gpt4" -> "gpt-4-turbo")
    - Channel routing (official, proxy, enterprise)
    - Fallback chains
    - Per-model parameters

    Example:
        config = ModelConfig(
            model_name="gpt-4-turbo",
            endpoints={
                Channel.OFFICIAL: ModelEndpoint(
                    provider=Provider.OPENAI,
                    base_url="https://api.openai.com/v1",
                    api_key="sk-...",
                ),
                Channel.PROXY: ModelEndpoint(
                    provider=Provider.OPENAI,
                    base_url="https://proxy.example.com/v1",
                    api_key="proxy-key",
                ),
            },
            preferred_channel=Channel.PROXY,
        )
    """

    model_name: str
    temperature: float = 1.0
    top_p: float = 0.95
    max_tokens: int | None = None
    stream: bool = True

    # Multi-channel endpoints
    endpoints: dict[Channel, ModelEndpoint] = field(default_factory=dict)
    preferred_channel: Channel = Channel.OFFICIAL

    # Fallback chain
    fallback_models: list[str] = field(default_factory=list)

    # Model aliases
    aliases: dict[str, str] = field(
        default_factory=lambda: {
            "gpt4": "gpt-4-turbo",
            "gpt4o": "gpt-4o",
            "gpt35": "gpt-3.5-turbo",
            "claude3": "claude-3-opus-20240229",
            "claude35": "claude-3-5-sonnet-20241022",
            "haiku": "claude-3-5-haiku-20241022",
            "sonnet": "claude-3-5-sonnet-20241022",
            "opus": "claude-3-opus-20240229",
            "deepseek": "deepseek-chat",
            "deepseek-coder": "deepseek-coder",
        }
    )

    # Provider-specific defaults
    provider_defaults: dict[Provider, dict[str, Any]] = field(
        default_factory=lambda: {
            Provider.OPENAI: {
                "base_url": "https://api.openai.com/v1",
            },
            Provider.ANTHROPIC: {
                "base_url": "https://api.anthropic.com",
            },
            Provider.DEEPSEEK: {
                "base_url": "https://api.deepseek.com",
            },
        }
    )

    def resolve_model_name(self, name: str | None = None) -> str:
        """
        Resolve model name, expanding aliases.

        Args:
            name: Model name or alias (uses self.model_name if None)

        Returns:
            Full model name
        """
        name = name or self.model_name
        return self.aliases.get(name, name)

    def get_endpoint(self, channel: Channel | None = None) -> ModelEndpoint | None:
        """
        Get endpoint for specified channel.

        Args:
            channel: Target channel (uses preferred_channel if None)

        Returns:
            ModelEndpoint or None if not configured
        """
        channel = channel or self.preferred_channel
        return self.endpoints.get(channel)

    def get_active_endpoint(self) -> ModelEndpoint | None:
        """
        Get active endpoint with fallback logic.

        Priority:
        1. Preferred channel if healthy
        2. Any other healthy channel
        3. Preferred channel even if unhealthy
        """
        # Try preferred channel first
        endpoint = self.get_endpoint(self.preferred_channel)
        if endpoint and endpoint.is_healthy:
            return endpoint

        # Try other channels
        for channel in Channel:
            if channel == self.preferred_channel:
                continue
            endpoint = self.get_endpoint(channel)
            if endpoint and endpoint.is_healthy:
                return endpoint

        # Fallback to preferred channel
        return self.get_endpoint(self.preferred_channel)

    def get_fallback_chain(self) -> list[str]:
        """
        Get model fallback chain.

        Returns:
            List of model names to try in order
        """
        resolved_name = self.resolve_model_name()
        chain = [resolved_name]

        for fallback in self.fallback_models:
            resolved = self.resolve_model_name(fallback)
            if resolved not in chain:
                chain.append(resolved)

        return chain


@dataclass
class ModelRegistry:
    """
    Central registry for all model configurations.

    Manages multiple model configs and provides routing logic.
    """

    configs: dict[str, ModelConfig] = field(default_factory=dict)
    default_model: str = "gpt-4-turbo"

    def register(self, name: str, config: ModelConfig) -> None:
        """Register a model configuration."""
        self.configs[name] = config

    def get(self, name: str) -> ModelConfig | None:
        """Get model configuration by name or alias."""
        # Try exact match
        if name in self.configs:
            return self.configs[name]

        # Try resolving alias
        for config in self.configs.values():
            resolved = config.resolve_model_name(name)
            if resolved == config.resolve_model_name():
                return config

        return None

    def get_or_default(self, name: str | None = None) -> ModelConfig:
        """Get model config or return default."""
        if name:
            config = self.get(name)
            if config:
                return config

        return self.configs.get(self.default_model) or ModelConfig(
            model_name=self.default_model
        )


# Pre-configured model templates
MODEL_TEMPLATES = {
    "gpt-4-turbo": ModelConfig(
        model_name="gpt-4-turbo",
        temperature=0.7,
        fallback_models=["gpt-4", "gpt-3.5-turbo"],
    ),
    "claude-3-5-sonnet": ModelConfig(
        model_name="claude-3-5-sonnet-20241022",
        temperature=0.7,
        fallback_models=["claude-3-opus-20240229", "claude-3-5-haiku-20241022"],
    ),
    "claude-3-5-haiku": ModelConfig(
        model_name="claude-3-5-haiku-20241022",
        temperature=0.7,
        aliases={"haiku": "claude-3-5-haiku-20241022"},
    ),
    "deepseek-chat": ModelConfig(
        model_name="deepseek-chat",
        temperature=0.7,
        aliases={"deepseek": "deepseek-chat"},
    ),
}


def create_model_config_from_env(
    provider: Provider = Provider.OPENAI,
    channel: Channel = Channel.OFFICIAL,
) -> ModelConfig:
    """
    Create model configuration from environment variables.

    Environment variables:
    - {PROVIDER}_API_KEY: API key for provider
    - {PROVIDER}_BASE_URL: Custom base URL for provider
    - MODEL_NAME: Default model name
    - TEMPERATURE: Default temperature
    - MAX_TOKENS: Default max tokens

    Example:
        # .env
        OPENAI_API_KEY=sk-...
        OPENAI_BASE_URL=https://api.openai.com/v1
        MODEL_NAME=gpt-4-turbo
    """
    import os

    prefix = provider.value.upper()

    api_key = os.getenv(f"{prefix}_API_KEY")
    base_url = os.getenv(f"{prefix}_BASE_URL")

    model_name = os.getenv("MODEL_NAME", "gpt-4-turbo")
    temperature = float(os.getenv("TEMPERATURE", "0.7"))
    max_tokens = int(os.getenv("MAX_TOKENS")) if os.getenv("MAX_TOKENS") else None

    endpoint = ModelEndpoint(
        provider=provider,
        base_url=base_url or f"https://api.{provider.value}.com/v1",
        api_key=api_key,
        channel=channel,
    )

    return ModelConfig(
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        endpoints={channel: endpoint},
        preferred_channel=channel,
    )


__all__ = [
    "Provider",
    "Channel",
    "ModelEndpoint",
    "ModelConfig",
    "ModelRegistry",
    "MODEL_TEMPLATES",
    "create_model_config_from_env",
]
