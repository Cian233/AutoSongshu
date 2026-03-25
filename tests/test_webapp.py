from __future__ import annotations

import importlib.util
import os
import unittest
from unittest import mock

_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None
_HAS_UVICORN = importlib.util.find_spec("uvicorn") is not None

if _HAS_FASTAPI and _HAS_UVICORN:
    with mock.patch.dict(os.environ, {"AUTOSONGSHU_CHAT_DATABASE_URL": "sqlite:///:memory:"}, clear=False):
        from autosongshu_agent import webapp
        from fastapi.testclient import TestClient


@unittest.skipUnless(_HAS_FASTAPI and _HAS_UVICORN, "webapp tests require fastapi and uvicorn")
class WebAppRunConfigTests(unittest.TestCase):
    def test_uvicorn_kwargs_limit_reload_scope_to_source_tree(self) -> None:
        args = webapp.build_parser().parse_args(["--reload"])

        kwargs = webapp._uvicorn_run_kwargs(args)

        self.assertTrue(kwargs["reload"])
        self.assertEqual(kwargs["app"], "autosongshu_agent.webapp:app")
        self.assertEqual(kwargs["reload_dirs"], [str((webapp._project_root() / "src").resolve())])
        self.assertIn(str((webapp._project_root() / "artifacts").resolve()), kwargs["reload_excludes"])
        self.assertIn(str((webapp._project_root() / "data").resolve()), kwargs["reload_excludes"])
        self.assertIn(str((webapp._project_root() / "configs" / "data").resolve()), kwargs["reload_excludes"])
        self.assertIn("**/__pycache__/**", kwargs["reload_excludes"])
        self.assertIn("*.pyc", kwargs["reload_excludes"])
        self.assertIn("*.egg-info/**", kwargs["reload_excludes"])
        self.assertIn("*.db", kwargs["reload_excludes"])
        self.assertIn("*.jsonl", kwargs["reload_excludes"])

    def test_main_passes_reload_guards_to_uvicorn(self) -> None:
        with mock.patch.object(webapp.uvicorn, "run") as mocked_run:
            exit_code = webapp.main(["--host", "0.0.0.0", "--port", "9000", "--reload"])

        self.assertEqual(exit_code, 0)
        mocked_run.assert_called_once()
        kwargs = mocked_run.call_args.kwargs
        self.assertTrue(kwargs["reload"])
        self.assertEqual(kwargs["host"], "0.0.0.0")
        self.assertEqual(kwargs["port"], 9000)
        self.assertEqual(kwargs["reload_dirs"], [str((webapp._project_root() / "src").resolve())])
        self.assertIn(str((webapp._project_root() / "artifacts").resolve()), kwargs["reload_excludes"])
        self.assertIn("*.pyc", kwargs["reload_excludes"])


@unittest.skipUnless(_HAS_FASTAPI and _HAS_UVICORN, "webapp tests require fastapi and uvicorn")
class WebAppKnowledgeEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(webapp.app)
        self.manager = webapp.app.state.chat_manager

    def tearDown(self) -> None:
        self.client.close()

    def test_create_session_knowledge_document_success(self) -> None:
        with mock.patch.object(
            self.manager,
            "create_knowledge_document_from_session",
            return_value={"status": "created", "knowledge_base_id": "kb-1", "document": {"id": "doc-1"}},
        ) as mocked_create:
            response = self.client.post(
                "/api/chat/sessions/chat-0001/knowledge-documents",
                json={"knowledge_base_id": "kb-1", "title": "summary"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "created")
        mocked_create.assert_called_once()

    def test_create_session_knowledge_document_maps_missing_chat_session(self) -> None:
        with mock.patch.object(
            self.manager,
            "create_knowledge_document_from_session",
            side_effect=KeyError("chat_session:chat-404"),
        ):
            response = self.client.post(
                "/api/chat/sessions/chat-404/knowledge-documents",
                json={"knowledge_base_id": "kb-1"},
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn("Chat session not found", response.text)

    def test_create_session_knowledge_document_maps_missing_knowledge_base(self) -> None:
        with mock.patch.object(
            self.manager,
            "create_knowledge_document_from_session",
            side_effect=KeyError("knowledge_base:kb-missing"),
        ):
            response = self.client.post(
                "/api/chat/sessions/chat-0001/knowledge-documents",
                json={"knowledge_base_id": "kb-missing"},
            )

        self.assertEqual(response.status_code, 404)
        self.assertIn("Knowledge base not found", response.text)


if __name__ == "__main__":
    unittest.main()
