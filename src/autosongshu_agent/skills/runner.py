from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..artifacts import ArtifactStore
from ..config import ScopePolicy
from .models import LoadedSkill, SkillScript


class SkillScriptError(RuntimeError):
    pass


def _truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars]


class SkillScriptRunner:
    def __init__(
        self,
        artifacts: ArtifactStore,
        *,
        scope: ScopePolicy | None = None,
        authorization: str = "",
    ) -> None:
        self.artifacts = artifacts
        self.scope = scope
        self.authorization = authorization
        self.repo_root = Path(__file__).resolve().parents[3]
        self._skills_by_name: dict[str, LoadedSkill] = {}
        self._visible_skill_names: set[str] = set()

    def update_skills(
        self,
        loaded_skills: list[LoadedSkill],
        manual_skills: list[LoadedSkill] | None = None,
    ) -> None:
        manual_skills = manual_skills or []
        self._skills_by_name = {
            skill.canonical_name: skill
            for skill in [*loaded_skills, *manual_skills]
            if skill.scripts
        }
        self._visible_skill_names = {
            skill.canonical_name for skill in loaded_skills if skill.scripts
        }

    def describe(self) -> dict[str, Any]:
        skills = sorted(
            self._skills_by_name.values(), key=lambda item: item.name.lower()
        )
        return {
            "available": bool(skills),
            "skill_count": len(skills),
            "script_count": sum(len(skill.scripts) for skill in skills),
            "skills": [self._serialize_skill_overview(skill) for skill in skills],
        }

    def list_scripts(self, skill_name: str = "") -> dict[str, Any]:
        if skill_name.strip():
            skill = self._require_skill(skill_name)
            return {
                "skill": skill.name,
                "directory": skill.directory,
                "scripts_dir": skill.scripts_dir,
                "activation_mode": skill.activation_mode,
                "prompt_visible": skill.canonical_name in self._visible_skill_names,
                "scripts": [self._serialize_script(script) for script in skill.scripts],
            }

        return {
            "skills": [
                {
                    "skill": skill.name,
                    "directory": skill.directory,
                    "scripts_dir": skill.scripts_dir,
                    "activation_mode": skill.activation_mode,
                    "prompt_visible": skill.canonical_name in self._visible_skill_names,
                    "scripts": [
                        self._serialize_script(script) for script in skill.scripts
                    ],
                }
                for skill in sorted(
                    self._skills_by_name.values(), key=lambda item: item.name.lower()
                )
            ],
        }

    def run(
        self,
        *,
        skill_name: str,
        script_name: str,
        args: list[str] | None = None,
        timeout_sec: int = 300,
        max_output_chars: int = 20000,
    ) -> dict[str, Any]:
        if timeout_sec <= 0:
            raise SkillScriptError("timeout_sec must be greater than 0.")

        skill = self._require_skill(skill_name)
        script = self._resolve_script(skill, script_name)
        command = [*self._build_command(script), *(str(item) for item in (args or []))]

        # Save original env for restoration
        _original_env = os.environ.copy()
        environment = _original_env.copy()
        environment["PYTHONUTF8"] = "1"
        environment["AUTOSONGSHU_SKILL_NAME"] = skill.name
        environment["AUTOSONGSHU_SKILL_DIR"] = skill.directory
        environment["AUTOSONGSHU_SKILL_SCRIPTS_DIR"] = skill.scripts_dir or ""
        environment["AUTOSONGSHU_ARTIFACT_DIR"] = str(self.artifacts.session_dir)
        if self.scope is not None:
            environment["AUTOSONGSHU_SCOPE_START_URL"] = self.scope.start_url
            environment["AUTOSONGSHU_SCOPE_ALLOWED_HOSTS"] = json.dumps(
                self.scope.allowed_hosts, ensure_ascii=False
            )
            environment["AUTOSONGSHU_SCOPE_ALLOW_SUBDOMAINS"] = str(
                self.scope.allow_subdomains
            ).lower()
        if self.authorization:
            environment["AUTOSONGSHU_AUTHORIZATION"] = self.authorization

        try:
            started = time.monotonic()
            try:
                completed = subprocess.run(
                    command,
                    cwd=skill.directory,
                    env=environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_sec,
                    check=False,
                )
                duration_sec = round(time.monotonic() - started, 3)
                result = {
                    "ok": completed.returncode == 0,
                    "exit_code": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "timed_out": False,
                    "duration_sec": duration_sec,
                }
            except subprocess.TimeoutExpired as exc:
                duration_sec = round(time.monotonic() - started, 3)
                result = {
                    "ok": False,
                    "exit_code": None,
                    "stdout": exc.stdout or "",
                    "stderr": exc.stderr
                    or f"Command timed out after {timeout_sec} seconds.",
                    "timed_out": True,
                    "duration_sec": duration_sec,
                }

            payload = {
                "ok": result["ok"],
                "exit_code": result["exit_code"],
                "timed_out": result["timed_out"],
                "duration_sec": result["duration_sec"],
                "command": command,
                "cwd": skill.directory,
                "skill": {
                    "name": skill.name,
                    "directory": skill.directory,
                },
                "script": self._serialize_script(script),
                "args": [str(item) for item in (args or [])],
                "stdout": _truncate_text(result["stdout"], max_output_chars),
                "stderr": _truncate_text(result["stderr"], max_output_chars),
            }
            self.artifacts.append_jsonl(
                "skill-scripts.jsonl",
                {
                    "skill": skill.name,
                    "script": script.relative_path,
                    "args": payload["args"],
                    "ok": payload["ok"],
                    "exit_code": payload["exit_code"],
                    "timed_out": payload["timed_out"],
                    "duration_sec": payload["duration_sec"],
                },
            )
            return payload
        finally:
            # Restore original environment variables
            try:
                os.environ.clear()
                os.environ.update(_original_env)
            except Exception:
                pass

    def _require_skill(self, skill_name: str) -> LoadedSkill:
        canonical_name = skill_name.strip().lower()
        if not canonical_name:
            raise SkillScriptError("skill_name must not be empty.")
        skill = self._skills_by_name.get(canonical_name)
        if skill is None:
            available = (
                ", ".join(sorted(skill.name for skill in self._skills_by_name.values()))
                or "none"
            )
            raise SkillScriptError(
                f"Skill '{skill_name}' does not have bundled scripts or is not currently available. "
                f"Available scripted skills: {available}."
            )
        return skill

    def _visible_skills(self) -> list[LoadedSkill]:
        return [
            skill
            for canonical_name, skill in self._skills_by_name.items()
            if canonical_name in self._visible_skill_names
        ]

    def _serialize_skill_overview(self, skill: LoadedSkill) -> dict[str, Any]:
        return {
            "name": skill.name,
            "directory": skill.directory,
            "scripts_dir": skill.scripts_dir,
            "script_count": len(skill.scripts),
            "activation_mode": skill.activation_mode,
            "prompt_visible": skill.canonical_name in self._visible_skill_names,
        }

    def _resolve_script(self, skill: LoadedSkill, script_name: str) -> SkillScript:
        requested = script_name.strip().replace("\\", "/")
        if not requested:
            raise SkillScriptError("script_name must not be empty.")

        by_relative = {script.relative_path.lower(): script for script in skill.scripts}
        direct = by_relative.get(requested.lower())
        if direct is not None:
            return direct

        by_name = [
            script
            for script in skill.scripts
            if script.name.lower() == requested.lower()
        ]
        if len(by_name) == 1:
            return by_name[0]
        if len(by_name) > 1:
            matches = ", ".join(item.relative_path for item in by_name)
            raise SkillScriptError(
                f"Multiple scripts in skill '{skill.name}' match '{script_name}'. Use one of: {matches}."
            )

        available = (
            ", ".join(script.relative_path for script in skill.scripts) or "none"
        )
        raise SkillScriptError(
            f"Script '{script_name}' was not found in skill '{skill.name}'. Available scripts: {available}."
        )

    def _build_command(self, script: SkillScript) -> list[str]:
        script_path = Path(script.absolute_path)
        if script.runner == "python":
            return [str(self._resolve_python_executable()), str(script_path)]
        if script.runner == "powershell":
            shell = shutil.which("powershell") or shutil.which("pwsh")
            if not shell:
                raise SkillScriptError("PowerShell is not available on this system.")
            return [shell, "-ExecutionPolicy", "Bypass", "-File", str(script_path)]
        if script.runner == "cmd":
            shell = shutil.which("cmd.exe") or "cmd.exe"
            return [shell, "/c", str(script_path)]
        if script.runner == "shell":
            shell = shutil.which("bash") or shutil.which("sh")
            if not shell:
                raise SkillScriptError(
                    "No POSIX shell is available to run .sh scripts."
                )
            return [shell, str(script_path)]
        raise SkillScriptError(f"Unsupported script runner: {script.runner}")

    def _resolve_python_executable(self) -> Path:
        scripts_dir = "Scripts" if os.name == "nt" else "bin"
        executable_name = "python.exe" if os.name == "nt" else "python"
        candidate = self.repo_root / ".venv" / scripts_dir / executable_name
        if candidate.is_file():
            return candidate
        return Path(sys.executable).resolve()

    def _serialize_script(self, script: SkillScript) -> dict[str, str]:
        return {
            "name": script.name,
            "relative_path": script.relative_path,
            "absolute_path": script.absolute_path,
            "runner": script.runner,
        }


__all__ = ["SkillScriptRunner", "SkillScriptError"]
