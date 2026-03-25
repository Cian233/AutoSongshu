from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_sqlmap_common():
    module_path = Path(__file__).resolve().parents[1] / "skills" / "sqlmap-sqli" / "scripts" / "sqlmap_common.py"
    spec = importlib.util.spec_from_file_location("test_sqlmap_common", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SqlmapSkillScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sqlmap_common = _load_sqlmap_common()
        self._temp_dir = tempfile.TemporaryDirectory()
        root = Path(self._temp_dir.name)
        self.skill_dir = root / "sqlmap-sqli"
        vendor_dir = self.skill_dir / "vendor" / "sqlmap"
        (vendor_dir / "lib" / "core").mkdir(parents=True, exist_ok=True)
        (vendor_dir / "sqlmap.py").write_text("print('sqlmap')\n", encoding="utf-8")
        (vendor_dir / "sqlmap.conf").write_text("[Target]\nurl = \n", encoding="utf-8")
        (vendor_dir / "lib" / "core" / "settings.py").write_text(
            'VERSION = "1.10.3.4"\nTYPE = "dev"\n',
            encoding="utf-8",
        )
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
            with self.assertRaisesRegex(self.sqlmap_common.SqlmapScriptError, "outside the authorized scope"):
                self.sqlmap_common.scan(
                    skill_dir=self.skill_dir,
                    targets=["https://evil.example.org/item.php?id=1"],
                )

    def test_scan_writes_artifacts_and_parses_summary(self) -> None:
        def fake_run(command: list[str], *, cwd: Path, timeout_sec: int):
            output_dir = Path(command[command.index("--output-dir") + 1])
            target_output_dir = output_dir / "app.example.internal"
            target_output_dir.mkdir(parents=True, exist_ok=True)
            (target_output_dir / "log").write_text("sqlmap output log\n", encoding="utf-8")
            return {
                "ok": True,
                "exit_code": 0,
                "stdout": (
                    "[INFO] GET parameter 'id' appears to be 'boolean-based blind' injectable\n"
                    "[INFO] parameter 'id' is vulnerable\n"
                    "[INFO] the back-end DBMS is MySQL\n"
                    "[INFO] current user: 'app_user@%'\n"
                    "[INFO] current database: 'appdb'\n"
                    "[INFO] banner: '8.0.36'\n"
                ),
                "stderr": "",
                "timed_out": False,
                "duration_sec": 9.75,
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
            with patch.object(self.sqlmap_common, "run_command", side_effect=fake_run):
                payload = self.sqlmap_common.scan(
                    skill_dir=self.skill_dir,
                    targets=["https://app.example.internal/item.php?id=1"],
                    banner=True,
                    current_db=True,
                    current_user=True,
                    level=1,
                    risk=1,
                )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["targets"], ["https://app.example.internal/item.php?id=1"])
        self.assertEqual(payload["summary"]["dbms"], "MySQL")
        self.assertEqual(payload["summary"]["current_database"], "appdb")
        self.assertEqual(payload["summary"]["current_user"], "app_user@%")
        self.assertEqual(payload["summary"]["injectable_parameters"][0]["parameter"], "id")
        self.assertIn("--batch", payload["command"])
        self.assertIn("--output-dir", payload["command"])
        self.assertTrue(Path(payload["artifacts"]["stdout_path"]).is_file())
        self.assertTrue(Path(payload["artifacts"]["stderr_path"]).is_file())
        self.assertTrue(Path(payload["artifacts"]["result_path"]).is_file())
        self.assertTrue(Path(payload["artifacts"]["output_dir"]).is_dir())
        self.assertTrue((self.artifact_dir / "sqlmap-log.jsonl").is_file())

    def test_scan_supports_request_file_and_official_workflow_flags(self) -> None:
        request_file = self.skill_dir / "captured-request.txt"
        request_file.write_text(
            "POST /login HTTP/1.1\r\n"
            "Host: app.example.internal\r\n"
            "Cookie: session=abc123\r\n"
            "Content-Type: application/x-www-form-urlencoded\r\n"
            "\r\n"
            "username=test&password=test&csrf_token=abc123\r\n",
            encoding="utf-8",
        )

        def fake_run(command: list[str], *, cwd: Path, timeout_sec: int):
            output_dir = Path(command[command.index("--output-dir") + 1])
            target_output_dir = output_dir / "app.example.internal"
            target_output_dir.mkdir(parents=True, exist_ok=True)
            return {
                "ok": True,
                "exit_code": 0,
                "stdout": "[INFO] all tested parameters do not appear to be injectable\n",
                "stderr": "",
                "timed_out": False,
                "duration_sec": 3.5,
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
            with patch.object(self.sqlmap_common, "run_command", side_effect=fake_run):
                payload = self.sqlmap_common.scan(
                    skill_dir=self.skill_dir,
                    targets=[],
                    request_file=str(request_file),
                    force_ssl=True,
                    random_agent=True,
                    unstable=True,
                    ignore_code="401,403",
                    ignore_redirects=True,
                    ignore_timeouts=True,
                    csrf_token="csrf_token",
                    csrf_url="/login",
                    csrf_method="get",
                    csrf_retries=2,
                    test_parameter="username",
                    skip_static=True,
                    param_exclude="csrf",
                    string="Welcome",
                    code=200,
                    text_only=True,
                    time_sec=8,
                    fresh_queries=True,
                    parse_errors=True,
                )

        self.assertEqual(payload["scan_source"], "request_file")
        self.assertEqual(payload["request_file"], str(request_file.resolve()))
        self.assertEqual(payload["targets"], ["https://app.example.internal/login"])
        self.assertTrue(payload["force_ssl"])
        self.assertEqual(payload["csrf_url"], "https://app.example.internal/login")
        self.assertIn("-r", payload["command"])
        self.assertIn(str(request_file.resolve()), payload["command"])
        self.assertIn("--force-ssl", payload["command"])
        self.assertIn("--random-agent", payload["command"])
        self.assertIn("--unstable", payload["command"])
        self.assertIn("--ignore-code", payload["command"])
        self.assertIn("--ignore-redirects", payload["command"])
        self.assertIn("--ignore-timeouts", payload["command"])
        self.assertIn("--csrf-token", payload["command"])
        self.assertIn("--csrf-url", payload["command"])
        self.assertIn("--skip-static", payload["command"])
        self.assertIn("--param-exclude", payload["command"])
        self.assertIn("--string", payload["command"])
        self.assertIn("--code", payload["command"])
        self.assertIn("--text-only", payload["command"])
        self.assertIn("--time-sec", payload["command"])
        self.assertIn("--fresh-queries", payload["command"])
        self.assertIn("--parse-errors", payload["command"])

    def test_scan_rejects_mixing_request_file_with_url_shaping_arguments(self) -> None:
        request_file = self.skill_dir / "captured-request.txt"
        request_file.write_text(
            "GET /items?id=1 HTTP/1.1\r\n"
            "Host: app.example.internal\r\n"
            "\r\n",
            encoding="utf-8",
        )

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
            with self.assertRaisesRegex(self.sqlmap_common.SqlmapScriptError, "request_file mode cannot be combined"):
                self.sqlmap_common.scan(
                    skill_dir=self.skill_dir,
                    targets=[],
                    request_file=str(request_file),
                    forms=True,
                )

    def test_scan_marks_critical_sqlmap_output_as_failed(self) -> None:
        def fake_run(command: list[str], *, cwd: Path, timeout_sec: int):
            output_dir = Path(command[command.index("--output-dir") + 1])
            target_output_dir = output_dir / "app.example.internal"
            target_output_dir.mkdir(parents=True, exist_ok=True)
            return {
                "ok": True,
                "exit_code": 0,
                "stdout": (
                    "[INFO] testing for SQL injection on POST parameter 'username'\n"
                    "[CRITICAL] can't establish SSL connection\n"
                ),
                "stderr": "",
                "timed_out": False,
                "duration_sec": 12.4,
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
            with patch.object(self.sqlmap_common, "run_command", side_effect=fake_run):
                payload = self.sqlmap_common.scan(
                    skill_dir=self.skill_dir,
                    targets=["https://app.example.internal/login"],
                    method="POST",
                    data="username=admin&password=admin",
                )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["exit_code"], 0)
        self.assertEqual(
            payload["summary"]["last_critical_message"],
            "[CRITICAL] can't establish SSL connection",
        )
        self.assertIn(
            "[CRITICAL] can't establish SSL connection",
            payload["summary"]["critical_messages"],
        )


if __name__ == "__main__":
    unittest.main()
