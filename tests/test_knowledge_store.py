from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from autosongshu_agent.knowledge_store import (
    KnowledgeBaseDraft,
    KnowledgeBaseUpdateDraft,
    KnowledgeDocumentDraft,
    KnowledgeStore,
)


class KnowledgeStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = KnowledgeStore(project_root=Path(self.temp_dir.name))
        self.addCleanup(self.store.close)

    def test_create_base_and_document_updates_counts(self) -> None:
        created_base = self.store.create_base(
            KnowledgeBaseDraft(name="Web Pentest Playbook", description="Operational notes"),
        )
        self.assertEqual(created_base["document_count"], 0)
        self.assertEqual(created_base["chunk_count"], 0)

        created_document = self.store.create_document(
            created_base["id"],
            KnowledgeDocumentDraft(
                title="Login Checklist",
                content="Check rate limiting.\n\nCheck lockout policy.\n\nCheck reset flow.",
                source_type="text",
                source="internal wiki",
            ),
        )

        self.assertEqual(created_document["title"], "Login Checklist")
        self.assertGreaterEqual(created_document["chunk_count"], 1)

        base_detail = self.store.get_base(created_base["id"])
        self.assertEqual(base_detail["document_count"], 1)
        self.assertGreaterEqual(base_detail["chunk_count"], 1)
        self.assertEqual(len(base_detail["documents"]), 1)
        self.assertEqual(base_detail["documents"][0]["source"], "internal wiki")

    def test_search_chunks_returns_ranked_hits(self) -> None:
        base = self.store.create_base(KnowledgeBaseDraft(name="Knowledge", description=None))
        self.store.create_document(
            base["id"],
            KnowledgeDocumentDraft(
                title="JWT Notes",
                content="JWT secret exposure can happen through source leaks. Rotate compromised secrets immediately.",
                source_type="text",
            ),
        )
        self.store.create_document(
            base["id"],
            KnowledgeDocumentDraft(
                title="XSS Notes",
                content="Reflected XSS can be mitigated with context-aware output encoding.",
                source_type="text",
            ),
        )

        hits = self.store.search_chunks([base["id"]], "JWT secret exposure", limit=3)

        self.assertGreaterEqual(len(hits), 1)
        self.assertEqual(hits[0]["knowledge_base_id"], base["id"])
        self.assertIn("JWT", hits[0]["document_title"])
        self.assertGreater(hits[0]["score"], 0)

    def test_filter_existing_base_ids_keeps_input_order(self) -> None:
        base_a = self.store.create_base(KnowledgeBaseDraft(name="A", description=None))
        base_b = self.store.create_base(KnowledgeBaseDraft(name="B", description=None))
        filtered = self.store.filter_existing_base_ids(["missing", base_b["id"], base_a["id"], base_b["id"]])
        self.assertEqual(filtered, [base_b["id"], base_a["id"], base_b["id"]])

    def test_update_base_changes_name_and_description(self) -> None:
        created = self.store.create_base(KnowledgeBaseDraft(name="Old Name", description="Old Desc"))
        updated = self.store.update_base(
            created["id"],
            KnowledgeBaseUpdateDraft(name="New Name", description="New Desc"),
        )
        self.assertEqual(updated["name"], "New Name")
        self.assertEqual(updated["description"], "New Desc")

    def test_vulnerability_section_chunking_preserves_location_and_root_cause(self) -> None:
        base = self.store.create_base(KnowledgeBaseDraft(name="Vuln KB", description=None))
        content = """
## 漏洞成因链路
触发条件：登录接口允许高频尝试，且返回差异化错误。
脆弱点：/api/auth/login 接口对 user_id 参数缺少统一响应与频率限制。
漏洞形成：攻击者可枚举有效账号并进行口令喷洒。

## 漏洞点定位
接口：POST /api/auth/login
参数：user_id
行为：不存在账号返回 404，存在账号返回 401，形成可观测差异。

## 修复与加固
统一错误响应；增加限速和账号锁定策略。
""".strip()
        self.store.create_document(
            base["id"],
            KnowledgeDocumentDraft(
                title="登录接口账号枚举",
                content=content,
                source_type="text",
            ),
        )

        hits = self.store.search_chunks([base["id"]], "user_id 参数 漏洞点 定位", limit=3)
        self.assertGreaterEqual(len(hits), 1)
        top = hits[0]["content"]
        self.assertTrue("漏洞点定位" in top or "/api/auth/login" in top)
        self.assertTrue("user_id" in top or "触发条件" in top)


if __name__ == "__main__":
    unittest.main()
