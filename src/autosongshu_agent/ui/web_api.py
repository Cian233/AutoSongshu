"""
Web API extensions for new features.

FastAPI endpoints for model management, state access, and permission rules.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from ..core.config.model_config import (
    ModelConfig,
    ModelRegistry,
    create_model_config_from_env,
)
from ..core.config.model_switcher import (
    ModelSwitcher,
    SwitchReason,
)
from ..core.permissions.persistence import (
    PersistenceMode,
    PermissionStore,
    PermissionRuleSource,
    create_permission_store_with_persistence,
)
from ..ui.model_selector import ModelSelectorUI, format_model_display_name
from ..ui.hooks import get_global_bridge
from ..ui.permissions import SessionStatusUI, PermissionRulesUI


def create_model_router(switcher: ModelSwitcher) -> APIRouter:
    """
    Create FastAPI router for model management.

    Args:
        switcher: Model switcher instance

    Returns:
        FastAPI router with model endpoints
    """
    router = APIRouter(prefix="/models", tags=["models"])

    @router.get("/")
    async def list_models() -> dict[str, Any]:
        """List all available models."""
        ui = ModelSelectorUI(switcher)
        return ui.render_web()

    @router.post("/switch")
    async def switch_model(model_name: str, reason: str = "manual") -> dict[str, Any]:
        """Switch to a different model."""
        try:
            switch_reason = SwitchReason(reason)
        except ValueError:
            switch_reason = SwitchReason.MANUAL

        success = switcher.switch(model_name, switch_reason)

        if not success:
            raise HTTPException(
                status_code=400, detail=f"Model '{model_name}' not found"
            )

        return {
            "success": True,
            "current_model": switcher.get_current_model(),
            "display_name": format_model_display_name(switcher.get_current_config()),
        }

    @router.post("/fallback")
    async def switch_to_fallback() -> dict[str, Any]:
        """Switch to fallback model."""
        success = switcher.switch_to_fallback()

        if not success:
            raise HTTPException(status_code=400, detail="No fallback model available")

        return {
            "success": True,
            "current_model": switcher.get_current_model(),
        }

    @router.get("/history")
    async def get_switch_history(limit: int = 10) -> list[dict[str, Any]]:
        """Get model switch history."""
        history = switcher.get_switch_history(limit)

        return [
            {
                "from_model": event.from_model,
                "to_model": event.to_model,
                "reason": event.reason.value,
                "timestamp": event.timestamp,
                "channel": event.channel.value,
            }
            for event in history
        ]

    return router


def create_state_router() -> APIRouter:
    """
    Create FastAPI router for state management.

    Returns:
        FastAPI router with state endpoints
    """
    router = APIRouter(prefix="/state", tags=["state"])

    @router.get("/")
    async def get_state() -> dict[str, Any]:
        """Get current application state."""
        bridge = get_global_bridge()
        state = bridge.get_state()

        # Convert dataclass to dict
        if hasattr(state, "__dict__"):
            return vars(state)
        return state

    @router.post("/update")
    async def update_state(updates: dict[str, Any]) -> dict[str, Any]:
        """Update application state."""
        bridge = get_global_bridge()

        def updater(state: Any) -> Any:
            if hasattr(state, "__dict__"):
                state_dict = vars(state)
                state_dict.update(updates)
                return state.__class__(**state_dict)
            return {**state, **updates}

        bridge.update_state(updater)

        return {"success": True}

    @router.get("/session")
    async def get_session_status() -> dict[str, Any]:
        """Get session status."""
        bridge = get_global_bridge()
        state = bridge.get_state()

        ui = SessionStatusUI(state if isinstance(state, dict) else vars(state))
        return ui.render_web()

    return router


def create_permission_router(
    store: PermissionStore | None = None,
) -> APIRouter:
    """
    Create FastAPI router for permission management.

    Args:
        store: Permission store instance (creates default if None)

    Returns:
        FastAPI router with permission endpoints
    """
    router = APIRouter(prefix="/permissions", tags=["permissions"])
    _store = store or create_permission_store_with_persistence()

    @router.get("/")
    async def list_rules() -> dict[str, Any]:
        """List all permission rules."""
        ui = PermissionRulesUI(_store)
        return ui.render_web()

    @router.post("/rules")
    async def add_rule(
        tool_pattern: str,
        behavior: str,
        source: PermissionRuleSource = "userSettings",
        content_pattern: str | None = None,
    ) -> dict[str, Any]:
        """Add a new permission rule."""
        ui = PermissionRulesUI(_store)
        success = ui.add_rule(tool_pattern, behavior, source, content_pattern)

        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid behavior: {behavior}",
            )

        return {"success": True, "message": f"Rule added to {source}"}

    @router.delete("/rules")
    async def remove_rule(
        tool_pattern: str,
        behavior: str,
        source: PermissionRuleSource = "userSettings",
    ) -> dict[str, Any]:
        """Remove a permission rule."""
        ui = PermissionRulesUI(_store)
        success = ui.remove_rule(tool_pattern, behavior, source)

        if not success:
            raise HTTPException(
                status_code=404,
                detail="Rule not found",
            )

        return {"success": True}

    @router.post("/clear-session")
    async def clear_session_rules() -> dict[str, Any]:
        """Clear all session-only rules."""
        _store.clear_session_rules()
        return {"success": True, "message": "Session rules cleared"}

    @router.post("/export")
    async def export_rules() -> dict[str, Any]:
        """Export all rules for backup."""
        return _store.export_rules_to_dict()

    @router.post("/import")
    async def import_rules(data: dict[str, Any]) -> dict[str, Any]:
        """Import rules from backup."""
        count = _store.import_rules_from_dict(data)
        return {"success": True, "imported_count": count}

    return router


__all__ = [
    "create_model_router",
    "create_state_router",
    "create_permission_router",
]
