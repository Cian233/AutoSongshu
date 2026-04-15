from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentscope.tool import Toolkit

from autosongshu_agent.skills import SkillRegistry, SkillRuntimeContext
from autosongshu_agent.skills import registry as skill_registry_module


def _write_skill(directory: Path, *, name: str, description: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    content = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        f"{body.strip()}\n"
    )
    (directory / "SKILL.md").write_text(content, encoding="utf-8")


class SkillRegistryTests(unittest.TestCase):
    def test_register_recursively_loads_nested_skill_and_builds_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested_skill_dir = root / "bundled" / "web" / "recon-web"
            _write_skill(
                nested_skill_dir,
                name="recon-web",
                description="First-pass reconnaissance workflow.",
                body="""
# Recon Web

## Recommended workflow

1. Navigate.
2. Snapshot.
                """,
            )

            report = SkillRegistry([str(root)]).register(Toolkit())

            self.assertEqual(report.loaded_paths, [str(nested_skill_dir.resolve())])
            self.assertEqual(report.as_dict()["counts"]["loaded"], 1)
            self.assertIsNotNone(report.agent_prompt)
            self.assertIn("Recommended workflow", report.agent_prompt or "")
            self.assertEqual(report.loaded[0].name, "recon-web")

    def test_register_prefers_later_duplicate_skill_name_registration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "skills-a" / "recon-web"
            second = root / "skills-b" / "recon-web-v2"
            _write_skill(first, name="recon-web", description="Primary skill.", body="# First")
            _write_skill(second, name="recon-web", description="Duplicate skill.", body="# Second")

            report = SkillRegistry([str(first), str(second)]).register(Toolkit())

            self.assertEqual(report.loaded_paths, [str(second.resolve())])
            self.assertEqual(len(report.skipped), 1)
            self.assertIn("overridden by a later registration", (report.skipped[0].reason or "").lower())

    def test_register_reuses_cached_skill_parse_until_skill_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_dir = root / "cached-skill"
            _write_skill(
                skill_dir,
                name="cached-skill",
                description="Cache test skill.",
                body="# Cache",
            )

            with patch.object(
                skill_registry_module,
                "_parse_skill_file",
                wraps=skill_registry_module._parse_skill_file,
            ) as parse_mock:
                first = SkillRegistry([str(skill_dir)]).register(Toolkit())
                second = SkillRegistry([str(skill_dir)]).register(Toolkit())

                self.assertEqual(parse_mock.call_count, 1)
                self.assertEqual(first.loaded[0].description, "Cache test skill.")
                self.assertEqual(second.loaded[0].description, "Cache test skill.")

                (skill_dir / "SKILL.md").write_text(
                    "---\n"
                    "name: cached-skill\n"
                    "description: Cache invalidated.\n"
                    "---\n\n"
                    "# Cache Updated\n",
                    encoding="utf-8",
                )

                third = SkillRegistry([str(skill_dir)]).register(Toolkit())
                self.assertEqual(parse_mock.call_count, 2)
                self.assertEqual(third.loaded[0].description, "Cache invalidated.")

    def test_register_keeps_manual_skills_available_for_explicit_activation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manual_skill_dir = root / "manual" / "graphql-recon"
            _write_skill(
                manual_skill_dir,
                name="graphql-recon",
                description="GraphQL reconnaissance workflow.",
                body="""
activation: manual
                """,
            )
            skill_file = manual_skill_dir / "SKILL.md"
            skill_file.write_text(
                "---\n"
                "name: graphql-recon\n"
                "description: GraphQL reconnaissance workflow.\n"
                "activation: manual\n"
                "---\n\n"
                "# GraphQL Recon\n",
                encoding="utf-8",
            )

            report = SkillRegistry(
                [str(root)],
                context=SkillRuntimeContext(available_tools={"http_request"}, active_hosts={"api.example.internal"}),
            ).register(Toolkit())

            self.assertEqual(report.loaded_paths, [])
            self.assertEqual(len(report.manual_available), 1)
            self.assertIsNotNone(report.agent_prompt)
            self.assertIn("On-Demand Skill: graphql-recon", report.agent_prompt or "")
            self.assertIn("/skill skill-name", report.agent_prompt or "")
            selection = report.build_turn_selection(["graphql-recon"])
            self.assertEqual([skill.name for skill in selection.activated], ["graphql-recon"])

    def test_register_discovers_skill_scripts_and_mentions_them_in_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scripted_skill = root / "scripted-skill"
            scripted_skill.mkdir(parents=True, exist_ok=True)
            (scripted_skill / "SKILL.md").write_text(
                "---\n"
                "name: scripted-skill\n"
                "description: Skill with reusable scripts.\n"
                "---\n\n"
                "# Scripted Skill\n",
                encoding="utf-8",
            )
            (scripted_skill / "scripts").mkdir(parents=True, exist_ok=True)
            (scripted_skill / "scripts" / "helper.py").write_text("print('ok')\n", encoding="utf-8")

            report = SkillRegistry([str(root)]).register(Toolkit())

            self.assertEqual(report.as_dict()["counts"]["loaded"], 1)
            self.assertEqual(len(report.loaded[0].scripts), 1)
            self.assertEqual(report.loaded[0].scripts[0].relative_path, "scripts/helper.py")
            self.assertIn("run_skill_script", report.agent_prompt or "")
            self.assertIn("scripts/helper.py", report.agent_prompt or "")
            self.assertIn("Local skill index for this run", report.agent_prompt or "")
            self.assertIn("scripted-skill [auto; scripted]", report.agent_prompt or "")

    def test_register_honors_skill_activation_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            conditioned = root / "conditioned-skill"
            conditioned.mkdir(parents=True, exist_ok=True)
            (conditioned / "SKILL.md").write_text(
                "---\n"
                "name: sandbox-heavy-recon\n"
                "description: Requires sandbox and a matching host.\n"
                "requires_sandbox: true\n"
                "requires_tools:\n"
                "  - sandbox_run_python\n"
                "host_patterns:\n"
                "  - '*.internal'\n"
                "---\n\n"
                "# Sandbox Heavy Recon\n",
                encoding="utf-8",
            )

            report = SkillRegistry(
                [str(root)],
                context=SkillRuntimeContext(
                    available_tools={"sandbox_run_python"},
                    sandbox_enabled=False,
                    active_hosts={"public.example.com"},
                ),
            ).register(Toolkit())

            self.assertEqual(report.as_dict()["counts"]["loaded"], 0)
            self.assertEqual(report.as_dict()["counts"]["manual_available"], 0)
            self.assertEqual(len(report.skipped), 1)
            self.assertEqual(report.skipped[0].name, "sandbox-heavy-recon")
            self.assertIn("Sandbox support is disabled", report.skipped[0].reason or "")

    def test_register_reports_invalid_and_missing_skill_sources_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            invalid = root / "invalid-skill"
            invalid.mkdir(parents=True, exist_ok=True)
            (invalid / "SKILL.md").write_text("# Missing front matter\n", encoding="utf-8")
            missing = root / "missing-skills"

            report = SkillRegistry([str(invalid), str(missing)]).register(Toolkit())

            self.assertEqual(report.as_dict()["counts"]["loaded"], 0)
            self.assertEqual(len(report.failed), 1)
            self.assertEqual(len(report.skipped), 1)
            self.assertIn("front matter", report.failed[0].reason or "")
            self.assertIn("does not exist", report.skipped[0].reason or "")

    def test_project_nmap_skill_is_auto_loaded(self) -> None:
        skill_dir = Path(__file__).resolve().parents[1] / "skills" / "nmap-recon"

        report = SkillRegistry(
            [str(skill_dir)],
            context=SkillRuntimeContext(
                available_tools={"list_skill_scripts", "run_skill_script"},
            ),
        ).register(Toolkit())

        self.assertEqual(report.loaded_paths, [str(skill_dir.resolve())])
        self.assertEqual(len(report.loaded), 1)
        self.assertEqual(len(report.manual_available), 0)
        self.assertEqual(report.loaded[0].name, "nmap-recon")
        self.assertEqual(report.loaded[0].activation_mode, "auto")
        self.assertEqual(
            report.loaded[0].requires_tools,
            ["list_skill_scripts", "run_skill_script"],
        )
        self.assertGreaterEqual(len(report.loaded[0].scripts), 2)
        self.assertIn("## Skill: nmap-recon", report.agent_prompt or "")
        self.assertIn("nmap-recon [auto; scripted]", report.agent_prompt or "")

    def test_project_dirsearch_skill_is_auto_loaded(self) -> None:
        skill_dir = Path(__file__).resolve().parents[1] / "skills" / "dirsearch-recon"

        report = SkillRegistry(
            [str(skill_dir)],
            context=SkillRuntimeContext(
                available_tools={"list_skill_scripts", "run_skill_script"},
            ),
        ).register(Toolkit())

        self.assertEqual(report.loaded_paths, [str(skill_dir.resolve())])
        self.assertEqual(len(report.loaded), 1)
        self.assertEqual(len(report.manual_available), 0)
        self.assertEqual(report.loaded[0].name, "dirsearch-recon")
        self.assertEqual(report.loaded[0].activation_mode, "auto")
        self.assertEqual(
            report.loaded[0].requires_tools,
            ["list_skill_scripts", "run_skill_script"],
        )
        self.assertGreaterEqual(len(report.loaded[0].scripts), 2)
        self.assertIn("## Skill: dirsearch-recon", report.agent_prompt or "")
        self.assertIn("dirsearch-recon [auto; scripted]", report.agent_prompt or "")

    def test_project_sqlmap_skill_is_auto_loaded(self) -> None:
        skill_dir = Path(__file__).resolve().parents[1] / "skills" / "sqlmap-sqli"

        report = SkillRegistry(
            [str(skill_dir)],
            context=SkillRuntimeContext(
                available_tools={"list_skill_scripts", "run_skill_script"},
            ),
        ).register(Toolkit())

        self.assertEqual(report.loaded_paths, [str(skill_dir.resolve())])
        self.assertEqual(len(report.loaded), 1)
        self.assertEqual(len(report.manual_available), 0)
        self.assertEqual(report.loaded[0].name, "sqlmap-sqli")
        self.assertEqual(report.loaded[0].activation_mode, "auto")
        self.assertEqual(
            report.loaded[0].requires_tools,
            ["list_skill_scripts", "run_skill_script"],
        )
        self.assertGreaterEqual(len(report.loaded[0].scripts), 2)
        self.assertIn("## Skill: sqlmap-sqli", report.agent_prompt or "")
        self.assertIn("sqlmap-sqli [auto; scripted]", report.agent_prompt or "")


if __name__ == "__main__":
    unittest.main()
