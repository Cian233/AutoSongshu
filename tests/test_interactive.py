from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from autosongshu_agent.interactive import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalTimeoutError,
    ApprovalCancelledError,
    PendingApproval,
    InteractiveApprovalManager,
    InteractiveHarness,
    create_interactive_approval_manager,
)


class ApprovalRequestTests(unittest.TestCase):
    def test_request_creation(self) -> None:
        request = ApprovalRequest(
            request_id="test-123",
            tool_name="sandbox_run_python",
            arguments={"code": "print('hello')"},
            risk_level="high",
            session_id="session-1",
        )
        self.assertEqual(request.request_id, "test-123")
        self.assertEqual(request.status, "pending")
        self.assertEqual(request.timeout_seconds, 300)

    def test_to_dict(self) -> None:
        request = ApprovalRequest(
            request_id="test-123",
            tool_name="test_tool",
            arguments={},
            risk_level="medium",
            session_id="session-1",
        )
        d = request.to_dict()
        self.assertEqual(d["request_id"], "test-123")
        self.assertEqual(d["status"], "pending")


class ApprovalResponseTests(unittest.TestCase):
    def test_response_creation(self) -> None:
        response = ApprovalResponse(
            request_id="test-123",
            approved=True,
            reason="User approved",
        )
        self.assertTrue(response.approved)
        self.assertEqual(response.reason, "User approved")

    def test_to_dict(self) -> None:
        response = ApprovalResponse(
            request_id="test-123",
            approved=False,
            reason="Too risky",
            remember_for_session=True,
        )
        d = response.to_dict()
        self.assertFalse(d["approved"])
        self.assertTrue(d["remember_for_session"])


class InteractiveApprovalManagerTests(unittest.TestCase):
    def test_request_approval_approved(self) -> None:
        emit_callback = MagicMock()
        manager = InteractiveApprovalManager(emit_callback=emit_callback)

        def respond_later() -> None:
            time.sleep(0.1)
            pending = manager.get_pending_requests()
            if pending:
                manager.respond_to_approval(pending[0].request_id, approved=True)

        thread = threading.Thread(target=respond_later)
        thread.start()

        response = manager.request_approval(
            tool_name="test_tool",
            arguments={"arg": "value"},
            risk_level="high",
            session_id="session-1",
        )

        thread.join()
        self.assertTrue(response.approved)
        emit_callback.assert_called()

    def test_request_approval_denied(self) -> None:
        emit_callback = MagicMock()
        manager = InteractiveApprovalManager(emit_callback=emit_callback)

        def respond_later() -> None:
            time.sleep(0.1)
            pending = manager.get_pending_requests()
            if pending:
                manager.respond_to_approval(
                    pending[0].request_id,
                    approved=False,
                    reason="Denied by user",
                )

        thread = threading.Thread(target=respond_later)
        thread.start()

        response = manager.request_approval(
            tool_name="test_tool",
            arguments={},
            risk_level="high",
            session_id="session-1",
        )

        thread.join()
        self.assertFalse(response.approved)
        self.assertEqual(response.reason, "Denied by user")

    def test_request_approval_timeout(self) -> None:
        manager = InteractiveApprovalManager(default_timeout=0.1)

        with self.assertRaises(ApprovalTimeoutError):
            manager.request_approval(
                tool_name="test_tool",
                arguments={},
                risk_level="high",
                session_id="session-1",
            )

    def test_cancel_approval(self) -> None:
        manager = InteractiveApprovalManager(default_timeout=5)

        cancelled = False

        def cancel_later() -> None:
            nonlocal cancelled
            time.sleep(0.1)
            pending = manager.get_pending_requests()
            if pending:
                manager.cancel_approval(pending[0].request_id)
                cancelled = True

        thread = threading.Thread(target=cancel_later)
        thread.start()

        with self.assertRaises(ApprovalCancelledError):
            manager.request_approval(
                tool_name="test_tool",
                arguments={},
                risk_level="high",
                session_id="session-1",
            )

        thread.join()
        self.assertTrue(cancelled)

    def test_remember_for_session(self) -> None:
        manager = InteractiveApprovalManager()

        def respond_later() -> None:
            time.sleep(0.1)
            pending = manager.get_pending_requests()
            if pending:
                manager.respond_to_approval(
                    pending[0].request_id,
                    approved=True,
                    remember_for_session=True,
                )

        thread = threading.Thread(target=respond_later)
        thread.start()

        response1 = manager.request_approval(
            tool_name="test_tool",
            arguments={},
            risk_level="high",
            session_id="session-1",
        )
        thread.join()

        self.assertTrue(response1.approved)
        self.assertTrue(response1.remember_for_session)

        response2 = manager.request_approval(
            tool_name="test_tool",
            arguments={},
            risk_level="high",
            session_id="session-1",
        )
        self.assertTrue(response2.approved)
        self.assertEqual(response2.reason, "remembered_from_previous")

    def test_get_pending_requests(self) -> None:
        manager = InteractiveApprovalManager(default_timeout=10)

        def slow_request() -> None:
            try:
                manager.request_approval(
                    tool_name="test_tool",
                    arguments={},
                    risk_level="high",
                    session_id="session-1",
                )
            except Exception:
                pass

        thread = threading.Thread(target=slow_request)
        thread.start()
        time.sleep(0.1)

        pending = manager.get_pending_requests()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].tool_name, "test_tool")

        manager.cancel_all_pending()
        thread.join()

    def test_get_stats(self) -> None:
        manager = InteractiveApprovalManager()

        def respond_later(approved: bool) -> None:
            time.sleep(0.05)
            pending = manager.get_pending_requests()
            if pending:
                manager.respond_to_approval(pending[0].request_id, approved=approved)

        for approved in [True, True, False]:
            thread = threading.Thread(target=respond_later, args=(approved,))
            thread.start()
            try:
                manager.request_approval(
                    tool_name="test_tool",
                    arguments={},
                    risk_level="high",
                    session_id="session-1",
                )
            except Exception:
                pass
            thread.join()

        stats = manager.get_stats()
        self.assertEqual(stats["total_requests"], 3)
        self.assertEqual(stats["approved"], 2)
        self.assertEqual(stats["denied"], 1)

    def test_cancel_all_pending(self) -> None:
        manager = InteractiveApprovalManager(default_timeout=10)

        def slow_request(session_id: str) -> None:
            try:
                manager.request_approval(
                    tool_name="test_tool",
                    arguments={},
                    risk_level="high",
                    session_id=session_id,
                )
            except Exception:
                pass

        threads = [
            threading.Thread(target=slow_request, args=(f"session-{i}",))
            for i in range(3)
        ]
        for t in threads:
            t.start()
        time.sleep(0.1)

        pending = manager.get_pending_requests()
        self.assertEqual(len(pending), 3)

        cancelled = manager.cancel_all_pending()
        self.assertEqual(cancelled, 3)

        for t in threads:
            t.join()


