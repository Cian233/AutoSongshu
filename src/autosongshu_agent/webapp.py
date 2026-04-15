from __future__ import annotations

import argparse
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import uvicorn
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .authorization_store import AuthorizationDraft
from .chat_manager import (
    ChatSessionManager,
    CreateKnowledgeFromSessionRequest,
    CreateChatSessionRequest,
    InterruptSessionRequest,
    SendMessageRequest,
)
from .config import get_cached_config, reload_config as _reload_config, save_config as _save_config
from .utils import now_iso
from .knowledge_store import (
    KnowledgeBaseDraft,
    KnowledgeBaseUpdateDraft,
    KnowledgeDocumentDraft,
)
from .interactive import InteractiveApprovalManager
from .permissions import (
    ToolRiskLevel,
    InteractivePermissionInterceptor,
    PermissionPolicy,
    build_default_permission_context,
    build_persistence_path,
)
from .commands import CommandRegistry, default_command_registry
from .exceptions import AutoSongshuError
from .auth import TokenAuthMiddleware
from .project_store import ProjectStore, ProjectCreateRequest


class KnowledgeHitTestingRequest(BaseModel):
    query: str = Field(min_length=1)
    knowledge_base_id: str | None = None
    knowledge_base_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=6, ge=1, le=20)


class ApprovalResponsePayload(BaseModel):
    approved: bool
    reason: str = ""
    remember_for_session: bool = False
    always_allow: bool = False


_approval_manager: InteractiveApprovalManager | None = None
_permission_policy: PermissionPolicy | None = None


def get_permission_policy() -> PermissionPolicy:
    global _permission_policy
    if _permission_policy is None:
        persist_path = build_persistence_path()
        _permission_policy = PermissionPolicy(_persist_path=persist_path)
        _permission_policy.load()
    return _permission_policy


def get_approval_manager() -> InteractiveApprovalManager:
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = InteractiveApprovalManager(
            policy=get_permission_policy(),
        )
    return _approval_manager


def set_approval_emit_callback(
    callback: Callable[[str, dict[str, Any]], None] | None,
) -> None:
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = InteractiveApprovalManager(
            emit_callback=callback,
            policy=get_permission_policy(),
        )
    else:
        _approval_manager.emit_callback = callback


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _chat_summary(sessions: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(sessions),
        "running": sum(
            1 for item in sessions if item.get("status") in {"running", "interrupting"}
        ),
        "idle": sum(1 for item in sessions if item.get("status") == "idle"),
        "error": sum(1 for item in sessions if item.get("status") == "error"),
    }


def _asset_version(web_root: Path) -> str:
    latest_mtime = max(
        int(path.stat().st_mtime) for path in web_root.rglob("*") if path.is_file()
    )
    return str(latest_mtime)


