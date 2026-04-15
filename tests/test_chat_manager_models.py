from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from autosongshu_agent.chat_manager import ChatSessionManager, ChatSessionState
from autosongshu_agent.config import ModelConfig


class _DummyRouter:
    def __init__(self, profile_names: list[str], *, active: str | None = None) -> None:
        self._profile_names = list(profile_names)
        self._active = active or (profile_names[0] if profile_names else "")

    def list_profiles(self) -> list[dict[str, object]]:
        return [
            {"name": name, "is_active": name == self._active}
            for name in self._profile_names
        ]

    def set_active(self, profile_name: str) -> bool:
        if profile_name not in self._profile_names:
            return False
        self._active = profile_name
        return True


class _DummyConversation:
    def __init__(self, router: _DummyRouter) -> None:
        self.model_router = router
        self.config = SimpleNamespace(
            model=SimpleNamespace(active=None, profiles=[]),
        )
        self.agent = SimpleNamespace(model="old-model")
        self.memory_model = "old-memory-model"
        self.build_model_calls = 0
        self.build_memory_calls = 0

    def _build_model(self) -> str:
        self.build_model_calls += 1
        return f"model-{self.build_model_calls}"

    def _build_memory_model(self) -> str:
        self.build_memory_calls += 1
        return f"memory-{self.build_memory_calls}"


class ChatManagerModelSwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = ChatSessionManager(project_root=Path(self.temp_dir.name))
        self.addCleanup(self.manager.shutdown)
        self.config_a = str((Path(self.temp_dir.name) / "configs" / "a.yaml").resolve())
        self.config_b = str((Path(self.temp_dir.name) / "configs" / "b.yaml").resolve())

    def _new_session(
        self, *, session_id: str, config_path: str, conversation: _DummyConversation
    ) -> ChatSessionState:
        return ChatSessionState(
            session_id=session_id,
            project_id="project-test",
            title=session_id,
            config_path=config_path,
            conversation=conversation,
        )

    def test_get_model_profiles_prefers_active_conversation_router(self) -> None:
        conversation = _DummyConversation(_DummyRouter(["alpha", "beta"], active="beta"))
        session = self._new_session(
            session_id="chat-0001",
            config_path=self.config_a,
            conversation=conversation,
        )
        self.manager.chat_sessions[session.session_id] = session

        profiles = self.manager.get_model_profiles()

        self.assertEqual({item["name"] for item in profiles}, {"alpha", "beta"})
        active = [item for item in profiles if item.get("is_active")]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["name"], "beta")

    def test_get_model_profiles_filters_by_config_path(self) -> None:
        convo_a = _DummyConversation(_DummyRouter(["alpha"], active="alpha"))
        convo_b = _DummyConversation(_DummyRouter(["beta"], active="beta"))
        session_a = self._new_session(
            session_id="chat-0101",
            config_path=self.config_a,
            conversation=convo_a,
        )
        session_b = self._new_session(
            session_id="chat-0102",
            config_path=self.config_b,
            conversation=convo_b,
        )
        self.manager.chat_sessions[session_a.session_id] = session_a
        self.manager.chat_sessions[session_b.session_id] = session_b

        profiles = self.manager.get_model_profiles(config_path=self.config_b)

        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["name"], "beta")
        self.assertTrue(profiles[0]["is_active"])

    def test_set_active_model_rebuilds_runtime_models_for_matching_session(self) -> None:
        conversation = _DummyConversation(_DummyRouter(["alpha", "beta"], active="alpha"))
        session = self._new_session(
            session_id="chat-0002",
            config_path=self.config_a,
            conversation=conversation,
        )
        self.manager.chat_sessions[session.session_id] = session

        switched = self.manager.set_active_model(
            "beta", config_path=self.config_a
        )

        self.assertTrue(switched)
        self.assertEqual(conversation.config.model.active, "beta")
        self.assertEqual(conversation.build_model_calls, 1)
        self.assertEqual(conversation.build_memory_calls, 1)
        self.assertEqual(conversation.agent.model, "model-1")
        self.assertEqual(conversation.memory_model, "memory-1")

    def test_set_active_model_applies_profile_compaction_overrides(self) -> None:
        conversation = _DummyConversation(_DummyRouter(["alpha", "beta"], active="alpha"))
        conversation.config.model.active = "alpha"
        conversation.config.model.profiles = [
            SimpleNamespace(
                name="alpha",
                model_name="alpha",
                compaction={"compact_after_tokens": 100000},
            ),
            SimpleNamespace(
                name="beta",
                model_name="beta",
                compaction={
                    "context_window_tokens": 256000,
                    "reserved_tokens": 24000,
                    "compact_after_tokens": 232000,
                },
            ),
        ]
        conversation.config.compaction = SimpleNamespace(
            context_window_tokens=128000,
            reserved_tokens=8000,
            compact_after_tokens=90000,
        )
        session = self._new_session(
            session_id="chat-0002b",
            config_path=self.config_a,
            conversation=conversation,
        )
        self.manager.chat_sessions[session.session_id] = session

        switched = self.manager.set_active_model("beta", config_path=self.config_a)

        self.assertTrue(switched)
        self.assertEqual(conversation.config.model.active, "beta")
        self.assertEqual(conversation.config.compaction.context_window_tokens, 256000)
        self.assertEqual(conversation.config.compaction.reserved_tokens, 24000)
        self.assertEqual(conversation.config.compaction.compact_after_tokens, 232000)

    def test_refresh_model_routers_updates_only_target_config_sessions(self) -> None:
        convo_a = _DummyConversation(_DummyRouter(["alpha"], active="alpha"))
        convo_b = _DummyConversation(_DummyRouter(["beta"], active="beta"))
        convo_a.config.compaction = SimpleNamespace(
            context_window_tokens=128000,
            reserved_tokens=8000,
            compact_after_tokens=90000,
        )
        session_a = self._new_session(
            session_id="chat-0003",
            config_path=self.config_a,
            conversation=convo_a,
        )
        session_b = self._new_session(
            session_id="chat-0004",
            config_path=self.config_b,
            conversation=convo_b,
        )
        self.manager.chat_sessions[session_a.session_id] = session_a
        self.manager.chat_sessions[session_b.session_id] = session_b

        config = SimpleNamespace(
            model=ModelConfig(
                model_name="legacy-model",
                api_key="test-key",
                active="beta",
                profiles=[
                    {
                        "name": "alpha",
                        "provider": "custom",
                        "model_name": "gpt-4.1-mini",
                        "tasks": ["general"],
                    },
                    {
                        "name": "beta",
                        "provider": "custom",
                        "model_name": "gpt-4.1",
                        "tasks": ["general"],
                        "compaction": {
                            "context_window_tokens": 256000,
                            "reserved_tokens": 24000,
                            "compact_after_tokens": 232000,
                        },
                    },
                ],
            )
        )

        self.manager._refresh_model_routers(config, config_path=self.config_a)

        self.assertTrue(hasattr(convo_a, "_model_router"))
        self.assertEqual(convo_a.config.model.active, "beta")
        self.assertEqual(convo_a.build_model_calls, 1)
        self.assertEqual(convo_a.build_memory_calls, 1)
        self.assertEqual(convo_a.config.compaction.context_window_tokens, 256000)
        self.assertEqual(convo_a.config.compaction.reserved_tokens, 24000)
        self.assertEqual(convo_a.config.compaction.compact_after_tokens, 232000)

        self.assertFalse(hasattr(convo_b, "_model_router"))
        self.assertEqual(convo_b.build_model_calls, 0)
        self.assertEqual(convo_b.build_memory_calls, 0)

    def test_apply_active_profile_compaction_overrides_supports_pydantic_profiles(self) -> None:
        config = SimpleNamespace(
            model=ModelConfig(
                active="kimi-k2.5",
                profiles=[
                    {
                        "name": "kimi-k2.5",
                        "provider": "custom",
                        "model_name": "kimi-k2.5",
                        "tasks": ["general"],
                        "compaction": {
                            "context_window_tokens": 256000,
                            "reserved_tokens": 24000,
                            "compact_after_tokens": 232000,
                        },
                    },
                ],
            ),
            compaction=SimpleNamespace(
                context_window_tokens=128000,
                reserved_tokens=8000,
                compact_after_tokens=90000,
            ),
        )

        self.manager._apply_active_profile_compaction_overrides(config)

        self.assertEqual(config.compaction.context_window_tokens, 256000)
        self.assertEqual(config.compaction.reserved_tokens, 24000)
        self.assertEqual(config.compaction.compact_after_tokens, 232000)


if __name__ == "__main__":
    unittest.main()
