from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _load_nmap_common():
    module_path = Path(__file__).resolve().parents[1] / "skills" / "nmap-recon" / "scripts" / "nmap_common.py"
    spec = importlib.util.spec_from_file_location("test_nmap_common", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class NmapSkillScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.nmap_common = _load_nmap_common()
        self._temp_dir = tempfile.TemporaryDirectory()
        root = Path(self._temp_dir.name)
        self.skill_dir = root / "nmap-recon"
        vendor_dir = self.skill_dir / "vendor" / "nmap"
        vendor_dir.mkdir(parents=True, exist_ok=True)
        (vendor_dir / "nmap.exe").write_text("fake nmap binary", encoding="utf-8")
        self.artifact_dir = root / "artifacts"

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_scan_rejects_out_of_scope_targets(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AUTOSONGSHU_SCOPE_ALLOWED_HOSTS": '["example.internal"]',
                "AUTOSONGSHU_SCOPE_ALLOW_SUBDOMAINS": "true",
                "AUTOSONGSHU_ARTIFACT_DIR": str(self.artifact_dir),
            },
            clear=False,
        ):
            with self.assertRaisesRegex(self.nmap_common.NmapScriptError, "outside the authorized scope"):
                self.nmap_common.scan(
                    skill_dir=self.skill_dir,
                    targets=["evil.example.org"],
                )

    def test_scan_writes_artifacts_and_parses_open_ports(self) -> None:
        sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
<nmaprun scanner="nmap" args="nmap -sT --top-ports 20 app.example.internal" startstr="Thu Mar 12 16:00:00 2026" version="7.97" xmloutputversion="1.05">
  <host>
    <status state="up" />
    <address addr="10.0.0.10" addrtype="ipv4" />
    <hostnames>
      <hostname name="app.example.internal" />
    </hostnames>
    <ports>
      <port protocol="tcp" portid="80">
        <state state="open" reason="syn-ack" />
        <service name="http" product="nginx" version="1.25.0" />
      </port>
      <port protocol="tcp" portid="443">
        <state state="closed" reason="reset" />
      </port>
    </ports>
  </host>
  <runstats>
    <finished timestr="Thu Mar 12 16:00:10 2026" elapsed="10.00" summary="Nmap done" />
    <hosts up="1" down="0" total="1" />
  </runstats>
</nmaprun>
"""

        def fake_run(command: list[str], *, cwd: Path, timeout_sec: int):
            xml_path = Path(command[command.index("-oX") + 1])
            text_path = Path(command[command.index("-oN") + 1])
            xml_path.write_text(sample_xml, encoding="utf-8")
            text_path.write_text("Nmap scan report for app.example.internal", encoding="utf-8")
            return {
                "ok": True,
                "exit_code": 0,
                "stdout": "scan complete",
                "stderr": "",
                "timed_out": False,
                "duration_sec": 10.0,
                "command": command,
            }

        with patch.dict(
            os.environ,
            {
                "AUTOSONGSHU_SCOPE_ALLOWED_HOSTS": '["example.internal"]',
                "AUTOSONGSHU_SCOPE_ALLOW_SUBDOMAINS": "true",
                "AUTOSONGSHU_ARTIFACT_DIR": str(self.artifact_dir),
            },
            clear=False,
        ):
            with patch.object(self.nmap_common, "run_command", side_effect=fake_run):
                payload = self.nmap_common.scan(
                    skill_dir=self.skill_dir,
                    targets=["https://app.example.internal/login"],
                    top_ports=20,
                    service_version=True,
                    os_detection=False,
                    timing="T3",
                )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["targets"], ["app.example.internal"])
        self.assertEqual(payload["summary"]["hosts"][0]["open_ports_count"], 1)
        self.assertEqual(payload["summary"]["hosts"][0]["open_ports"][0]["service"], "http")
        self.assertIn("--top-ports", payload["command"])
        self.assertIn("-sV", payload["command"])
        self.assertTrue(Path(payload["artifacts"]["xml_path"]).is_file())
        self.assertTrue(Path(payload["artifacts"]["text_path"]).is_file())
        self.assertTrue(Path(payload["artifacts"]["json_path"]).is_file())
        self.assertTrue((self.artifact_dir / "nmap-log.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
