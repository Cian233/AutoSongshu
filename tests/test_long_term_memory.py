from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from autosongshu_agent.agent.long_term_memory import (
    Experience,
    LongTermMemory,
)


class ExperienceTests(unittest.TestCase):
    def _make_experience(self) -> Experience:
        return Experience(
            id="exp-001",
            session_id="session-abc",
            target_url="https://example.test",
            target_type="web_app",
            tech_stack=["Python", "Flask", "PostgreSQL"],
            vulnerability_types=["SQL Injection", "XSS"],
            findings=[
                {"title": "SQL Injection", "severity": "high", "url": "https://example.test/login"},
                {"title": "Reflected XSS", "severity": "medium", "url": "https://example.test/search"},
            ],
            successful_strategies=["Blind SQLi time-based", "DOM-based XSS payload"],
            failed_approaches=["Direct SQLi on login form"],
            lessons_learned="Time-based blind SQLi was effective; WAF blocked direct injection attempts.",
            created_at=1700000000.0,
        )

    def test_experience_to_dict(self) -> None:
        exp = self._make_experience()
        d = exp.to_dict()
        self.assertEqual(d["id"], "exp-001")
        self.assertEqual(d["session_id"], "session-abc")
        self.assertEqual(d["target_url"], "https://example.test")
        self.assertEqual(d["target_type"], "web_app")
        self.assertEqual(d["tech_stack"], ["Python", "Flask", "PostgreSQL"])
        self.assertEqual(d["vulnerability_types"], ["SQL Injection", "XSS"])
        self.assertEqual(len(d["findings"]), 2)
        self.assertEqual(d["successful_strategies"], ["Blind SQLi time-based", "DOM-based XSS payload"])
        self.assertEqual(d["failed_approaches"], ["Direct SQLi on login form"])
        self.assertEqual(
            d["lessons_learned"],
            "Time-based blind SQLi was effective; WAF blocked direct injection attempts.",
        )
        self.assertEqual(d["created_at"], 1700000000.0)

    def test_experience_from_dict(self) -> None:
        data = {
            "id": "exp-002",
            "session_id": "session-def",
            "target_url": "https://api.example.test",
            "target_type": "api",
            "tech_stack": ["Node.js", "Express"],
            "vulnerability_types": ["IDOR"],
            "findings": [{"title": "IDOR", "severity": "high"}],
            "successful_strategies": ["Sequential ID enumeration"],
            "failed_approaches": [],
            "lessons_learned": "IDOR found via sequential IDs.",
            "created_at": 1700000100.0,
        }
        exp = Experience.from_dict(data)
        self.assertEqual(exp.id, "exp-002")
        self.assertEqual(exp.session_id, "session-def")
        self.assertEqual(exp.target_url, "https://api.example.test")
        self.assertEqual(exp.target_type, "api")
        self.assertEqual(exp.tech_stack, ["Node.js", "Express"])
        self.assertEqual(exp.vulnerability_types, ["IDOR"])
        self.assertEqual(len(exp.findings), 1)
        self.assertEqual(exp.successful_strategies, ["Sequential ID enumeration"])
        self.assertEqual(exp.failed_approaches, [])
        self.assertEqual(exp.lessons_learned, "IDOR found via sequential IDs.")
        self.assertEqual(exp.created_at, 1700000100.0)

    def test_experience_from_dict_with_defaults(self) -> None:
        data = {
            "id": "exp-003",
            "session_id": "session-ghi",
            "target_url": "https://minimal.test",
            "target_type": "web_app",
        }
        exp = Experience.from_dict(data)
        self.assertEqual(exp.id, "exp-003")
        self.assertEqual(exp.tech_stack, [])
        self.assertEqual(exp.vulnerability_types, [])
        self.assertEqual(exp.findings, [])
        self.assertEqual(exp.successful_strategies, [])
        self.assertEqual(exp.failed_approaches, [])
        self.assertEqual(exp.lessons_learned, "")
        self.assertEqual(exp.created_at, 0.0)

    def test_experience_roundtrip(self) -> None:
        exp = self._make_experience()
        d = exp.to_dict()
        restored = Experience.from_dict(d)
        self.assertEqual(restored.id, exp.id)
        self.assertEqual(restored.session_id, exp.session_id)
        self.assertEqual(restored.target_url, exp.target_url)
        self.assertEqual(restored.target_type, exp.target_type)
        self.assertEqual(restored.tech_stack, exp.tech_stack)
        self.assertEqual(restored.vulnerability_types, exp.vulnerability_types)
        self.assertEqual(restored.findings, exp.findings)
        self.assertEqual(restored.successful_strategies, exp.successful_strategies)
        self.assertEqual(restored.failed_approaches, exp.failed_approaches)
        self.assertEqual(restored.lessons_learned, exp.lessons_learned)
        self.assertEqual(restored.created_at, exp.created_at)

    def test_render_for_prompt_basic(self) -> None:
        exp = self._make_experience()
        rendered = exp.render_for_prompt()
        self.assertIn("## Experience:", rendered)
        self.assertIn("web_app", rendered)
        self.assertIn("SQL Injection", rendered)
        self.assertIn("XSS", rendered)
        self.assertIn("https://example.test", rendered)
        self.assertIn("Python", rendered)
        self.assertIn("Flask", rendered)

    def test_render_for_prompt_includes_successful_strategies(self) -> None:
        exp = self._make_experience()
        rendered = exp.render_for_prompt()
        self.assertIn("Successful Strategies:", rendered)
        self.assertIn("Blind SQLi time-based", rendered)
        self.assertIn("DOM-based XSS payload", rendered)

    def test_render_for_prompt_includes_failed_approaches(self) -> None:
        exp = self._make_experience()
        rendered = exp.render_for_prompt()
        self.assertIn("Failed Approaches:", rendered)
        self.assertIn("Direct SQLi on login form", rendered)

    def test_render_for_prompt_includes_lessons_learned(self) -> None:
        exp = self._make_experience()
        rendered = exp.render_for_prompt()
        self.assertIn("Lessons Learned:", rendered)
        self.assertIn("Time-based blind SQLi", rendered)

    def test_render_for_prompt_includes_findings(self) -> None:
        exp = self._make_experience()
        rendered = exp.render_for_prompt()
        self.assertIn("Key Findings:", rendered)
        self.assertIn("[HIGH] SQL Injection", rendered)
        self.assertIn("[MEDIUM] Reflected XSS", rendered)

    def test_render_for_prompt_empty_vulnerability_types(self) -> None:
        exp = Experience(
            id="exp-empty",
            session_id="session-1",
            target_url="https://empty.test",
            target_type="web_app",
            tech_stack=[],
            vulnerability_types=[],
            findings=[],
            successful_strategies=[],
            failed_approaches=[],
            lessons_learned="",
            created_at=1700000000.0,
        )
        rendered = exp.render_for_prompt()
        self.assertIn("unknown", rendered)
        self.assertNotIn("Successful Strategies:", rendered)
        self.assertNotIn("Failed Approaches:", rendered)
        self.assertNotIn("Lessons Learned:", rendered)
        self.assertNotIn("Key Findings:", rendered)

    def test_render_for_prompt_limits_findings_to_five(self) -> None:
        exp = Experience(
            id="exp-many",
            session_id="session-1",
            target_url="https://many.test",
            target_type="web_app",
            tech_stack=[],
            vulnerability_types=["SQLi"],
            findings=[
                {"title": f"Finding {i}", "severity": "low"} for i in range(10)
            ],
            successful_strategies=[],
            failed_approaches=[],
            lessons_learned="",
            created_at=1700000000.0,
        )
        rendered = exp.render_for_prompt()
        self.assertIn("Key Findings:", rendered)
        self.assertIn("[LOW] Finding 0", rendered)
        self.assertIn("[LOW] Finding 4", rendered)
        self.assertNotIn("[LOW] Finding 5", rendered)
        self.assertNotIn("[LOW] Finding 9", rendered)

    def test_render_for_prompt_empty_tech_stack(self) -> None:
        exp = Experience(
            id="exp-no-tech",
            session_id="session-1",
            target_url="https://no-tech.test",
            target_type="web_app",
            tech_stack=[],
            vulnerability_types=["XSS"],
            findings=[],
            successful_strategies=[],
            failed_approaches=[],
            lessons_learned="",
            created_at=1700000000.0,
        )
        rendered = exp.render_for_prompt()
        self.assertIn("N/A", rendered)


