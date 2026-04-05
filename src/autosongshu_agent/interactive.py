from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class ApprovalRequest:
    request_id: str
    tool_name: str
    arguments: dict[str, Any]
    risk_level: str
    session_id: str
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    timeout_seconds: int = 300
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "risk_level": self.risk_level,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "timeout_seconds": self.timeout_seconds,
            "status": self.status,
        }


@dataclass
class ApprovalResponse:
    request_id: str
    approved: bool
    reason: str = ""
    responded_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    remember_for_session: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "approved": self.approved,
            "reason": self.reason,
            "responded_at": self.responded_at,
            "remember_for_session": self.remember_for_session,
        }


class ApprovalTimeoutError(Exception):
    pass


class ApprovalCancelledError(Exception):
    pass


@dataclass
class PendingApproval:
    request: ApprovalRequest
    event: threading.Event = field(default_factory=threading.Event)
    response: ApprovalResponse | None = None


class InteractiveApprovalManager:
    def __init__(
        self,
        emit_callback: Callable[[str, dict[str, Any]], None] | None = None,
        default_timeout: int = 300,
    ) -> None:
        self.emit_callback = emit_callback
        self.default_timeout = default_timeout
        self._pending: dict[str, PendingApproval] = {}
        self._lock = threading.RLock()
        self._session_decisions: dict[str, dict[str, bool]] = {}
        self._history: list[dict[str, Any]] = []

    def request_approval(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        risk_level: str,
        session_id: str,
        timeout: int | None = None,
    ) -> ApprovalResponse:
        request_id = str(uuid.uuid4())
        request = ApprovalRequest(
            request_id=request_id,
            tool_name=tool_name,
            arguments=arguments,
            risk_level=risk_level,
            session_id=session_id,
            timeout_seconds=timeout or self.default_timeout,
        )

        with self._lock:
            if session_id in self._session_decisions:
                session_decisions = self._session_decisions[session_id]
                if tool_name in session_decisions:
                    return ApprovalResponse(
                        request_id=request_id,
                        approved=session_decisions[tool_name],
                        reason="remembered_from_previous",
                        remember_for_session=True,
                    )

            pending = PendingApproval(request=request)
            self._pending[request_id] = pending

        if self.emit_callback:
            self.emit_callback("approval.request", request.to_dict())

        timeout_seconds = timeout or self.default_timeout
        completed = pending.event.wait(timeout=timeout_seconds)

        with self._lock:
            self._pending.pop(request_id, None)

        if not completed:
            self._record_history(request, None, "timeout")
            raise ApprovalTimeoutError(f"Approval request {request_id} timed out")

        if pending.response is None:
            self._record_history(request, None, "cancelled")
            raise ApprovalCancelledError(f"Approval request {request_id} was cancelled")

        self._record_history(request, pending.response, "responded")

        if pending.response.remember_for_session:
            if session_id not in self._session_decisions:
                self._session_decisions[session_id] = {}
            self._session_decisions[session_id][tool_name] = pending.response.approved

        return pending.response

    def respond_to_approval(
        self,
        request_id: str,
        approved: bool,
        reason: str = "",
        remember_for_session: bool = False,
    ) -> bool:
        with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                return False

            pending.response = ApprovalResponse(
                request_id=request_id,
                approved=approved,
                reason=reason,
                remember_for_session=remember_for_session,
            )
            pending.request.status = "approved" if approved else "denied"
            pending.event.set()

        if self.emit_callback:
            self.emit_callback("approval.response", pending.response.to_dict())

        return True

    def cancel_approval(self, request_id: str) -> bool:
        with self._lock:
            pending = self._pending.get(request_id)
            if pending is None:
                return False
            pending.request.status = "cancelled"
            pending.event.set()

        return True

    def cancel_all_pending(self, session_id: str | None = None) -> int:
        cancelled = 0
        with self._lock:
            for request_id, pending in list(self._pending.items()):
                if session_id is None or pending.request.session_id == session_id:
                    pending.request.status = "cancelled"
                    pending.event.set()
                    cancelled += 1
        return cancelled

    def get_pending_requests(
        self, session_id: str | None = None
    ) -> list[ApprovalRequest]:
        with self._lock:
            requests = []
            for pending in self._pending.values():
                if session_id is None or pending.request.session_id == session_id:
                    requests.append(pending.request)
            return requests

    def clear_session_decisions(self, session_id: str) -> None:
        with self._lock:
            self._session_decisions.pop(session_id, None)

    def remember_decision(
        self, session_id: str, tool_name: str, approved: bool
    ) -> None:
        with self._lock:
            if session_id not in self._session_decisions:
                self._session_decisions[session_id] = {}
            self._session_decisions[session_id][tool_name] = approved

    def _record_history(
        self,
        request: ApprovalRequest,
        response: ApprovalResponse | None,
        outcome: str,
    ) -> None:
        self._history.append(
            {
                "request_id": request.request_id,
                "tool_name": request.tool_name,
                "session_id": request.session_id,
                "risk_level": request.risk_level,
                "outcome": outcome,
                "approved": response.approved if response else None,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
        )
        if len(self._history) > 500:
            self._history = self._history[-500:]

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._history[-limit:])

    def get_stats(self) -> dict[str, Any]:
        total = len(self._history)
        approved = sum(1 for h in self._history if h.get("approved") is True)
        denied = sum(1 for h in self._history if h.get("approved") is False)
        timed_out = sum(1 for h in self._history if h.get("outcome") == "timeout")
        return {
            "total_requests": total,
            "approved": approved,
            "denied": denied,
            "timed_out": timed_out,
            "pending": len(self._pending),
        }


