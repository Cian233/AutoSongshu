from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agentscope.tool import Toolkit

from autosongshu_agent.artifacts import ArtifactStore
from autosongshu_agent.skills import SkillScriptRunner
from autosongshu_agent.config import ScopePolicy
from autosongshu_agent.skills import SkillRegistry


class SkillScriptRunnerTests(unittest.TestCase):
    def test_list_and_run_python_skill_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            skill_dir = root / "demo-skill"
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\n"
                "name: demo-skill\n"
                "description: Demo scripted skill.\n"
                "activation: manual\n"
                "---\n\n"
                "# Demo Skill\n",
                encoding="utf-8",
            )
            (scripts_dir / "echo_args.py").write_text(
                "from __future__ import annotations\n"
                "import json\n"
                "import os\n"
                "import sys\n"
                "print(json.dumps({\n"
                "    'argv': sys.argv[1:],\n"
                "    'skill': os.getenv('AUTOSONGSHU_SKILL_NAME'),\n"
                "    'allowed_hosts': os.getenv('AUTOSONGSHU_SCOPE_ALLOWED_HOSTS'),\n"
                "    'authorization': os.getenv('AUTOSONGSHU_AUTHORIZATION'),\n"
                "}, ensure_ascii=False))\n",
                encoding="utf-8",
            )

            report = SkillRegistry([str(skill_dir)]).register(Toolkit())
            runner = SkillScriptRunner(
                ArtifactStore(str(root / "artifacts"), "demo", "session"),
                scope=ScopePolicy(
                    start_url="https://app.example.internal",
                    allowed_hosts=["example.internal"],
                    allow_subdomains=True,
                ),
                authorization="AUTHORIZED",
            )
            runner.update_skills(report.loaded, manual_skills=report.manual_available)

            listed_all = runner.list_scripts()
            self.assertEqual(len(listed_all["skills"]), 1)
            self.assertEqual(listed_all["skills"][0]["skill"], "demo-skill")
            self.assertEqual(listed_all["skills"][0]["activation_mode"], "manual")
            self.assertFalse(listed_all["skills"][0]["prompt_visible"])

            listed = runner.list_scripts("demo-skill")
            self.assertEqual(listed["skill"], "demo-skill")
            self.assertEqual(listed["activation_mode"], "manual")
            self.assertFalse(listed["prompt_visible"])
            self.assertEqual(
                listed["scripts"][0]["relative_path"], "scripts/echo_args.py"
            )

            result = runner.run(
                skill_name="demo-skill",
                script_name="echo_args.py",
                args=["alpha", "beta"],
                timeout_sec=30,
            )

            self.assertTrue(result["ok"])
            self.assertIn('"argv": ["alpha", "beta"]', result["stdout"])
            self.assertIn('"skill": "demo-skill"', result["stdout"])
            self.assertIn("example.internal", result["stdout"])
            self.assertIn('"authorization": "AUTHORIZED"', result["stdout"])
            self.assertTrue(
                (runner.artifacts.session_dir / "skill-scripts.jsonl").is_file()
            )


if __name__ == "__main__":
    unittest.main()