class LongTermMemoryTests(unittest.TestCase):
    def _make_memory(self, storage_dir: Path | None = None) -> LongTermMemory:
        if storage_dir is None:
            storage_dir = Path(tempfile.mkdtemp())
        return LongTermMemory(storage_dir=storage_dir)

    def test_memory_initialization_creates_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = Path(tmpdir) / "test_memory"
            memory = self._make_memory(mem_dir)
            self.assertTrue(mem_dir.exists())
            self.assertTrue(mem_dir.is_dir())

    def test_memory_initialization_with_default_dir(self) -> None:
        memory = LongTermMemory()
        self.assertTrue(memory._storage_dir.exists())

    def test_store_experience(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            experience = memory.store_experience(
                session_id="session-001",
                findings=[
                    {"title": "SQL Injection", "severity": "high"},
                ],
                strategies={
                    "successful": ["Blind SQLi"],
                    "failed": ["Direct SQLi"],
                    "lessons_learned": "WAF blocks direct injection",
                },
                target_info={
                    "target_url": "https://target.test",
                    "target_type": "web_app",
                    "tech_stack": ["Python", "Flask"],
                    "vulnerability_types": ["SQL Injection"],
                },
            )
            self.assertIsNotNone(experience.id)
            self.assertEqual(experience.session_id, "session-001")
            self.assertEqual(experience.target_url, "https://target.test")
            self.assertEqual(experience.target_type, "web_app")
            self.assertEqual(experience.tech_stack, ["Python", "Flask"])
            self.assertEqual(experience.vulnerability_types, ["SQL Injection"])
            self.assertEqual(len(experience.findings), 1)
            self.assertEqual(experience.successful_strategies, ["Blind SQLi"])
            self.assertEqual(experience.failed_approaches, ["Direct SQLi"])
            self.assertEqual(experience.lessons_learned, "WAF blocks direct injection")
            self.assertGreater(experience.created_at, 0.0)

    def test_store_experience_persists_to_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = Path(tmpdir)
            memory = self._make_memory(mem_dir)
            memory.store_experience(
                session_id="session-001",
                findings=[{"title": "XSS", "severity": "medium"}],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://persist.test",
                    "target_type": "web_app",
                    "tech_stack": [],
                    "vulnerability_types": ["XSS"],
                },
            )
            index_file = mem_dir / "index.json"
            self.assertTrue(index_file.exists())
            data = json.loads(index_file.read_text(encoding="utf-8"))
            self.assertIsInstance(data, list)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["target_url"], "https://persist.test")

    def test_retrieve_relevant_experience_by_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            memory.store_experience(
                session_id="session-1",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://example.test/login",
                    "target_type": "web_app",
                    "tech_stack": ["Python"],
                    "vulnerability_types": ["SQL Injection"],
                },
            )
            memory.store_experience(
                session_id="session-2",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://completely-different.org/api",
                    "target_type": "api",
                    "tech_stack": ["Node.js"],
                    "vulnerability_types": [],
                },
            )
            results = memory.retrieve_relevant_experience("example.test")
            self.assertGreaterEqual(len(results), 1)
            self.assertIn("example.test", results[0].target_url)

    def test_retrieve_relevant_experience_by_tech_stack(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            memory.store_experience(
                session_id="session-1",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://python-app.test",
                    "target_type": "web_app",
                    "tech_stack": ["Python", "Flask"],
                    "vulnerability_types": [],
                },
            )
            memory.store_experience(
                session_id="session-2",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://node-api.test",
                    "target_type": "api",
                    "tech_stack": ["Node.js", "Express"],
                    "vulnerability_types": [],
                },
            )
            results = memory.retrieve_relevant_experience(
                "python-app.test", tech_stack="Python"
            )
            self.assertGreaterEqual(len(results), 1)
            self.assertIn("Python", results[0].tech_stack)

    def test_retrieve_relevant_experience_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            for i in range(10):
                memory.store_experience(
                    session_id=f"session-{i}",
                    findings=[],
                    strategies={"successful": [], "failed": [], "lessons_learned": ""},
                    target_info={
                        "target_url": f"https://target{i}.test",
                        "target_type": "web_app",
                        "tech_stack": ["Python"],
                        "vulnerability_types": ["XSS"],
                    },
                )
            results = memory.retrieve_relevant_experience("target", limit=3)
            self.assertLessEqual(len(results), 3)

    def test_retrieve_relevant_experience_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            memory.store_experience(
                session_id="session-1",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://example.test",
                    "target_type": "web_app",
                    "tech_stack": [],
                    "vulnerability_types": [],
                },
            )
            results = memory.retrieve_relevant_experience("nonexistent.test")
            self.assertEqual(results, [])

    def test_search_experiences_by_vulnerability_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            memory.store_experience(
                session_id="session-1",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://sqli.test",
                    "target_type": "web_app",
                    "tech_stack": [],
                    "vulnerability_types": ["SQL Injection"],
                },
            )
            memory.store_experience(
                session_id="session-2",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://xss.test",
                    "target_type": "web_app",
                    "tech_stack": [],
                    "vulnerability_types": ["XSS"],
                },
            )
            results = memory.search_experiences(vulnerability_type="SQL")
            self.assertEqual(len(results), 1)
            self.assertIn("SQL Injection", results[0].vulnerability_types)

    def test_search_experiences_by_target_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            memory.store_experience(
                session_id="session-1",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://web.test",
                    "target_type": "web_app",
                    "tech_stack": [],
                    "vulnerability_types": ["XSS"],
                },
            )
            memory.store_experience(
                session_id="session-2",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://api.test",
                    "target_type": "api",
                    "tech_stack": [],
                    "vulnerability_types": ["IDOR"],
                },
            )
            results = memory.search_experiences(target_type="api")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].target_type, "api")

    def test_search_experiences_combined_filters(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            memory.store_experience(
                session_id="session-1",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://web-sqli.test",
                    "target_type": "web_app",
                    "tech_stack": [],
                    "vulnerability_types": ["SQL Injection"],
                },
            )
            memory.store_experience(
                session_id="session-2",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://api-sqli.test",
                    "target_type": "api",
                    "tech_stack": [],
                    "vulnerability_types": ["SQL Injection"],
                },
            )
            results = memory.search_experiences(
                vulnerability_type="SQL", target_type="web_app"
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].target_type, "web_app")
            self.assertIn("SQL Injection", results[0].vulnerability_types)

    def test_search_experiences_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            for i in range(15):
                memory.store_experience(
                    session_id=f"session-{i}",
                    findings=[],
                    strategies={"successful": [], "failed": [], "lessons_learned": ""},
                    target_info={
                        "target_url": f"https://search{i}.test",
                        "target_type": "web_app",
                        "tech_stack": [],
                        "vulnerability_types": ["XSS"],
                    },
                )
            results = memory.search_experiences(vulnerability_type="XSS", limit=5)
            self.assertLessEqual(len(results), 5)

    def test_search_experiences_no_filter_returns_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            for i in range(5):
                memory.store_experience(
                    session_id=f"session-{i}",
                    findings=[],
                    strategies={"successful": [], "failed": [], "lessons_learned": ""},
                    target_info={
                        "target_url": f"https://all{i}.test",
                        "target_type": "web_app",
                        "tech_stack": [],
                        "vulnerability_types": ["XSS"],
                    },
                )
            results = memory.search_experiences()
            self.assertEqual(len(results), 5)

    def test_search_experiences_sorted_by_created_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            memory.store_experience(
                session_id="session-old",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://old.test",
                    "target_type": "web_app",
                    "tech_stack": [],
                    "vulnerability_types": ["XSS"],
                },
            )
            memory.store_experience(
                session_id="session-new",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://new.test",
                    "target_type": "web_app",
                    "tech_stack": [],
                    "vulnerability_types": ["XSS"],
                },
            )
            results = memory.search_experiences(vulnerability_type="XSS")
            self.assertGreaterEqual(
                results[0].created_at, results[-1].created_at
            )

    def test_get_all_experiences(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            for i in range(3):
                memory.store_experience(
                    session_id=f"session-{i}",
                    findings=[],
                    strategies={"successful": [], "failed": [], "lessons_learned": ""},
                    target_info={
                        "target_url": f"https://all{i}.test",
                        "target_type": "web_app",
                        "tech_stack": [],
                        "vulnerability_types": ["XSS"],
                    },
                )
            all_exp = memory.get_all_experiences()
            self.assertEqual(len(all_exp), 3)

    def test_get_experience_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            self.assertEqual(memory.get_experience_count(), 0)
            memory.store_experience(
                session_id="session-1",
                findings=[],
                strategies={"successful": [], "failed": [], "lessons_learned": ""},
                target_info={
                    "target_url": "https://count.test",
                    "target_type": "web_app",
                    "tech_stack": [],
                    "vulnerability_types": ["XSS"],
                },
            )
            self.assertEqual(memory.get_experience_count(), 1)

    def test_render_experiences_for_prompt_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            rendered = memory.render_experiences_for_prompt([])
            self.assertEqual(rendered, "")

    def test_render_experiences_for_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            exp = memory.store_experience(
                session_id="session-render",
                findings=[{"title": "SQLi", "severity": "high"}],
                strategies={
                    "successful": ["Blind SQLi"],
                    "failed": [],
                    "lessons_learned": "WAF bypass needed",
                },
                target_info={
                    "target_url": "https://render.test",
                    "target_type": "web_app",
                    "tech_stack": ["Python"],
                    "vulnerability_types": ["SQL Injection"],
                },
            )
            rendered = memory.render_experiences_for_prompt([exp])
            self.assertIn("# Historical Penetration Testing Experiences", rendered)
            self.assertIn("https://render.test", rendered)
            self.assertIn("SQL Injection", rendered)
            self.assertIn("Python", rendered)
            self.assertIn("Blind SQLi", rendered)
            self.assertIn("WAF bypass needed", rendered)

    def test_render_experiences_for_prompt_respects_max_chars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = self._make_memory(Path(tmpdir))
            experiences = []
            for i in range(10):
                exp = memory.store_experience(
                    session_id=f"session-{i}",
                    findings=[{"title": f"Finding {i}", "severity": "high"}],
                    strategies={
                        "successful": [f"Strategy {i} with some extra text to make it longer"],
                        "failed": [f"Failed approach {i} with additional context"],
                        "lessons_learned": f"Lesson {i}: important learning about the target system and its vulnerabilities",
                    },
                    target_info={
                        "target_url": f"https://render{i}.test",
                        "target_type": "web_app",
                        "tech_stack": ["Python", "Flask", "PostgreSQL"],
                        "vulnerability_types": ["SQL Injection", "XSS", "SSRF"],
                    },
                )
                experiences.append(exp)
            rendered = memory.render_experiences_for_prompt(experiences, max_chars=500)
            self.assertLessEqual(len(rendered), 600)
            self.assertIn("truncated", rendered)

    def test_load_index_from_list_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = Path(tmpdir)
            index_file = mem_dir / "index.json"
            data = [
                {
                    "id": "exp-list-1",
                    "session_id": "session-list-1",
                    "target_url": "https://list1.test",
                    "target_type": "web_app",
                    "tech_stack": ["Python"],
                    "vulnerability_types": ["XSS"],
                    "findings": [],
                    "successful_strategies": [],
                    "failed_approaches": [],
                    "lessons_learned": "",
                    "created_at": 1700000000.0,
                }
            ]
            index_file.write_text(json.dumps(data), encoding="utf-8")
            memory = self._make_memory(mem_dir)
            self.assertEqual(memory.get_experience_count(), 1)
            exp = memory.get_all_experiences()[0]
            self.assertEqual(exp.id, "exp-list-1")

    def test_load_index_from_dict_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = Path(tmpdir)
            index_file = mem_dir / "index.json"
            data = {
                "exp-dict-1": {
                    "id": "exp-dict-1",
                    "session_id": "session-dict-1",
                    "target_url": "https://dict1.test",
                    "target_type": "api",
                    "tech_stack": ["Node.js"],
                    "vulnerability_types": ["IDOR"],
                    "findings": [],
                    "successful_strategies": [],
                    "failed_approaches": [],
                    "lessons_learned": "",
                    "created_at": 1700000100.0,
                }
            }
            index_file.write_text(json.dumps(data), encoding="utf-8")
            memory = self._make_memory(mem_dir)
            self.assertEqual(memory.get_experience_count(), 1)
            exp = memory.get_all_experiences()[0]
            self.assertEqual(exp.id, "exp-dict-1")

    def test_load_index_handles_corrupt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = Path(tmpdir)
            index_file = mem_dir / "index.json"
            index_file.write_text("not valid json {{{", encoding="utf-8")
            memory = self._make_memory(mem_dir)
            self.assertEqual(memory.get_experience_count(), 0)

    def test_load_index_handles_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = Path(tmpdir)
            memory = self._make_memory(mem_dir)
            self.assertEqual(memory.get_experience_count(), 0)

    def test_store_multiple_experiences_persists_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_dir = Path(tmpdir)
            memory = self._make_memory(mem_dir)
            for i in range(5):
                memory.store_experience(
                    session_id=f"session-{i}",
                    findings=[{"title": f"Finding {i}", "severity": "high"}],
                    strategies={"successful": [], "failed": [], "lessons_learned": ""},
                    target_info={
                        "target_url": f"https://multi{i}.test",
                        "target_type": "web_app",
                        "tech_stack": [],
                        "vulnerability_types": ["XSS"],
                    },
                )
            self.assertEqual(memory.get_experience_count(), 5)
            index_file = mem_dir / "index.json"
            data = json.loads(index_file.read_text(encoding="utf-8"))
            self.assertEqual(len(data), 5)


if __name__ == "__main__":
    unittest.main()
