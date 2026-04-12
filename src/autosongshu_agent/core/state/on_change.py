"""
Centralized side effects handler for AppState changes.

This is called after EVERY state change, ensuring:
- Permission mode changes are synced to external systems
- Model changes are persisted to settings
- Config changes clear authentication caches

Inspired by claw-code's state/onChangeAppState.ts

Prior to this pattern, mode changes were relayed by only 2 of 8+ mutation paths.
Every other path mutated AppState without telling external systems.
Now, ANY setState call triggers centralized side effects.
"""

from __future__ import annotations

from typing import Any, Callable


def on_change_app_state(new_state: dict[str, Any], old_state: dict[str, Any]) -> None:
    """
    Handle centralized side effects after AppState changes.

    This is called by Store after every state change.
    Use it to sync to external systems, persist changes, etc.
    """
    # Permission mode change -> notify external systems
    old_mode = old_state.get("tool_permission_context", {}).get("mode")
    new_mode = new_state.get("tool_permission_context", {}).get("mode")
    if old_mode != new_mode:
        _sync_permission_mode_change(new_mode)

    # Model change -> persist to settings
    old_model = old_state.get("main_loop_model")
    new_model = new_state.get("main_loop_model")
    if old_model != new_model:
        _persist_model_change(new_model)

    # Settings change -> clear auth caches
    if new_state.get("settings") != old_state.get("settings"):
        _clear_auth_caches()


def _sync_permission_mode_change(new_mode: str | None) -> None:
    """Sync permission mode to external systems."""
    # In a real implementation, this would:
    # - Notify CCR (Claude Code Runtime) via SDK
    # - Update session metadata
    # - Log telemetry
    pass


def _persist_model_change(new_model: str | None) -> None:
    """Persist model change to user settings."""
    # In a real implementation, this would:
    # - Write to ~/.autosongshu/settings.json
    # - Update bootstrap state
    pass


def _clear_auth_caches() -> None:
    """Clear authentication caches when settings change."""
    # In a real implementation, this would:
    # - Clear API key helper cache
    # - Clear AWS credentials cache
    # - Clear GCP credentials cache
    pass


def create_on_change_handler(
    extra_handlers: list[Callable[[dict, dict], None]] | None = None,
) -> Callable[[dict, dict], None]:
    """
    Create a composite onChange handler.

    This allows adding custom handlers while keeping the default ones.
    """
    handlers = [on_change_app_state]
    if extra_handlers:
        handlers.extend(extra_handlers)

    def composite_handler(new_state: dict[str, Any], old_state: dict[str, Any]) -> None:
        for handler in handlers:
            try:
                handler(new_state, old_state)
            except Exception:
                # Don't let one handler break others
                pass

    return composite_handler
