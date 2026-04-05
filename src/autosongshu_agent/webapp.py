from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .authorization_store import AuthorizationDraft
from .chat_manager import (
    ChatSessionManager,
    CreateKnowledgeFromSessionRequest,
    CreateChatSessionRequest,
    SendMessageRequest,
)
from .utils import now_iso
from .knowledge_store import (
    KnowledgeBaseDraft,
    KnowledgeBaseUpdateDraft,
    KnowledgeDocumentDraft,
)
from .interactive import InteractiveApprovalManager
from .permissions import (
    InteractivePermissionInterceptor,
    build_default_permission_context,
)
from .commands import CommandRegistry, default_command_registry


class KnowledgeHitTestingRequest(BaseModel):
    query: str = Field(min_length=1)
    knowledge_base_id: str | None = None
    knowledge_base_ids: list[str] = Field(default_factory=list)
    limit: int = Field(default=6, ge=1, le=20)


class ApprovalResponsePayload(BaseModel):
    approved: bool
    reason: str = ""
    remember_for_session: bool = False


_approval_manager: InteractiveApprovalManager | None = None


def get_approval_manager() -> InteractiveApprovalManager:
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = InteractiveApprovalManager()
    return _approval_manager


def set_approval_emit_callback(
    callback: Callable[[str, dict[str, Any]], None] | None,
) -> None:
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = InteractiveApprovalManager(emit_callback=callback)
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
            approval_callback=approval_callback,
        )

    return factory


def create_app() -> FastAPI:
    project_root = _project_root()
    web_root = Path(__file__).resolve().parent / "web"
    asset_version = _asset_version(web_root)
    templates = Jinja2Templates(directory=str(web_root / "templates"))
    templates.env.auto_reload = True
    manager = ChatSessionManager(project_root=project_root)
    hub = SSEHub()
    approval_manager = get_approval_manager()
    default_goal = "继续评估登录、账号与会话流程中的常见 Web 安全问题。"

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
            create_permission_interceptor_factory(approval_manager)
        )
        try:
            yield
        finally:
            manager.remove_listener(listener_id)
            set_approval_emit_callback(None)
            manager.set_permission_interceptor_factory(None)
            manager.shutdown()

    app = FastAPI(title="AutoSongshu Chat", version="0.3.0", lifespan=lifespan)
    app.state.chat_manager = manager
    app.mount("/static", StaticFiles(directory=str(web_root / "static")), name="static")
    app.mount(
        "/artifacts",
        StaticFiles(directory=str(manager.default_artifacts_root)),
        name="artifacts",
    )

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

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
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

    @app.get("/knowledge", response_class=HTMLResponse)
    async def knowledge_page(request: Request) -> HTMLResponse:
        response = templates.TemplateResponse(
            request,
            "knowledge.html",
            {
                "request": request,
                "asset_version": asset_version,
            },
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    def _knowledge_detail_response(
        request: Request,
        knowledge_base_id: str,
        *,
        active_tab: str,
    ) -> HTMLResponse:
        try:
            knowledge_base = manager.get_knowledge_base(knowledge_base_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Knowledge base not found: {knowledge_base_id}"
            ) from exc

        response = templates.TemplateResponse(
            request,
            "knowledge-detail.html",
            {
                "request": request,
                "asset_version": asset_version,
                "knowledge_base_id": knowledge_base_id,
                "knowledge_base": knowledge_base,
                "active_tab": active_tab,
            },
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/knowledge/bases/{knowledge_base_id}", include_in_schema=False)
    async def knowledge_base_redirect(knowledge_base_id: str) -> RedirectResponse:
        return RedirectResponse(
            url=f"/knowledge/bases/{knowledge_base_id}/documents",
            status_code=307,
        )

    @app.get(
        "/knowledge/bases/{knowledge_base_id}/documents", response_class=HTMLResponse
    )
    async def knowledge_documents_page(
        request: Request, knowledge_base_id: str
    ) -> HTMLResponse:
        return _knowledge_detail_response(
            request, knowledge_base_id, active_tab="documents"
        )

    @app.get(
        "/knowledge/bases/{knowledge_base_id}/hit-testing", response_class=HTMLResponse
    )
    async def knowledge_hit_testing_page(
        request: Request, knowledge_base_id: str
    ) -> HTMLResponse:
        return _knowledge_detail_response(
            request, knowledge_base_id, active_tab="hit-testing"
        )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "timestamp": now_iso()}

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/chat/sessions")
    async def list_chat_sessions() -> dict[str, Any]:
        sessions = manager.list_chat_sessions()
        return {"sessions": sessions, "summary": _chat_summary(sessions)}

    @app.post("/api/chat/sessions")
    async def create_chat_session(payload: CreateChatSessionRequest) -> dict[str, Any]:
        try:
            return manager.create_chat_session(payload)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/chat/sessions/{session_id}")
    async def get_chat_session(session_id: str) -> dict[str, Any]:
        try:
            return manager.get_chat_session(session_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Chat session not found: {session_id}"
            ) from exc

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/chat/sessions/{session_id}/interrupt")
    async def interrupt_session(session_id: str) -> dict[str, Any]:
        try:
            return manager.interrupt_session(session_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail=f"Chat session not found: {session_id}"
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        return approval_manager.get_stats()

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
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
