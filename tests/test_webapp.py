from __future__ import annotations

import importlib.util
import os
import unittest
from unittest import mock
from types import SimpleNamespace

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


@unittest.skipUnless(_HAS_FASTAPI and _HAS_UVICORN, "webapp tests require fastapi and uvicorn")
class WebAppModelEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(webapp.app)
        self.manager = webapp.app.state.chat_manager

    def tearDown(self) -> None:
        self.client.close()

    def test_list_models_accepts_config_path_query(self) -> None:
        expected_profiles = [{"name": "secondary", "is_active": True}]

        with mock.patch.object(
            self.manager,
            "_resolve_config_path",
            return_value="/tmp/custom-config.yaml",
        ) as mocked_resolve, mock.patch.object(
            self.manager,
            "get_model_profiles",
            return_value=expected_profiles,
        ) as mocked_profiles:
            response = self.client.get("/api/models?config_path=configs/custom.yaml")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["profiles"], expected_profiles)
        self.assertEqual(body["config_path"], "/tmp/custom-config.yaml")
        mocked_resolve.assert_called_once_with("configs/custom.yaml")
        mocked_profiles.assert_called_once_with(config_path="/tmp/custom-config.yaml")

    def test_set_active_model_uses_explicit_config_path(self) -> None:
        config = SimpleNamespace(
            model=SimpleNamespace(
                profiles=[
                    {"name": "primary", "model_name": "gpt-4o"},
                    {"name": "secondary", "model_name": "gpt-4.1"},
                ],
                active="primary",
            )
        )

        with mock.patch.object(
            self.manager,
            "_resolve_config_path",
            return_value="/tmp/custom-config.yaml",
        ) as mocked_resolve, mock.patch.object(
            webapp, "_reload_config", return_value=config
        ) as mocked_reload, mock.patch.object(
            webapp, "_save_config"
        ) as mocked_save, mock.patch.object(
            self.manager, "_refresh_model_routers"
        ) as mocked_refresh:
            response = self.client.put(
                "/api/models/active",
                json={
                    "profile_name": "secondary",
                    "config_path": "configs/custom.yaml",
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["active_profile"], "secondary")
        self.assertEqual(body["config_path"], "/tmp/custom-config.yaml")
        mocked_resolve.assert_called_once_with("configs/custom.yaml")
        mocked_reload.assert_called_once_with("/tmp/custom-config.yaml")
        mocked_save.assert_called_once_with("/tmp/custom-config.yaml", config)
        mocked_refresh.assert_called_once_with(
            config, config_path="/tmp/custom-config.yaml"
        )

    def test_delete_model_profile_accepts_config_path_query(self) -> None:
        config = SimpleNamespace(
            model=SimpleNamespace(
                profiles=[{"name": "primary", "model_name": "gpt-4o"}],
                active="primary",
            )
        )

        with mock.patch.object(
            self.manager,
            "_resolve_config_path",
            return_value="/tmp/custom-config.yaml",
        ) as mocked_resolve, mock.patch.object(
            webapp, "_reload_config", return_value=config
        ) as mocked_reload, mock.patch.object(
            webapp, "_save_config"
        ) as mocked_save, mock.patch.object(
            self.manager, "_refresh_model_routers"
        ) as mocked_refresh:
            response = self.client.delete(
                "/api/models/primary?config_path=configs/custom.yaml"
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["deleted"], "primary")
        self.assertEqual(body["config_path"], "/tmp/custom-config.yaml")
        mocked_resolve.assert_called_once_with("configs/custom.yaml")
        mocked_reload.assert_called_once_with("/tmp/custom-config.yaml")
        mocked_save.assert_called_once_with("/tmp/custom-config.yaml", config)
        mocked_refresh.assert_called_once_with(
            config, config_path="/tmp/custom-config.yaml"
        )


if __name__ == "__main__":
    unittest.main()
