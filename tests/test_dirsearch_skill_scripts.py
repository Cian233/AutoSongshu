from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_dirsearch_common():
    module_path = Path(__file__).resolve().parents[1] / "skills" / "dirsearch-recon" / "scripts" / "dirsearch_common.py"
    spec = importlib.util.spec_from_file_location("test_dirsearch_common", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DirsearchSkillScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dirsearch_common = _load_dirsearch_common()
        self._temp_dir = tempfile.TemporaryDirectory()
        root = Path(self._temp_dir.name)
        self.skill_dir = root / "dirsearch-recon"
        vendor_dir = self.skill_dir / "vendor" / "dirsearch"
        (vendor_dir / "db" / "categories").mkdir(parents=True, exist_ok=True)
        (vendor_dir / "dirsearch.py").write_text("print('dirsearch')\n", encoding="utf-8")
        (vendor_dir / "config.ini").write_text("[general]\nthreads = 10\n", encoding="utf-8")
        (vendor_dir / "db" / "categories" / "common.txt").write_text("admin\n", encoding="utf-8")
        (vendor_dir / "db" / "categories" / "conf.txt").write_text(".env\n", encoding="utf-8")
        (vendor_dir / "db" / "categories" / "web.txt").write_text("api\n", encoding="utf-8")
        self.artifact_dir = root / "artifacts"

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_scan_rejects_out_of_scope_targets(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AUTOSONGSHU_SCOPE_ALLOWED_HOSTS": '["example.internal"]',
                "AUTOSONGSHU_SCOPE_ALLOW_SUBDOMAINS": "true",
                "AUTOSONGSHU_SCOPE_START_URL": "https://app.example.internal",
                "AUTOSONGSHU_ARTIFACT_DIR": str(self.artifact_dir),
            },
            clear=False,
        ):
            with patch.object(
                self.dirsearch_common,
                "inspect_dependencies",
                return_value={
                    "required": [],
                    "optional": [],
                    "required_available": True,
                    "missing_required": [],
                    "missing_optional": [],
                },
            ):
                with self.assertRaisesRegex(self.dirsearch_common.DirsearchScriptError, "outside the authorized scope"):
                    self.dirsearch_common.scan(
                        skill_dir=self.skill_dir,
                        targets=["https://evil.example.org"],
                    )

    def test_scan_writes_artifacts_and_parses_json_report(self) -> None:
        def fake_run(command: list[str], *, cwd: Path, timeout_sec: int):
            output_path = Path(command[command.index("-o") + 1])
            plain_path = Path(str(output_path).replace("{format}", "plain").replace("{extension}", "txt"))
            json_path = Path(str(output_path).replace("{format}", "json").replace("{extension}", "json"))
            log_path = Path(command[command.index("--log") + 1])
            plain_path.write_text(
                "# Dirsearch started\n200  123B  https://app.example.internal/admin/\n",
                encoding="utf-8",
            )
            json_path.write_text(
                (
                    "{\n"
                    '  "info": {"args": "dirsearch", "time": "2026-03-12 16:00:00"},\n'
                    '  "results": [\n'
                    '    {"url": "https://app.example.internal/admin/", "status": 200, "contentLength": 123, "contentType": "text/html", "redirect": null},\n'
                    '    {"url": "https://app.example.internal/.env", "status": 403, "contentLength": 11, "contentType": "text/plain", "redirect": null}\n'
                    "  ]\n"
                    "}\n"
                ),
                encoding="utf-8",
            )
            log_path.write_text("dirsearch log\n", encoding="utf-8")
            return {
                "ok": True,
                "exit_code": 0,
                "stdout": "200 https://app.example.internal/admin/\n403 https://app.example.internal/.env\n",
                "stderr": "",
                "timed_out": False,
                "duration_sec": 12.5,
                "command": command,
            }

        with patch.dict(
            os.environ,
            {
                "AUTOSONGSHU_SCOPE_ALLOWED_HOSTS": '["example.internal"]',
                "AUTOSONGSHU_SCOPE_ALLOW_SUBDOMAINS": "true",
                "AUTOSONGSHU_SCOPE_START_URL": "https://app.example.internal",
                "AUTOSONGSHU_ARTIFACT_DIR": str(self.artifact_dir),
            },
            clear=False,
        ):
            with patch.object(
                self.dirsearch_common,
                "inspect_dependencies",
                return_value={
                    "required": [],
                    "optional": [],
                    "required_available": True,
                    "missing_required": [],
                    "missing_optional": [],
                },
            ):
                with patch.object(self.dirsearch_common, "run_command", side_effect=fake_run):
                    payload = self.dirsearch_common.scan(
                        skill_dir=self.skill_dir,
                        targets=["/"],
                        wordlist_categories="common,conf,web",
                        threads=8,
                        recursive=False,
                        include_status="200,403",
                    )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["targets"], ["https://app.example.internal/"])
        self.assertEqual(payload["summary"]["result_count"], 2)
        self.assertEqual(payload["summary"]["status_counts"]["200"], 1)
        self.assertEqual(payload["summary"]["status_counts"]["403"], 1)
        self.assertIn("--wordlist-categories", payload["command"])
        self.assertTrue(Path(payload["artifacts"]["plain_path"]).is_file())
        self.assertTrue(Path(payload["artifacts"]["json_path"]).is_file())
        self.assertTrue(Path(payload["artifacts"]["log_path"]).is_file())
        self.assertTrue(Path(payload["artifacts"]["sidecar_path"]).is_file())
        self.assertTrue((self.artifact_dir / "dirsearch-log.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
