from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from autosongshu_agent.chat_manager import (
    ChatMessage,
    ChatSessionManager,
    ChatSessionState,
    CreateKnowledgeFromSessionRequest,
)
from autosongshu_agent.utils import now_iso
from autosongshu_agent.knowledge_store import KnowledgeBaseDraft, KnowledgeDocumentDraft


class ChatManagerKnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.manager = ChatSessionManager(project_root=Path(self.temp_dir.name))
        self.addCleanup(self.manager.shutdown)

    def test_session_pinned_context_mentions_linked_knowledge_bases(self) -> None:
        kb = self.manager.create_knowledge_base(
            KnowledgeBaseDraft(name="Incident Notes", description=None)
        )
        session = ChatSessionState(
            session_id="chat-0001",
            title="KB linked",
            config_path="E:/config.yaml",
            knowledge_base_ids=[kb["id"]],
        )

        pinned = self.manager._session_pinned_context(session)

        self.assertIn("Linked knowledge bases: Incident Notes", pinned)

    def test_normalize_knowledge_base_ids_rejects_missing_ids(self) -> None:
        with self.assertRaises(ValueError):
            self.manager._normalize_knowledge_base_ids(["missing-kb-id"])

    def test_create_knowledge_document_from_session_creates_document(self) -> None:
        kb = self.manager.create_knowledge_base(
            KnowledgeBaseDraft(name="Ops Notes", description=None)
        )
        timestamp = now_iso()
        session = ChatSessionState(
            session_id="chat-0001",
            title="Login Flow",
            config_path="E:/config.yaml",
            knowledge_base_ids=[kb["id"]],
            messages=[
                ChatMessage(
                    id="msg-user",
                    role="user",
                    status="completed",
                    content=[
                        {"type": "input_text", "text": "发现登录接口会返回详细报错"}
                    ],
                    created_at=timestamp,
                    updated_at=timestamp,
                    order_index=1,
                ),
                ChatMessage(
                    id="msg-assistant",
                    role="assistant",
                    status="completed",
                    content=[
                        {
                            "type": "output_text",
                            "text": "建议先验证账号枚举与限速策略。",
                        }
                    ],
                    created_at=timestamp,
                    updated_at=timestamp,
                    order_index=2,
                ),
            ],
        )
        with self.manager.lock:
            self.manager.chat_sessions[session.session_id] = session

        self.manager._generate_knowledge_summary_from_session = lambda **_: {
            "title": "登录流程渗透经验",
            "content": "## 关键发现\n- 可枚举账号\n",
            "model_name": "stub-model",
        }

        result = self.manager.create_knowledge_document_from_session(
            "chat-0001",
            CreateKnowledgeFromSessionRequest(),
        )

        self.assertEqual(result["status"], "created")
        self.assertEqual(result["knowledge_base_id"], kb["id"])
        self.assertEqual(result["summary_model"], "stub-model")
        self.assertEqual(result["document"]["title"], "登录流程渗透经验")
        self.assertNotEqual(result["document"]["title"], "手工标题")

        base_detail = self.manager.get_knowledge_base(kb["id"])
        self.assertEqual(base_detail["document_count"], 1)

    def test_create_knowledge_document_from_session_requires_target_kb(self) -> None:
        with self.manager.lock:
            self.manager.chat_sessions["chat-0009"] = ChatSessionState(
                session_id="chat-0009",
                title="No KB",
                config_path="E:/config.yaml",
                messages=[],
            )

        with self.assertRaises(ValueError):
            self.manager.create_knowledge_document_from_session(
                "chat-0009",
                CreateKnowledgeFromSessionRequest(),
            )

    def test_create_knowledge_document_from_session_missing_session(self) -> None:
        with self.assertRaises(KeyError):
            self.manager.create_knowledge_document_from_session(
                "chat-missing",
                CreateKnowledgeFromSessionRequest(knowledge_base_id="kb"),
            )

    def test_create_knowledge_document_from_session_auto_links_knowledge_base(
        self,
    ) -> None:
        kb = self.manager.create_knowledge_base(
            KnowledgeBaseDraft(name="Auto Link KB", description=None)
        )
        timestamp = now_iso()
        session = ChatSessionState(
            session_id="chat-0010",
            title="No Link Yet",
            config_path="E:/config.yaml",
            messages=[
                ChatMessage(
                    id="msg-user-10",
                    role="user",
                    status="completed",
                    content=[{"type": "input_text", "text": "请沉淀当前过程"}],
                    created_at=timestamp,
                    updated_at=timestamp,
                    order_index=1,
                ),
            ],
        )
        with self.manager.lock:
            self.manager.chat_sessions[session.session_id] = session

        self.manager._generate_knowledge_summary_from_session = lambda **_: {
            "title": "自动关联测试",
            "content": "## 关键发现\n- done\n",
            "model_name": "stub-model",
        }

        result = self.manager.create_knowledge_document_from_session(
            "chat-0010",
            CreateKnowledgeFromSessionRequest(knowledge_base_id=kb["id"]),
        )

        self.assertTrue(result["linked_to_session"])
        updated = self.manager.get_chat_session("chat-0010")
        self.assertIn(kb["id"], updated["knowledge_base_ids"])


if __name__ == "__main__":
    unittest.main()