class InteractiveHarnessTests(unittest.TestCase):
    def test_auto_approve_low_risk(self) -> None:
        manager = InteractiveApprovalManager()
        harness = InteractiveHarness(manager, auto_approve_low_risk=True)

        result = harness.check_and_request_approval(
            tool_name="http_get",
            arguments={"url": "http://example.com"},
            risk_level="low",
            session_id="session-1",
            requires_approval=True,
        )
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "auto_approved_low_risk")

    def test_requires_approval_flow(self) -> None:
        manager = InteractiveApprovalManager()

        def respond_later() -> None:
            time.sleep(0.1)
            pending = manager.get_pending_requests()
            if pending:
                manager.respond_to_approval(pending[0].request_id, approved=True)

        thread = threading.Thread(target=respond_later)
        thread.start()

        harness = InteractiveHarness(manager, auto_approve_low_risk=False)
        result = harness.check_and_request_approval(
            tool_name="sandbox_run_python",
            arguments={"code": "print('hello')"},
            risk_level="high",
            session_id="session-1",
            requires_approval=True,
        )

        thread.join()
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "user_approved")

    def test_no_approval_required(self) -> None:
        manager = InteractiveApprovalManager()
        harness = InteractiveHarness(manager)

        result = harness.check_and_request_approval(
            tool_name="http_get",
            arguments={},
            risk_level="low",
            session_id="session-1",
            requires_approval=False,
        )
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "no_approval_required")

    def test_create_approval_callback(self) -> None:
        manager = InteractiveApprovalManager()

        def respond_later() -> None:
            time.sleep(0.1)
            pending = manager.get_pending_requests()
            if pending:
                manager.respond_to_approval(pending[0].request_id, approved=True)

        thread = threading.Thread(target=respond_later)
        thread.start()

        harness = InteractiveHarness(manager, auto_approve_low_risk=False)
        callback = harness.create_approval_callback("session-1")

        result = callback("test_tool", {"arg": "value"}, "high")
        thread.join()
        self.assertTrue(result)


class CreateInteractiveApprovalManagerTests(unittest.TestCase):
    def test_create_manager(self) -> None:
        manager = create_interactive_approval_manager(default_timeout=60)
        self.assertIsNotNone(manager)
        self.assertEqual(manager.default_timeout, 60)


if __name__ == "__main__":
    unittest.main()