def _decode_upload_bytes(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return raw.decode(encoding)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _uvicorn_run_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    project_root = _project_root()
    src_root = (project_root / "src").resolve()
    runtime_excludes = [
        str((project_root / "artifacts").resolve()),
        str((project_root / "data").resolve()),
        str((project_root / "configs" / "data").resolve()),
        str((project_root / ".git").resolve()),
        str((project_root / ".venv").resolve()),
        "__pycache__",
        "**/__pycache__/**",
        "*.pyc",
        "*.pyo",
        "*.pyd",
        "*.egg-info/**",
        ".pytest_cache/**",
        ".mypy_cache/**",
        ".ruff_cache/**",
        "*.db",
        "*.db-*",
        "*.sqlite",
        "*.sqlite3",
        "*.jsonl",
        "*.log",
    ]
    return {
        "app": "autosongshu_agent.webapp:app",
        "host": args.host,
        "port": args.port,
        "reload": args.reload,
        "reload_dirs": [str(src_root)] if args.reload else None,
        "reload_excludes": runtime_excludes if args.reload else None,
    }


def _format_sse(event_name: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    lines = [f"event: {event_name}"]
    for line in serialized.splitlines() or [""]:
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


logger = logging.getLogger(__name__)


def _safe_error_detail(exc: Exception) -> str:
    """Return a user-safe error message, never leaking internal details."""
    if isinstance(exc, AutoSongshuError):
        return str(exc)
    logger.exception("Unhandled exception in webapp")
    return "An unexpected error occurred. Please check server logs for details."


_SENSITIVE_FIELD_NAMES = frozenset({
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
})


def _mask_sensitive(data: Any, parent_key: str = "") -> Any:
    """Recursively mask sensitive field values in a dict/list structure."""
    if isinstance(data, dict):
        return {
            k: _mask_sensitive(v, parent_key=k) for k, v in data.items()
        }
    if isinstance(data, list):
        return [_mask_sensitive(item, parent_key=parent_key) for item in data]
    if parent_key.lower() in _SENSITIVE_FIELD_NAMES and isinstance(data, str):
        if len(data) <= 8:
            return "********"
        return data[:4] + "****" + data[-4:]
    return data


def _config_to_safe_dict(config: Any) -> dict[str, Any]:
    """Convert an AppConfig to a JSON-safe dict with sensitive fields masked."""
    raw = config.model_dump()
    return _mask_sensitive(raw)


class SSEHub:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.connections: dict[str, asyncio.Queue[dict[str, Any]]] = {}

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def register(self) -> tuple[str, asyncio.Queue[dict[str, Any]]]:
        connection_id = uuid4().hex
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.connections[connection_id] = queue
        return connection_id, queue

    def unregister(self, connection_id: str) -> None:
        self.connections.pop(connection_id, None)

    def broadcast_threadsafe(self, payload: dict[str, Any]) -> None:
        if self.loop is None or self.loop.is_closed():
            return
        self.loop.call_soon_threadsafe(self._broadcast_now, payload)

    def _broadcast_now(self, payload: dict[str, Any]) -> None:
        for queue in list(self.connections.values()):
            queue.put_nowait(payload)


def create_permission_interceptor_factory(
    approval_manager: InteractiveApprovalManager,
    policy: Any | None = None,
) -> Callable[[str], InteractivePermissionInterceptor]:
    def factory(session_id: str) -> InteractivePermissionInterceptor:
        def approval_callback(tool_name: str, arguments: dict[str, Any]) -> bool:
            try:
                response = approval_manager.request_approval(
                    tool_name=tool_name,
                    arguments=arguments,
                    risk_level="high",
                    session_id=session_id,
                )
                return response.approved
            except Exception:
                return False

        context = build_default_permission_context(require_approval_for_high_risk=True)
        return InteractivePermissionInterceptor(
            context=context,
            policy=policy,
            approval_callback=approval_callback,
        )

    return factory


def create_app() -> FastAPI:
    # Initialize logging before anything else
    from .logging_config import setup_logging
    project_root = _project_root()
    log_dir = project_root / "logs" if project_root else None
    setup_logging(log_dir=log_dir)

    web_root = Path(__file__).resolve().parent / "web"
    asset_version = _asset_version(web_root)
    templates = Jinja2Templates(directory=str(web_root / "templates"))
    templates.env.auto_reload = True
    manager = ChatSessionManager(project_root=project_root)
    hub = SSEHub()
    approval_manager = get_approval_manager()
    default_goal = "继续评估登录、账号与会话流程中的常见 Web 安全问题。"
    project_store = ProjectStore(data_dir=project_root / "data")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        hub.attach_loop(asyncio.get_running_loop())
        listener_id = manager.add_listener(hub.broadcast_threadsafe)
        set_approval_emit_callback(
            lambda event_type, payload: hub.broadcast_threadsafe(
                {"type": event_type, **payload}
            )
        )
        manager.set_permission_interceptor_factory(
            create_permission_interceptor_factory(
                approval_manager,
                policy=get_permission_policy(),
            )
        )
        try:
            yield
        finally:
            manager.remove_listener(listener_id)
            set_approval_emit_callback(None)
            manager.set_permission_interceptor_factory(None)
            manager.shutdown()

    app = FastAPI(title="AutoSongshu Chat", version="0.3.0", lifespan=lifespan)
    app.add_middleware(TokenAuthMiddleware)
    app.state.chat_manager = manager
    app.mount("/static", StaticFiles(directory=str(web_root / "static")), name="static")
    app.mount(
        "/artifacts",
        StaticFiles(directory=str(manager.default_artifacts_root)),
        name="artifacts",
    )

    # --- SPA support: serve production build assets if available ---
    _frontend_dist = project_root / "frontend" / "dist"
    _spa_index_path = _frontend_dist / "index.html"
    _spa_available = _spa_index_path.is_file()
    if _spa_available:
        _spa_assets_dir = _frontend_dist / "assets"
        if _spa_assets_dir.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=str(_spa_assets_dir), html=False),
                name="spa-assets",
            )
        logger.info("SPA production build detected at %s", _frontend_dist)

    @app.middleware("http")
    async def disable_browser_cache(request: Request, call_next):
        response = await call_next(request)
        if (
            request.url.path == "/"
            or request.url.path.startswith("/knowledge")
            or request.url.path.startswith("/static/")
        ):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
        return response

    def _serve_spa(request: Request) -> HTMLResponse:
        """Return the SPA index.html from the production build.

        Falls back to the legacy Jinja2 template if the build artefact is
        not available (backward compatibility).
        """
        if _spa_available:
            content = _spa_index_path.read_text(encoding="utf-8")
            response = HTMLResponse(content=content)
            response.headers["Cache-Control"] = "no-store"
            return response
        # Fallback: render the original Jinja2 template
        response = templates.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "asset_version": asset_version,
                "default_config_path": str(manager.default_config_path),
                "default_goal": default_goal,
                "default_authorization_draft": manager.get_default_authorization_draft(),
            },
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return _serve_spa(request)

    @app.get("/knowledge", response_class=HTMLResponse)
    async def knowledge_page(request: Request) -> HTMLResponse:
        return _serve_spa(request)

    @app.get("/knowledge/bases/{path:path}", response_class=HTMLResponse)
    async def knowledge_catchall(request: Request, path: str) -> HTMLResponse:
        return _serve_spa(request)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "timestamp": now_iso()}

    @app.post("/api/chat/config/reload")
    async def reload_configuration(request: Request) -> dict[str, Any]:
        """Reload configuration from the default config file on disk.

        Accepts an optional JSON body ``{"config_path": "..."}`` to reload a
        specific config file.  If omitted the manager's default config path is
        used.  The reloaded config is cached so that subsequent ``GET
        /api/chat/config`` calls return the fresh values.
        """
        try:
            body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
        except Exception:
            body = {}

        config_path = str(body.get("config_path") or manager.default_config_path)
        try:
            resolved_path = manager._resolve_config_path(config_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            new_config = _reload_config(resolved_path)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Unexpected error during config reload")
            raise HTTPException(
                status_code=500,
                detail="Failed to reload configuration. Check server logs.",
            ) from exc

        safe_dict = _config_to_safe_dict(new_config)
        return {
            "status": "reloaded",
            "config_path": resolved_path,
            "config": safe_dict,
            "timestamp": now_iso(),
        }

    @app.get("/api/chat/config")
    async def get_configuration(request: Request) -> dict[str, Any]:
        """Return the current (cached) configuration with sensitive fields masked.

        Query parameter ``config_path`` can be used to request a specific config
        file.  If the config has not been loaded yet it will be loaded now.
        """
        config_path = request.query_params.get("config_path") or str(
            manager.default_config_path
        )
        try:
            resolved_path = manager._resolve_config_path(config_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        config = get_cached_config(resolved_path)
        if config is None:
            # Not yet cached -- load it now
            try:
                from .config import load_config as _load_config
                config = _load_config(resolved_path)
            except Exception as exc:
                raise HTTPException(
                    status_code=400, detail=f"Failed to load config: {exc}"
                ) from exc

        safe_dict = _config_to_safe_dict(config)
        return {
            "config_path": resolved_path,
            "config": safe_dict,
            "timestamp": now_iso(),
        }

    @app.put("/api/chat/config")
    async def update_configuration(request: Request) -> dict[str, Any]:
        """Update selected configuration sections (compaction, etc.) and persist to YAML."""
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        config_path = str(body.get("config_path") or manager.default_config_path)
        try:
            resolved_path = manager._resolve_config_path(config_path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            config = _reload_config(resolved_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Apply compaction overrides (with type validation)
        compaction_patch = body.get("compaction")
        if isinstance(compaction_patch, dict):
            _COMPACTION_BOOL_FIELDS = {"auto", "prune", "use_token_counting"}
            for key, value in compaction_patch.items():
                if not hasattr(config.compaction, key):
                    continue
                expected_type = bool if key in _COMPACTION_BOOL_FIELDS else int
                if not isinstance(value, expected_type):
                    raise HTTPException(
                        status_code=400,
                        detail=f"compaction.{key} must be {expected_type.__name__}, got {type(value).__name__}",
                    )
                setattr(config.compaction, key, value)

        _save_config(resolved_path, config)

        safe_dict = _config_to_safe_dict(config)
        return {
            "status": "updated",
            "config_path": resolved_path,
            "config": safe_dict,
            "timestamp": now_iso(),
        }

    # ── Model routing API ──────────────────────────────────────────

    @app.get("/api/models")
    async def list_models() -> dict[str, Any]:
        """List all configured model profiles."""
        try:
            profiles = manager.get_model_profiles()
            return {"profiles": profiles, "timestamp": now_iso()}
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to list models: {exc}"
            ) from exc

    @app.put("/api/models/active")
    async def set_active_model(request: Request) -> dict[str, Any]:
        """Switch the active model profile at runtime."""
        body = await request.json()
        profile_name = body.get("profile_name", "").strip()
        if not profile_name:
            raise HTTPException(status_code=400, detail="Missing 'profile_name'")

        try:
            ok = manager.set_active_model(profile_name)
            if not ok:
                raise HTTPException(
                    status_code=404,
                    detail=f"Unknown profile '{profile_name}'",
                )
            return {
                "ok": True,
                "active_profile": profile_name,
                "timestamp": now_iso(),
            }
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to switch model: {exc}"
            ) from exc

    @app.post("/api/models")
    async def add_model_profile(request: Request) -> dict[str, Any]:
        """Add a new model profile to the config file."""
        body = await request.json()
        profile = body.get("profile")
        if not profile or not isinstance(profile, dict):
            raise HTTPException(status_code=400, detail="Missing 'profile' object")

        name = profile.get("name", "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Profile 'name' is required")
        if not profile.get("model_name", "").strip():
            raise HTTPException(status_code=400, detail="Profile 'model_name' is required")

        try:
            config_path = manager.default_config_path
            config = _reload_config(str(config_path))

            # Ensure profiles list exists
            if not config.model.profiles:
                config.model.profiles = []

            # Check for duplicate name
            existing_names = [p.get("name", "") for p in config.model.profiles]
            if name in existing_names:
                raise HTTPException(
                    status_code=409,
                    detail=f"Profile '{name}' already exists",
                )

            # Build profile dict (only include non-empty fields)
            new_profile: dict[str, Any] = {"name": name}
            for key in (
                "display_name", "provider", "model_name", "api_key", "base_url",
                "temperature", "top_p", "max_tokens", "timeout", "stream",
                "tasks", "enabled", "cost_per_1m_input", "cost_per_1m_output",
            ):
                val = profile.get(key)
                if val is not None and val != "":
                    new_profile[key] = val

            # Per-profile compaction overrides
            compaction = profile.get("compaction")
            if isinstance(compaction, dict) and compaction:
                new_profile["compaction"] = compaction

            config.model.profiles.append(new_profile)

            # Set as active if this is the first profile
            if len(config.model.profiles) == 1:
                config.model.active = name

            _save_config(str(config_path), config)

            # Refresh router in all sessions
            manager._refresh_model_routers(config)

            return {
                "ok": True,
                "profile": new_profile,
                "timestamp": now_iso(),
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to add model profile: {exc}"
            ) from exc

    @app.delete("/api/models/{profile_name}")
    async def delete_model_profile(profile_name: str) -> dict[str, Any]:
        """Remove a model profile from the config file."""
        try:
            config_path = manager.default_config_path
            config = _reload_config(str(config_path))

            if not config.model.profiles:
                raise HTTPException(status_code=404, detail="No profiles configured")

            original_len = len(config.model.profiles)
            config.model.profiles = [
                p for p in config.model.profiles
                if p.get("name") != profile_name
            ]

            if len(config.model.profiles) == original_len:
                raise HTTPException(
                    status_code=404,
                    detail=f"Profile '{profile_name}' not found",
                )

            # Clear active if it was the deleted profile
            if config.model.active == profile_name:
                config.model.active = (
                    config.model.profiles[0].get("name")
                    if config.model.profiles
                    else None
                )

            _save_config(str(config_path), config)
            manager._refresh_model_routers(config)

            return {
                "ok": True,
                "deleted": profile_name,
                "timestamp": now_iso(),
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Failed to delete model profile: {exc}"
            ) from exc

    @app.patch("/api/models/{profile_name}")
    async def update_model_profile(profile_name: str, request: Request) -> dict[str, Any]:
        """Update fields (including compaction) of an existing model profile."""
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        config_path = manager.default_config_path
        config = _reload_config(str(config_path))

        if not config.model.profiles:
            raise HTTPException(status_code=404, detail="No profiles configured")

        target = None
        for p in config.model.profiles:
            if isinstance(p, dict) and p.get("name") == profile_name:
                target = p
                break
        if target is None:
            raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' not found")

        # Merge update fields
        for key in (
            "display_name", "provider", "model_name", "api_key", "base_url",
            "temperature", "top_p", "max_tokens", "timeout", "stream",
            "tasks", "enabled", "cost_per_1m_input", "cost_per_1m_output",
        ):
            if key in body:
                target[key] = body[key]

        # Handle compaction merge
        if "compaction" in body:
            compaction_patch = body["compaction"]
            if isinstance(compaction_patch, dict) and compaction_patch:
                existing_compaction = target.get("compaction", {})
                if not isinstance(existing_compaction, dict):
                    existing_compaction = {}
                existing_compaction.update(compaction_patch)
                target["compaction"] = existing_compaction
            elif compaction_patch is None:
                target.pop("compaction", None)

        _save_config(str(config_path), config)
        manager._refresh_model_routers(config)

        return {
            "ok": True,
            "profile": target,
            "timestamp": now_iso(),
        }

    @app.get("/api/bootstrap")
    async def bootstrap() -> dict[str, Any]:
        sessions = manager.list_chat_sessions()
        return {
            "default_config_path": str(manager.default_config_path),
            "default_goal": default_goal,
            "artifact_root": str(manager.default_artifacts_root),
            "default_authorization_draft": manager.get_default_authorization_draft(),
            "authorizations": manager.list_authorizations(),
            "knowledge_bases": manager.list_knowledge_bases(),
            "chat_sessions": sessions,
            "summary": _chat_summary(sessions),
        }

    @app.get("/api/chat/events")
    async def chat_events(request: Request) -> StreamingResponse:
        hub.attach_loop(asyncio.get_running_loop())
        connection_id, queue = hub.register()

        async def event_stream():
            try:
                yield _format_sse(
                    "connected", {"type": "connected", "timestamp": now_iso()}
                )
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    event_name = str(payload.get("type") or "message")
                    yield _format_sse(event_name, payload)
            finally:
                hub.unregister(connection_id)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/authorizations")
    async def list_authorizations() -> dict[str, Any]:
        authorizations = manager.list_authorizations()
        return {"authorizations": authorizations, "total": len(authorizations)}

    @app.get("/api/commands")
    async def list_commands() -> dict[str, Any]:
        commands = default_command_registry.list_commands()
        items = []
        for cmd in commands:
            item = {
                "name": cmd.name,
                "description": cmd.description,
                "aliases": cmd.aliases,
                "usage": cmd.usage or "",
            }
            items.append(item)
        return {"commands": items, "total": len(items)}

    @app.post("/api/authorizations")
    async def create_authorization(payload: AuthorizationDraft) -> dict[str, Any]:
        try:
            return manager.create_authorization(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.get("/api/knowledge/bases")
    async def list_knowledge_bases() -> dict[str, Any]:
        items = manager.list_knowledge_bases()
        return {"items": items, "total": len(items)}

    @app.get("/api/knowledge/bootstrap")
    async def knowledge_bootstrap() -> dict[str, Any]:
        items = manager.list_knowledge_bases()
        return {
            "items": items,
            "total": len(items),
            "timestamp": now_iso(),
        }

    @app.post("/api/knowledge/bases")
    async def create_knowledge_base(payload: KnowledgeBaseDraft) -> dict[str, Any]:
        try:
            return manager.create_knowledge_base(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.patch("/api/knowledge/bases/{knowledge_base_id}")
    async def update_knowledge_base(
        knowledge_base_id: str, payload: KnowledgeBaseUpdateDraft
    ) -> dict[str, Any]:
        try:
            return manager.update_knowledge_base(knowledge_base_id, payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Knowledge base not found: {knowledge_base_id}"
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.get("/api/knowledge/bases/{knowledge_base_id}")
    async def get_knowledge_base(knowledge_base_id: str) -> dict[str, Any]:
        try:
            return manager.get_knowledge_base(knowledge_base_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Knowledge base not found: {knowledge_base_id}"
            ) from exc

    @app.delete("/api/knowledge/bases/{knowledge_base_id}")
    async def delete_knowledge_base(knowledge_base_id: str) -> dict[str, str]:
        try:
            manager.delete_knowledge_base(knowledge_base_id)
            return {"status": "deleted"}
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Knowledge base not found: {knowledge_base_id}"
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.post("/api/knowledge/bases/{knowledge_base_id}/documents")
    async def create_knowledge_document(
        knowledge_base_id: str, payload: KnowledgeDocumentDraft
    ) -> dict[str, Any]:
        try:
            return manager.create_knowledge_document(knowledge_base_id, payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Knowledge base not found: {knowledge_base_id}"
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.post("/api/knowledge/bases/{knowledge_base_id}/documents/upload")
    async def upload_knowledge_document(
        knowledge_base_id: str,
        file: UploadFile = File(...),
        title: str | None = Form(default=None),
        source: str | None = Form(default=None),
    ) -> dict[str, Any]:
        try:
            data = await file.read()
            if not data:
                raise ValueError("Uploaded file is empty.")
            if len(data) > 5 * 1024 * 1024:
                raise ValueError("Uploaded file is too large (max 5MB).")
            content = _decode_upload_bytes(data).strip()
            if not content:
                raise ValueError("Uploaded file has no readable text content.")
            doc_title = (title or "").strip() or (file.filename or "Uploaded document")
            payload = KnowledgeDocumentDraft(
                title=doc_title,
                content=content,
                source_type="file",
                source=(source or "").strip() or file.filename,
            )
            return manager.create_knowledge_document(knowledge_base_id, payload)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Knowledge base not found: {knowledge_base_id}"
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.get("/api/knowledge/bases/{knowledge_base_id}/documents/{document_id}")
    async def get_knowledge_document(
        knowledge_base_id: str, document_id: str
    ) -> dict[str, Any]:
        try:
            return manager.get_knowledge_document(knowledge_base_id, document_id)
        except KeyError as exc:
            reason = str(exc).strip().strip("'\"")
            if reason == knowledge_base_id:
                raise HTTPException(
                    status_code=404,
                    detail=f"Knowledge base not found: {knowledge_base_id}",
                ) from exc
            raise HTTPException(
                status_code=404, detail=f"Document not found: {document_id}"
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.delete("/api/knowledge/bases/{knowledge_base_id}/documents/{document_id}")
    async def delete_knowledge_document(
        knowledge_base_id: str, document_id: str
    ) -> dict[str, str]:
        try:
            manager.delete_knowledge_document(knowledge_base_id, document_id)
            return {"status": "deleted"}
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Document not found: {document_id}"
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.post("/api/knowledge/hit-testing")
    async def knowledge_hit_testing(
        payload: KnowledgeHitTestingRequest,
    ) -> dict[str, Any]:
        ids: list[str] = []
        if payload.knowledge_base_ids:
            ids.extend(payload.knowledge_base_ids)
        if payload.knowledge_base_id:
            ids.append(payload.knowledge_base_id)
        normalized_ids = [
            str(item or "").strip() for item in ids if str(item or "").strip()
        ]
        if not normalized_ids:
            raise HTTPException(
                status_code=400, detail="knowledge_base_ids is required"
            )

        try:
            items = manager.search_knowledge_chunks(
                knowledge_base_ids=normalized_ids,
                query=payload.query,
                limit=payload.limit,
            )
            return {"items": items, "total": len(items)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.get("/api/chat/sessions")
    async def list_chat_sessions() -> dict[str, Any]:
        sessions = manager.list_chat_sessions()
        return {"sessions": sessions, "summary": _chat_summary(sessions)}

    @app.post("/api/chat/sessions")
    async def create_chat_session(payload: CreateChatSessionRequest) -> dict[str, Any]:
        try:
            effective_project_id = str(payload.project_id or "").strip()
            if not effective_project_id:
                raise HTTPException(
                    status_code=400,
                    detail="Please select a project before creating a session.",
                )

            if project_store.get_project(effective_project_id) is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Project not found: {effective_project_id}",
                )
            if effective_project_id != str(payload.project_id or ""):
                payload = payload.model_copy(update={"project_id": effective_project_id})

            result = manager.create_chat_session(payload)
            project_store.increment_session_count(effective_project_id)
            return result
        except HTTPException:
            raise
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AutoSongshuError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Failed to create chat session")
            raise HTTPException(status_code=500, detail=f"创建会话失败: {exc}") from exc

    @app.get("/api/chat/sessions/{session_id}")
    async def get_chat_session(session_id: str) -> dict[str, Any]:
        try:
            return manager.get_chat_session(session_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Chat session not found: {session_id}"
            ) from exc

    @app.get("/api/chat/sessions/{session_id}/export")
    async def export_chat_session(session_id: str, format: str = "markdown"):
        """Export a chat session in the specified format (markdown)."""
        try:
            session_data = manager.get_chat_session(session_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Chat session not found: {session_id}"
            ) from exc

        if format != "markdown":
            raise HTTPException(
                status_code=400, detail=f"Unsupported export format: {format}"
            )

        title = session_data.get("title") or "Untitled"
        created_at = session_data.get("created_at") or now_iso()
        updated_at = session_data.get("updated_at") or now_iso()
        messages = session_data.get("messages") or []

        lines = [
            f"# {title}",
            "",
            f"- **Created:** {created_at}",
            f"- **Updated:** {updated_at}",
            "",
            "---",
            "",
        ]

        for msg in messages:
            role = msg.get("role", "unknown")
            role_label = {"user": "User", "assistant": "Assistant"}.get(role, role)
            status = msg.get("status", "")
            error = msg.get("error")
            content = msg.get("content") or []

            lines.append(f"### {role_label}")
            if status and status != "completed":
                lines.append(f"*Status: {status}*")
            if error:
                lines.append(f"*Error: {error}*")

            # Extract text from content parts
            text_parts = []
            for part in content:
                part_type = str(part.get("type", ""))
                if part_type == "output_text" or part_type == "text":
                    text = part.get("text", "")
                    if text:
                        text_parts.append(text)
                elif part_type == "tool_use":
                    tool_name = part.get("name", "unknown")
                    tool_input = part.get("input", {})
                    tool_text = f"**Tool Call:** `{tool_name}`\n"
                    if tool_input:
                        import json as _json
                        tool_text += f"```json\n{_json.dumps(tool_input, ensure_ascii=False, indent=2)}\n```\n"
                    text_parts.append(tool_text)
                elif part_type == "tool_result":
                    result_content = part.get("content") or []
                    result_texts = [
                        p.get("text", "") for p in result_content
                        if str(p.get("type", "")) in ("output_text", "text")
                    ]
                    if result_texts:
                        text_parts.append(f"**Tool Result:**\n```\n{''.join(result_texts)}\n```")

            if text_parts:
                lines.append("")
                lines.append("\n\n".join(text_parts))

            lines.append("")
            lines.append("---")
            lines.append("")

        markdown_content = "\n".join(lines)

        safe_title = "".join(
            c if c.isalnum() or c in (" ", "-", "_") else "_"
            for c in title
        ).strip()
        date_str = created_at[:10] if len(created_at) >= 10 else "unknown"
        filename = f"session_{safe_title}_{date_str}.md"

        return Response(
            content=markdown_content,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.post("/api/chat/sessions/{session_id}/messages")
    async def send_message(
        session_id: str, payload: SendMessageRequest
    ) -> dict[str, Any]:
        try:
            return manager.enqueue_message(session_id, payload.content)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Chat session not found: {session_id}"
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.post("/api/chat/sessions/{session_id}/interrupt")
    async def interrupt_session(
        session_id: str,
        request: Request,
        payload: InterruptSessionRequest | None = Body(default=None),
    ) -> dict[str, Any]:
        try:
            expected_assistant_message_id = (
                str(payload.assistant_message_id or "").strip()
                if payload is not None
                else ""
            )
            if request is not None:
                logger.info(
                    "Interrupt requested: session=%s expected_assistant=%s client=%s",
                    session_id,
                    expected_assistant_message_id or "-",
                    getattr(request.client, "host", "unknown"),
                )
            return manager.interrupt_session(
                session_id,
                expected_assistant_message_id=expected_assistant_message_id or None,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Chat session not found: {session_id}"
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    class ForkSessionRequest(BaseModel):
        message_index: int = Field(default=-1, ge=-1)

    @app.post("/api/chat/sessions/{session_id}/fork")
    async def fork_session(
        session_id: str, payload: ForkSessionRequest | None = None
    ) -> dict[str, Any]:
        try:
            message_index = payload.message_index if payload else -1
            return manager.fork_session(session_id, message_index=message_index)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Chat session not found: {session_id}"
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.get("/api/chat/sessions/{session_id}/trajectory")
    async def get_session_trajectory(session_id: str):
        """Return the trajectory steps for a session."""
        try:
            session = manager.chat_sessions.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")

            steps = []
            summary = {}
            try:
                if session.conversation is not None:
                    recorder = getattr(
                        session.conversation, "trajectory_recorder", None
                    )
                    if recorder is not None:
                        steps = [s.to_dict() for s in recorder.steps]
                        summary = recorder.summary()
            except Exception:
                pass

            return JSONResponse({
                "session_id": session_id,
                "steps": steps,
                "total": len(steps),
                "summary": summary,
            })
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.get("/api/chat/sessions/{session_id}/memory-status")
    async def get_session_memory_status(session_id: str):
        """Return the memory/context window status for a session."""
        try:
            session = manager.chat_sessions.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")
            memory_data = {
                "session_id": session_id,
                "token_usage": {},
                "compaction": {},
                "layers": {},
            }
            # Extract memory status if available
            conversation = getattr(session, "conversation", None)
            if conversation is not None:
                mem = getattr(conversation, "memory", None)
                if mem is not None:
                    memory_data["layers"] = {
                        "has_summary": bool(getattr(mem, "summary", None)),
                        "has_continuation": bool(getattr(mem, "continuation", None)),
                        "stable_conclusions_count": len(getattr(mem, "stable_conclusions", []) or []),
                        "validated_findings_count": len(getattr(mem, "validated_findings", []) or []),
                        "active_leads_count": len(getattr(mem, "active_leads", []) or []),
                        "has_handoff": bool(getattr(mem, "handoff", None)),
                        "next_focus": getattr(mem, "next_focus", ""),
                    }
            return memory_data
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.get("/api/chat/sessions/{session_id}/findings")
    async def get_session_findings(session_id: str):
        """Return all findings recorded during the session."""
        try:
            session = manager.chat_sessions.get(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")
            conversation = getattr(session, "conversation", None)
            if conversation is None:
                return JSONResponse({"findings": [], "total": 0})
            runtime = getattr(conversation, "runtime", None)
            if runtime is None:
                return JSONResponse({"findings": [], "total": 0})
            store = getattr(runtime, "findings", None)
            if store is None:
                return JSONResponse({"findings": [], "total": 0})
            findings = [f.model_dump() for f in store.list()]
            return JSONResponse({"findings": findings, "total": len(findings)})
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    @app.get("/api/chat/approvals/pending")
    async def list_pending_approvals() -> dict[str, Any]:
        approval_manager = get_approval_manager()
        pending = approval_manager.get_pending_requests()
        return {"pending": [req.to_dict() for req in pending]}

    @app.post("/api/chat/approvals/{request_id}/respond")
    async def respond_to_approval(
        request_id: str,
        payload: ApprovalResponsePayload,
    ) -> dict[str, Any]:
        approval_manager = get_approval_manager()
        success = approval_manager.respond_to_approval(
            request_id=request_id,
            approved=payload.approved,
            reason=payload.reason,
            remember_for_session=payload.remember_for_session,
            always_allow=payload.always_allow,
        )
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Approval request not found: {request_id}",
            )
        return {"success": True, "request_id": request_id, "approved": payload.approved}

    @app.post("/api/chat/approvals/{request_id}/cancel")
    async def cancel_approval(request_id: str) -> dict[str, Any]:
        approval_manager = get_approval_manager()
        success = approval_manager.cancel_approval(request_id)
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Approval request not found: {request_id}",
            )
        return {"success": True, "request_id": request_id}

    @app.get("/api/chat/approvals/stats")
    async def approval_stats() -> dict[str, Any]:
        approval_manager = get_approval_manager()
        stats = approval_manager.get_stats()
        policy = get_permission_policy()
        stats["permission_rules"] = policy.get_rules_summary()
        return stats

    @app.get("/api/chat/permissions/rules")
    async def get_permission_rules() -> dict[str, Any]:
        policy = get_permission_policy()
        return policy.get_rules_summary()

    @app.delete("/api/chat/permissions/rules")
    async def clear_permission_rules() -> dict[str, Any]:
        policy = get_permission_policy()
        policy.clear_allow_rules()
        return {"success": True, "message": "所有始终允许规则已清除"}

    @app.post("/api/chat/permissions/rules")
    async def add_permission_rule(payload: dict[str, Any]) -> dict[str, Any]:
        rule_str = payload.get("rule", "").strip()
        rule_type = payload.get("type", "allow").strip().lower()
        if not rule_str:
            raise HTTPException(status_code=400, detail="缺少 rule 参数")
        policy = get_permission_policy()
        if rule_type == "deny":
            policy.add_deny_rule(rule_str)
        else:
            policy.add_allow_rule(rule_str)
        return {"success": True, "rule": rule_str, "type": rule_type}

    @app.post("/api/chat/sessions/{session_id}/knowledge-documents")
    async def create_session_knowledge_document(
        session_id: str,
        payload: CreateKnowledgeFromSessionRequest,
    ) -> dict[str, Any]:
        try:
            return manager.create_knowledge_document_from_session(session_id, payload)
        except KeyError as exc:
            reason = str(exc).strip().strip("'\"")
            if reason.startswith("knowledge_base:"):
                kb_id = reason.split(":", 1)[1] or payload.knowledge_base_id or ""
                raise HTTPException(
                    status_code=404, detail=f"Knowledge base not found: {kb_id}"
                ) from exc
            chat_id = (
                reason.split(":", 1)[1]
                if reason.startswith("chat_session:")
                else session_id
            )
            raise HTTPException(
                status_code=404, detail=f"Chat session not found: {chat_id}"
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=_safe_error_detail(exc)) from exc

    # --- Project Management API ---
    @app.get("/api/projects")
    async def list_projects() -> dict[str, Any]:
        """List all projects."""
        try:
            projects = project_store.list_projects()
            return {"projects": [p.model_dump() for p in projects]}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/projects")
    async def create_project(payload: ProjectCreateRequest) -> dict[str, Any]:
        """Create a new project."""
        try:
            project = project_store.create_project(
                name=payload.name,
                workspace_dir=payload.workspace_dir,
            )
            return project.model_dump()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.delete("/api/projects/{project_id}")
    async def delete_project(project_id: str) -> dict[str, Any]:
        """Delete a project."""
        try:
            success = project_store.delete_project(project_id)
            if not success:
                raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
            return {"status": "deleted", "project_id": project_id}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # --- Project workspace file management ---
    @app.get("/api/projects/{project_id}/workspace")
    async def list_workspace_files(project_id: str) -> dict[str, Any]:
        """List all files in the project workspace as a tree structure."""
        try:
            project = project_store.get_project(project_id)
            if project is None:
                raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

            # Resolve workspace_dir relative to project_root, not CWD
            workspace_root = (project_root / project.workspace_dir).resolve()
            workspace_root.mkdir(parents=True, exist_ok=True)

            def build_tree(directory: Path) -> list[dict[str, Any]]:
                items = []
                try:
                    entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                except PermissionError:
                    return items
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    item: dict[str, Any] = {
                        "name": entry.name,
                        "path": str(entry.relative_to(workspace_root)),
                        "is_directory": entry.is_dir(),
                    }
                    if entry.is_file():
                        item["size"] = entry.stat().st_size
                    else:
                        item["children"] = build_tree(entry)
                    items.append(item)
                return items

            files = build_tree(workspace_root)
            return {"files": files, "project_id": project_id, "workspace_dir": str(workspace_root)}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/api/projects/{project_id}/workspace/upload")
    async def upload_workspace_file(
        project_id: str,
        file: UploadFile = File(...),
        path: str = Form(default=""),
    ) -> dict[str, Any]:
        """Upload a file to the project workspace."""
        try:
            project = project_store.get_project(project_id)
            if project is None:
                raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

            # Resolve workspace_dir relative to project_root, not CWD
            workspace_root = (project_root / project.workspace_dir).resolve()
            workspace_root.mkdir(parents=True, exist_ok=True)

            target_path = workspace_root / path if path else workspace_root / file.filename
            target_path = target_path.resolve()

            if not target_path.is_relative_to(workspace_root):
                raise HTTPException(status_code=400, detail="Invalid path: outside workspace")

            target_path.parent.mkdir(parents=True, exist_ok=True)
            content = await file.read()
            target_path.write_bytes(content)

            return {
                "success": True,
                "path": str(target_path.relative_to(workspace_root)),
                "size": len(content),
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.delete("/api/projects/{project_id}/workspace")
    async def delete_workspace_file(project_id: str, path: str) -> dict[str, Any]:
        """Delete a file or directory from the project workspace."""
        try:
            project = project_store.get_project(project_id)
            if project is None:
                raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

            # Resolve workspace_dir relative to project_root, not CWD
            workspace_root = (project_root / project.workspace_dir).resolve()
            target_path = (workspace_root / path).resolve()

            if not target_path.is_relative_to(workspace_root):
                raise HTTPException(status_code=400, detail="Invalid path: outside workspace")

            if not target_path.exists():
                raise HTTPException(status_code=404, detail="File not found")

            if target_path.is_dir():
                import shutil
                shutil.rmtree(target_path)
            else:
                target_path.unlink()

            return {"success": True, "path": path}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    # --- SPA fallback: any unmatched non-API route returns index.html ---
    @app.get("/{full_path:path}", response_class=HTMLResponse)
    async def spa_fallback(request: Request, full_path: str) -> HTMLResponse:
        # Only serve SPA for paths that don't look like API or static assets
        if full_path.startswith(("api/", "static/", "artifacts/", "assets/")):
            raise HTTPException(status_code=404, detail="Not found")
        return _serve_spa(request)

    return app


app = create_app()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autosongshu-web",
        description="FastAPI web console for AutoSongshu.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind host.")
    parser.add_argument("--port", type=int, default=8000, help="Bind port.")
    parser.add_argument("--reload", action="store_true", help="Enable auto reload.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    uvicorn.run(**_uvicorn_run_kwargs(args))
    return 0