class InteractiveHarness:
    def __init__(
        self,
        approval_manager: InteractiveApprovalManager,
        auto_approve_low_risk: bool = True,
    ) -> None:
        self.approval_manager = approval_manager
        self.auto_approve_low_risk = auto_approve_low_risk

    def check_and_request_approval(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        risk_level: str,
        session_id: str,
        requires_approval: bool,
    ) -> dict[str, Any]:
        if not requires_approval:
            return {"allowed": True, "reason": "no_approval_required"}

        if self.auto_approve_low_risk and risk_level.lower() in ("low", "medium"):
            return {"allowed": True, "reason": "auto_approved_low_risk"}

        try:
            response = self.approval_manager.request_approval(
                tool_name=tool_name,
                arguments=arguments,
                risk_level=risk_level,
                session_id=session_id,
            )
            if response.approved:
                return {
                    "allowed": True,
                    "reason": "user_approved",
                    "request_id": response.request_id,
                }
            return {
                "allowed": False,
                "reason": "user_denied",
                "error": f"Tool '{tool_name}' was denied by user: {response.reason}",
                "request_id": response.request_id,
            }
        except ApprovalTimeoutError:
            return {
                "allowed": False,
                "reason": "timeout",
                "error": f"Approval request for '{tool_name}' timed out.",
            }
        except ApprovalCancelledError:
            return {
                "allowed": False,
                "reason": "cancelled",
                "error": f"Approval request for '{tool_name}' was cancelled.",
            }

    def create_approval_callback(
        self,
        session_id: str,
    ) -> Callable[[str, dict[str, Any], str | None], bool]:
        def callback(
            tool_name: str, arguments: dict[str, Any], risk_level: str | None = None
        ) -> bool:
            result = self.check_and_request_approval(
                tool_name=tool_name,
                arguments=arguments,
                risk_level=risk_level or "medium",
                session_id=session_id,
                requires_approval=True,
            )
            return result.get("allowed", False)

        return callback


def create_interactive_approval_manager(
    emit_callback: Callable[[str, dict[str, Any]], None] | None = None,
    default_timeout: int = 300,
) -> InteractiveApprovalManager:
    return InteractiveApprovalManager(
        emit_callback=emit_callback,
        default_timeout=default_timeout,
    )


__all__ = [
    "ApprovalRequest",
    "ApprovalResponse",
    "ApprovalTimeoutError",
    "ApprovalCancelledError",
    "PendingApproval",
    "InteractiveApprovalManager",
    "InteractiveHarness",
    "create_interactive_approval_manager",
]
