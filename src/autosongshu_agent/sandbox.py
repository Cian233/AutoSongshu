from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, ClassVar

from .artifacts import ArtifactStore
from .config import SandboxConfig
from .scope import ScopePolicy


class SandboxError(RuntimeError):
    pass


_PACKAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+")
_USER_ID_SAFE_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")
_MARKDOWN_FENCE_PATTERN = re.compile(r"^\s*```")
_CJK_CHARACTER_PATTERN = re.compile(r"[\u4e00-\u9fff]")
_WORD_PATTERN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_CODE_TOKEN_PATTERN = re.compile(
    r"[=(){}\[\];<>]|"
    r"\b(?:def|class|import|from|return|raise|async|await|if|elif|else|for|while|try|except|with|lambda|"
    r"print|const|let|var|function|SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b",
    re.IGNORECASE,
)
_STRUCTURED_DATA_LINE_PATTERN = re.compile(r"""^['"]?[A-Za-z0-9_.-]+['"]?\s*:\s*\S""")
_PROSE_BULLET_PATTERN = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+)")
_PROSE_PUNCTUATION_PATTERN = re.compile(r"[。！？；：]|[.!?](?:\s|$)")
_PENDING_WORKSPACE_UPDATE_WAIT_SEC = 1.0
_PENDING_WORKSPACE_UPDATE_POLL_SEC = 0.05
_RAW_CONTENT_CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyw",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".mjs",
        ".cjs",
        ".php",
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        ".rb",
        ".pl",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".cc",
        ".cxx",
        ".hpp",
        ".swift",
        ".kt",
        ".kts",
        ".lua",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sql",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".xml",
    }
)
_RAW_CONTENT_CODE_FILENAMES = frozenset({"dockerfile", "makefile", "procfile"})


def _normalize_user_id(user_id: str) -> str:
    normalized = _USER_ID_SAFE_PATTERN.sub("-", str(user_id or "").strip()).strip("-.")
    return normalized or "local-default-user"


def _truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _coerce_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _build_unified_diff(before: str, after: str, relative_path: str, max_chars: int) -> tuple[str, bool]:
    diff = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            n=3,
        )
    )
    return _truncate_text(diff, max_chars)


def _render_numbered_lines(lines: list[str], start_line: int) -> str:
    numbered: list[str] = []
    for offset, raw_line in enumerate(lines):
        line_number = start_line + offset
        stripped = raw_line.rstrip("\r\n")
        suffix = "\n" if raw_line.endswith(("\n", "\r")) else ""
        numbered.append(f"{line_number:>4}: {stripped}{suffix}")
    return "".join(numbered)


def _detect_runtime_hints(stdout: str, stderr: str) -> list[str]:
    text = f"{stdout}\n{stderr}".lower()
    hints: list[str] = []

    if "certificate_verify_failed" in text or "unable to get local issuer certificate" in text:
        hints.append("检测到 TLS 证书校验失败；对已授权目标可在 requests/httpx 中显式使用 verify=False 重试，并记录原因。")
    elif "httpsconnectionpool" in text or "sslerror" in text:
        hints.append("检测到 HTTPS/TLS 连接异常；如果目标证书链不完整或为自签名证书，请优先排查 verify/证书问题。")

    if "nameresolutionerror" in text or "failed to resolve" in text or "getaddrinfo failed" in text:
        hints.append("检测到 DNS 解析异常；请检查目标域名是否可解析、是否仍在有效期内，或是否需要代理/特定网络环境。")

    if "connecttimeout" in text or "readtimeout" in text or "timed out" in text:
        hints.append("检测到超时；可在脚本中增加 timeout、重试机制，或降低并发。")

    return hints


def _is_code_like_path(path: Path | None, *, language_hint: str | None = None) -> bool:
    if language_hint:
        return True
    if path is None:
        return False
    return path.suffix.lower() in _RAW_CONTENT_CODE_EXTENSIONS or path.name.lower() in _RAW_CONTENT_CODE_FILENAMES


def _looks_like_natural_language_line(text: str) -> bool:
    stripped = text.strip().strip("`")
    if not stripped:
        return False

    code_token_hits = len(_CODE_TOKEN_PATTERN.findall(stripped))
    if code_token_hits >= 3:
        return False

    cjk_count = len(_CJK_CHARACTER_PATTERN.findall(stripped))
    word_count = len(_WORD_PATTERN.findall(stripped))
    has_sentence_punctuation = bool(_PROSE_PUNCTUATION_PATTERN.search(stripped))
    has_bullet_prefix = bool(_PROSE_BULLET_PATTERN.match(stripped))
    has_heading_punctuation = ":" in stripped or "：" in stripped

    if not (has_sentence_punctuation or has_bullet_prefix or has_heading_punctuation):
        return False

    if has_heading_punctuation and code_token_hits == 0:
        return cjk_count >= 2 or word_count >= 2
    return cjk_count >= 4 or word_count >= 4


def _looks_like_code_line(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped.startswith("#!"):
        return True
    if stripped.startswith(("```", "#", "//", "--", "/*", "*", "<!--", '"""', "'''")):
        return False
    return bool(_CODE_TOKEN_PATTERN.search(stripped) or _STRUCTURED_DATA_LINE_PATTERN.match(stripped))


def _finalize_comment_block(block_stats: dict[str, int], totals: dict[str, int]) -> None:
    if block_stats["lines"] <= 0:
        return
    totals["max_block_lines"] = max(totals["max_block_lines"], block_stats["lines"])
    totals["max_block_chars"] = max(totals["max_block_chars"], block_stats["chars"])
    block_stats["lines"] = 0
    block_stats["chars"] = 0


def _validate_raw_file_content(
    content: str,
    *,
    path: Path | None = None,
    language_hint: str | None = None,
) -> None:
    if not _is_code_like_path(path, language_hint=language_hint):
        return

    normalized = content.lstrip("\ufeff")
    lines = normalized.splitlines()
    non_empty_lines = [line.strip() for line in lines if line.strip()]
    if not non_empty_lines:
        return

    if _MARKDOWN_FENCE_PATTERN.match(non_empty_lines[0]) or _MARKDOWN_FENCE_PATTERN.match(non_empty_lines[-1]):
        raise SandboxError(
            "Sandbox file content must be raw code or raw file text only. Remove the Markdown code fences and resend the file content itself."
        )

    suffix = (path.suffix.lower() if path is not None else ".py") or ".py"
    line_comment_prefixes = ("#",) if suffix in {".py", ".pyw", ".sh", ".bash", ".zsh", ".ps1"} else ("#", "//", "--")
    in_triple_quote: str | None = None
    in_block_comment = False
    in_html_comment = False
    totals = {
        "code_lines": 0,
        "comment_prose_lines": 0,
        "comment_prose_chars": 0,
        "max_block_lines": 0,
        "max_block_chars": 0,
    }
    block_stats = {"lines": 0, "chars": 0}

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue

        comment_text: str | None = None

        if in_triple_quote:
            end_index = stripped.find(in_triple_quote)
            if end_index >= 0:
                comment_text = stripped[:end_index].strip()
                in_triple_quote = None
            else:
                comment_text = stripped
        elif in_block_comment:
            end_index = stripped.find("*/")
            if end_index >= 0:
                comment_text = stripped[:end_index].lstrip("*").strip()
                in_block_comment = False
            else:
                comment_text = stripped.lstrip("*").strip()
        elif in_html_comment:
            end_index = stripped.find("-->")
            if end_index >= 0:
                comment_text = stripped[:end_index].strip()
                in_html_comment = False
            else:
                comment_text = stripped
        elif stripped.startswith(('"""', "'''")):
            delimiter = stripped[:3]
            remainder = stripped[3:]
            end_index = remainder.find(delimiter)
            if end_index >= 0:
                comment_text = remainder[:end_index].strip()
            else:
                comment_text = remainder.strip()
                in_triple_quote = delimiter
        elif stripped.startswith("/*"):
            remainder = stripped[2:]
            end_index = remainder.find("*/")
            if end_index >= 0:
                comment_text = remainder[:end_index].strip()
            else:
                comment_text = remainder.strip()
                in_block_comment = True
        elif stripped.startswith("<!--"):
            remainder = stripped[4:]
            end_index = remainder.find("-->")
            if end_index >= 0:
                comment_text = remainder[:end_index].strip()
            else:
                comment_text = remainder.strip()
                in_html_comment = True
        else:
            for prefix in line_comment_prefixes:
                if stripped.startswith(prefix):
                    comment_text = stripped[len(prefix) :].strip()
                    break

        if comment_text is not None:
            if _looks_like_natural_language_line(comment_text):
                block_stats["lines"] += 1
                block_stats["chars"] += len(comment_text)
                totals["comment_prose_lines"] += 1
                totals["comment_prose_chars"] += len(comment_text)
            continue

        _finalize_comment_block(block_stats, totals)

        if _looks_like_code_line(stripped):
            totals["code_lines"] += 1
            continue

        if _looks_like_natural_language_line(stripped):
            raise SandboxError(
                "Sandbox file content must be raw code or raw file text only. Remove the explanatory prose and resend just the file content."
            )

        totals["code_lines"] += 1

    _finalize_comment_block(block_stats, totals)

    if totals["max_block_lines"] >= 10 and totals["max_block_chars"] >= 400:
        raise SandboxError(
            "Sandbox file content contains a large explanation-heavy comment block. Keep comments concise and resend raw code only."
        )

    if (
        totals["comment_prose_lines"] >= totals["code_lines"] + 4
        and totals["comment_prose_chars"] >= 400
    ):
        raise SandboxError(
            "Sandbox file content looks explanation-heavy relative to the code. Remove the reasoning text and resend raw code only."
        )

    if totals["code_lines"] == 0 and totals["comment_prose_lines"] >= 4 and totals["comment_prose_chars"] >= 200:
        raise SandboxError(
            "Sandbox file content contains explanation text but no executable code. Resend the actual file content only."
        )


class PythonSandbox:
    _shared_state_lock: ClassVar[threading.RLock] = threading.RLock()
    _root_locks: ClassVar[dict[str, threading.RLock]] = {}
    _bootstrap_cache: ClassVar[dict[str, tuple[str, tuple[str, ...]]]] = {}
    _pending_workspace_updates: ClassVar[dict[tuple[str, str], dict[str, Any]]] = {}

    def __init__(
        self,
        settings: SandboxConfig,
        scope: ScopePolicy,
        artifacts: ArtifactStore,
        engagement_name: str,
        authorization: str,
        ignore_https_errors: bool = False,
        user_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.scope = scope
        self.artifacts = artifacts
        self.engagement_name = engagement_name
        self.authorization = authorization
        self.ignore_https_errors = ignore_https_errors
        self.user_id = _normalize_user_id(user_id or settings.default_user_id)

        self.root_dir = self._resolve_root_dir(settings.root_subdir)
        self.workspace_dir = self._resolve_in_root(settings.workspace_subdir)
        self.venv_dir = self._resolve_in_root(settings.venv_subdir)
        self.activity_log_path = self.root_dir / "activity.jsonl"
        self.metadata_path = self.root_dir / "metadata.json"
        self.bootstrap_state_path = self.root_dir / "bootstrap-packages.json"
        self._cache_key = str(self.root_dir)
        self._lock = self._lock_for_root(self._cache_key)

        self._ensure_directories()
        self._write_metadata()

    @classmethod
    def _lock_for_root(cls, cache_key: str) -> threading.RLock:
        with cls._shared_state_lock:
            lock = cls._root_locks.get(cache_key)
            if lock is None:
                lock = threading.RLock()
                cls._root_locks[cache_key] = lock
            return lock

    @property
    def python_executable(self) -> Path:
        scripts_dir = "Scripts" if os.name == "nt" else "bin"
        executable_name = "python.exe" if os.name == "nt" else "python"
        return self.venv_dir / scripts_dir / executable_name

    @property
    def scripts_dir(self) -> Path:
        return self.python_executable.parent

    def _resolve_in_session(self, relative_path: str) -> Path:
        session_root = self.artifacts.session_dir.resolve()
        candidate = (session_root / relative_path).resolve()
        if not candidate.is_relative_to(session_root):
            raise SandboxError(f"Sandbox path escapes session artifacts directory: {relative_path}")
        return candidate

    def _resolve_root_dir(self, relative_path: str) -> Path:
        if self.settings.isolation_mode == "session":
            return self._resolve_in_session(relative_path)

        shared_root = Path(self.settings.shared_root_dir).resolve()
        shared_root.mkdir(parents=True, exist_ok=True)
        candidate = (shared_root / self.user_id / relative_path).resolve()
        if not candidate.is_relative_to(shared_root):
            raise SandboxError(f"Sandbox path escapes shared sandbox directory: {relative_path}")
        return candidate

    def _resolve_in_root(self, relative_path: str) -> Path:
        candidate = (self.root_dir / relative_path).resolve()
        if not candidate.is_relative_to(self.root_dir):
            raise SandboxError(f"Sandbox path escapes sandbox root: {relative_path}")
        return candidate

    def _resolve_workspace_path(self, relative_path: str) -> Path:
        normalized = relative_path.strip().replace("\\", "/")
        if not normalized or normalized == ".":
            return self.workspace_dir
        candidate = (self.workspace_dir / normalized).resolve()
        if not candidate.is_relative_to(self.workspace_dir):
            raise SandboxError(f"Sandbox workspace path is invalid: {relative_path}")
        return candidate

    def _ensure_directories(self) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def _workspace_update_key(self, target: Path) -> tuple[str, str]:
        workspace_key = str(self.workspace_dir.resolve())
        relative_key = target.relative_to(self.workspace_dir).as_posix()
        if os.name == "nt":
            workspace_key = workspace_key.lower()
            relative_key = relative_key.lower()
        return workspace_key, relative_key

    def _begin_workspace_update(self, target: Path) -> tuple[str, str]:
        key = self._workspace_update_key(target)
        with self._shared_state_lock:
            record = self._pending_workspace_updates.get(key)
            if record is None:
                record = {"event": threading.Event(), "count": 0}
                self._pending_workspace_updates[key] = record
            record["count"] = int(record.get("count", 0)) + 1
            record["event"].clear()
        return key

    def _finish_workspace_update(self, key: tuple[str, str]) -> None:
        event: threading.Event | None = None
        with self._shared_state_lock:
            record = self._pending_workspace_updates.get(key)
            if record is None:
                return
            remaining = max(int(record.get("count", 1)) - 1, 0)
            if remaining:
                record["count"] = remaining
                return
            self._pending_workspace_updates.pop(key, None)
            pending_event = record.get("event")
            if isinstance(pending_event, threading.Event):
                event = pending_event
        if event is not None:
            event.set()

    def _wait_for_pending_workspace_update(self, target: Path, *, timeout_sec: float = _PENDING_WORKSPACE_UPDATE_WAIT_SEC) -> None:
        deadline = time.monotonic() + max(float(timeout_sec), 0.0)
        settle_deadline = time.monotonic() + _PENDING_WORKSPACE_UPDATE_POLL_SEC
        key = self._workspace_update_key(target)

        while True:
            with self._shared_state_lock:
                record = self._pending_workspace_updates.get(key)
                pending_event = record.get("event") if isinstance(record, dict) else None

            remaining = deadline - time.monotonic()
            if pending_event is None:
                if target.is_file():
                    if time.monotonic() >= settle_deadline:
                        return
                    time.sleep(min(_PENDING_WORKSPACE_UPDATE_POLL_SEC, max(settle_deadline - time.monotonic(), 0.0)))
                    continue
                if remaining <= 0:
                    return
                time.sleep(min(_PENDING_WORKSPACE_UPDATE_POLL_SEC, remaining))
                continue

            if remaining <= 0:
                return
            pending_event.wait(timeout=min(_PENDING_WORKSPACE_UPDATE_POLL_SEC, remaining))

    def _bootstrap_distribution_names(self) -> list[str]:
        names: list[str] = []
        for spec in self.settings.bootstrap_packages:
            normalized = spec.strip()
            if not normalized:
                continue
            matched = _PACKAGE_NAME_PATTERN.match(normalized)
            names.append(matched.group(0) if matched else normalized)
        return names

    def _read_bootstrap_state(self) -> dict[str, Any]:
        if not self.bootstrap_state_path.exists():
            return {}
        try:
            payload = json.loads(self.bootstrap_state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_bootstrap_state(self) -> None:
        payload = {
            "packages": list(self.settings.bootstrap_packages),
            "python_executable": str(self.python_executable),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.bootstrap_state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _bootstrap_state_is_current(self) -> bool:
        payload = self._read_bootstrap_state()
        return (
            payload.get("packages") == list(self.settings.bootstrap_packages)
            and payload.get("python_executable") == str(self.python_executable)
        )

    def _bootstrap_packages_available(self) -> bool:
        package_names = self._bootstrap_distribution_names()
        if not package_names:
            return True
        result = self._run_command(
            [str(self.python_executable), "-m", "pip", "show", *package_names],
            timeout_sec=min(self.settings.bootstrap_timeout_sec, 120),
            cwd=self.root_dir,
        )
        return bool(result["ok"])

    def _install_bootstrap_packages(self) -> None:
        packages = [item.strip() for item in self.settings.bootstrap_packages if item.strip()]
        if not packages:
            return

        uv_path = shutil.which("uv")
        if uv_path:
            command = [
                uv_path,
                "pip",
                "install",
                "--python",
                str(self.python_executable),
                *self._command_index_args(),
                *packages,
            ]
        else:
            command = [
                str(self.python_executable),
                "-m",
                "pip",
                "install",
                *self._command_index_args(),
                *packages,
            ]

        result = self._run_command(
            command,
            timeout_sec=self.settings.bootstrap_timeout_sec,
            cwd=self.root_dir,
        )
        if not result["ok"]:
            raise SandboxError(
                "Failed to install default sandbox packages.\n"
                f"stdout:\n{result['stdout']}\n"
                f"stderr:\n{result['stderr']}"
            )

    def _ensure_bootstrap_packages(self) -> None:
        if not self.settings.bootstrap_packages:
            return

        if self._bootstrap_state_is_current():
            return

        if not self._bootstrap_packages_available():
            self._install_bootstrap_packages()

        self._write_bootstrap_state()

    def _write_metadata(self) -> None:
        payload = {
            "user_id": self.user_id,
            "isolation_mode": self.settings.isolation_mode,
            "engagement_name": self.engagement_name,
            "authorization": self.authorization,
            "start_url": self.scope.start_url,
            "allowed_hosts": self.scope.allowed_hosts,
            "allow_subdomains": self.scope.allow_subdomains,
            "artifact_dir": str(self.artifacts.session_dir),
            "workspace_dir": str(self.workspace_dir),
            "venv_dir": str(self.venv_dir),
            "bootstrap_packages": self.settings.bootstrap_packages,
        }
        self.metadata_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _log_activity(self, kind: str, payload: dict[str, Any]) -> None:
        record = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "kind": kind,
            **payload,
        }
        with self.activity_log_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, default=str))
            file.write("\n")

    def _base_env(self) -> dict[str, str]:
        redacted_markers = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
        env = {
            key: value
            for key, value in os.environ.items()
            if not any(marker in key.upper() for marker in redacted_markers)
        }
        env["PYTHONUTF8"] = "1"
        env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        env["AUTOSONGSHU_SCOPE_START_URL"] = self.scope.start_url
        env["AUTOSONGSHU_SCOPE_ALLOWED_HOSTS"] = json.dumps(self.scope.allowed_hosts, ensure_ascii=False)
        env["AUTOSONGSHU_SCOPE_ALLOW_SUBDOMAINS"] = str(self.scope.allow_subdomains).lower()
        env["AUTOSONGSHU_AUTHORIZATION"] = self.authorization
        env["AUTOSONGSHU_SANDBOX_ROOT"] = str(self.root_dir)
        env["AUTOSONGSHU_SANDBOX_WORKSPACE"] = str(self.workspace_dir)
        env["AUTOSONGSHU_ARTIFACT_DIR"] = str(self.artifacts.session_dir)
        env["AUTOSONGSHU_SANDBOX_IGNORE_HTTPS_ERRORS"] = str(self.ignore_https_errors).lower()

        if self.settings.index_url:
            env.setdefault("UV_INDEX_URL", self.settings.index_url)
            env.setdefault("PIP_INDEX_URL", self.settings.index_url)

        if self.scripts_dir.exists():
            current_path = env.get("PATH", "")
            env["PATH"] = str(self.scripts_dir) + (os.pathsep + current_path if current_path else "")

        return env

    def _command_index_args(self) -> list[str]:
        args: list[str] = []
        if self.settings.index_url:
            args.extend(["--index-url", self.settings.index_url])
        for item in self.settings.extra_index_urls:
            args.extend(["--extra-index-url", item])
        for item in self.settings.trusted_hosts:
            args.extend(["--trusted-host", item])
        return args

    def _run_command(
        self,
        command: list[str],
        *,
        timeout_sec: int,
        cwd: Path | None = None,
        extra_env: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> dict[str, Any]:
        environment = self._base_env()
        if extra_env:
            environment.update({key: str(value) for key, value in extra_env.items()})

        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=str(cwd or self.workspace_dir),
                env=environment,
                input=input_text,
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
                "duration_sec": duration_sec,
                "command": command,
                "cwd": str(cwd or self.workspace_dir),
                "timed_out": False,
            }
        except subprocess.TimeoutExpired as exc:
            duration_sec = round(time.monotonic() - started, 3)
            result = {
                "ok": False,
                "exit_code": None,
                "stdout": _coerce_text(exc.stdout),
                "stderr": _coerce_text(exc.stderr) or f"Command timed out after {timeout_sec} seconds.",
                "duration_sec": duration_sec,
                "command": command,
                "cwd": str(cwd or self.workspace_dir),
                "timed_out": True,
            }

        self._log_activity(
            "command",
            {
                "command": command,
                "cwd": str(cwd or self.workspace_dir),
                "timeout_sec": timeout_sec,
                "exit_code": result["exit_code"],
                "ok": result["ok"],
                "timed_out": result["timed_out"],
                "duration_sec": result["duration_sec"],
            },
        )
        return result

    def _ensure_bootstrapped(self) -> None:
        with self._lock:
            self._ensure_directories()
            self._write_metadata()
            venv_ready = self.python_executable.exists()
            cache_signature = (
                str(self.python_executable),
                tuple(self.settings.bootstrap_packages),
            )
            cached_signature = self._bootstrap_cache.get(self._cache_key)

            if venv_ready and cached_signature == cache_signature:
                return

            if not venv_ready:
                uv_path = shutil.which("uv")
                if uv_path:
                    command = [
                        uv_path,
                        "venv",
                        str(self.venv_dir),
                        "--python",
                        sys.executable,
                        "--seed",
                    ]
                else:
                    command = [sys.executable, "-m", "venv", str(self.venv_dir)]

                result = self._run_command(
                    command,
                    timeout_sec=self.settings.bootstrap_timeout_sec,
                    cwd=self.root_dir,
                )
                if not result["ok"] or not self.python_executable.exists():
                    raise SandboxError(
                        "Failed to initialize sandbox virtual environment.\n"
                        f"stdout:\n{result['stdout']}\n"
                        f"stderr:\n{result['stderr']}"
                    )

            self._ensure_bootstrap_packages()
            self._bootstrap_cache[self._cache_key] = cache_signature

    def status(self, include_packages: bool = False, package_limit: int = 50) -> dict[str, Any]:
        with self._lock:
            self._ensure_directories()
            payload: dict[str, Any] = {
                "enabled": self.settings.enabled,
                "user_id": self.user_id,
                "isolation_mode": self.settings.isolation_mode,
                "shared_root_dir": str(Path(self.settings.shared_root_dir).resolve()),
                "artifact_dir": str(self.artifacts.session_dir),
                "root_dir": str(self.root_dir),
                "workspace_dir": str(self.workspace_dir),
                "venv_dir": str(self.venv_dir),
                "python_executable": str(self.python_executable),
                "venv_ready": self.python_executable.exists(),
                "allow_package_install": self.settings.allow_package_install,
                "ignore_https_errors": self.ignore_https_errors,
                "index_url": self.settings.index_url,
                "extra_index_urls": self.settings.extra_index_urls,
                "trusted_hosts": self.settings.trusted_hosts,
                "bootstrap_packages": self.settings.bootstrap_packages,
                "scope": {
                    "start_url": self.scope.start_url,
                    "allowed_hosts": self.scope.allowed_hosts,
                    "allow_subdomains": self.scope.allow_subdomains,
                },
                "usage_hints": [
                    "Use the sandbox for batch payloads, retry loops, custom headers/cookies/sessions, or scripted validation.",
                    "Use write_file to create a new script or intentionally overwrite the full file; do not use edit_file as a disguised full rewrite.",
                    "Any sandbox code or file payload must be raw file content only. Do not wrap it in Markdown fences or mix in narrative explanations or thought-process notes.",
                    "For iterative payload work, inspect the target with read_file(include_line_numbers=True), apply one precise change with edit_file or several ordered precise changes with multiedit_file, and rerun by script_path instead of resending full inline code.",
                    "If HTTPS certificate validation fails on an authorized target, retry explicitly with verify=False and explain why.",
                    "sandbox_run_python ok/process_ok only means the Python process exited with code 0; inspect stdout and stderr to judge the test result.",
                    "Avoid rerunning identical sandbox code unless the inputs or logic changed.",
                ],
            }
            if include_packages and self.python_executable.exists():
                payload["packages"] = self.list_packages(limit=package_limit)["packages"]
            return payload

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        target = self._resolve_workspace_path(path)
        if target == self.workspace_dir:
            raise SandboxError("A file path is required.")
        _validate_raw_file_content(content, path=target)

        update_key = self._begin_workspace_update(target)
        try:
            with self._lock:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                self._log_activity(
                    "write_file",
                    {
                        "path": str(target),
                        "size_bytes": len(content.encode("utf-8")),
                    },
                )
                return {
                    "path": str(target),
                    "relative_path": target.relative_to(self.workspace_dir).as_posix(),
                    "size_bytes": target.stat().st_size,
                }
        finally:
            self._finish_workspace_update(update_key)

    def _apply_precise_edit(
        self,
        original: str,
        *,
        old_text: str = "",
        new_text: str = "",
        replace_all: bool = False,
        start_line: int = 0,
        end_line: int = 0,
        expected_old_text: str = "",
        reject_full_file_replace: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        use_text_replace = bool(old_text)
        use_line_replace = bool(start_line or end_line)
        if use_text_replace == use_line_replace:
            raise SandboxError(
                "Use exactly one edit mode: either provide old_text/new_text, or provide start_line/end_line/new_text."
            )

        updated = original
        edit_mode = "replace_text"
        replaced_count = 0
        spans_entire_file = False

        if use_text_replace:
            occurrences = original.count(old_text)
            if occurrences <= 0:
                raise SandboxError("old_text was not found in the target file.")
            if replace_all:
                updated = original.replace(old_text, new_text)
                replaced_count = occurrences
            else:
                if occurrences != 1:
                    raise SandboxError(
                        f"old_text matched {occurrences} times. Make it unique or set replace_all=true."
                    )
                updated = original.replace(old_text, new_text, 1)
                replaced_count = 1

            spans_entire_file = old_text == original
            if reject_full_file_replace and spans_entire_file and updated != original:
                raise SandboxError(
                    "Refusing to replace the entire file through edit_file. Use write_file for intentional full overwrites, or split the change into precise edit or multiedit operations."
                )
        else:
            if start_line <= 0 or end_line <= 0:
                raise SandboxError("start_line and end_line must both be positive integers.")
            if start_line > end_line:
                raise SandboxError("start_line must be less than or equal to end_line.")

            lines = original.splitlines(keepends=True)
            if lines:
                if end_line > len(lines):
                    raise SandboxError(
                        f"Line range {start_line}-{end_line} is outside the file. The file has {len(lines)} lines."
                    )
                selected_text = "".join(lines[start_line - 1 : end_line])
                if expected_old_text and selected_text != expected_old_text:
                    raise SandboxError("expected_old_text did not match the selected line range.")
                updated = "".join([*lines[: start_line - 1], new_text, *lines[end_line:]])
                spans_entire_file = start_line == 1 and end_line == len(lines)
                if reject_full_file_replace and spans_entire_file and len(lines) > 1 and updated != original:
                    raise SandboxError(
                        "Refusing to replace every line through edit_file. Use write_file for intentional full overwrites, or split the change into smaller line or snippet edits."
                    )
            elif start_line == 1 and end_line == 1:
                if expected_old_text and expected_old_text != "":
                    raise SandboxError("expected_old_text did not match the selected line range.")
                updated = new_text
            else:
                raise SandboxError("Cannot replace a non-existent line range in an empty file.")

            edit_mode = "replace_lines"
            replaced_count = end_line - start_line + 1

        return updated, {
            "edit_mode": edit_mode,
            "replace_all": replace_all,
            "replaced_count": replaced_count,
            "start_line": start_line or None,
            "end_line": end_line or None,
            "used_expected_old_text": bool(expected_old_text),
            "spans_entire_file": spans_entire_file,
        }

    def edit_file(
        self,
        path: str,
        *,
        old_text: str = "",
        new_text: str = "",
        replace_all: bool = False,
        start_line: int = 0,
        end_line: int = 0,
        expected_old_text: str = "",
        max_diff_chars: int = 12000,
    ) -> dict[str, Any]:
        target = self._resolve_workspace_path(path)
        update_key = self._begin_workspace_update(target)
        try:
            with self._lock:
                if not target.is_file():
                    raise SandboxError(f"Sandbox file not found: {path}")

                original = target.read_text(encoding="utf-8", errors="replace")
                updated, edit_metadata = self._apply_precise_edit(
                    original,
                    old_text=old_text,
                    new_text=new_text,
                    replace_all=replace_all,
                    start_line=start_line,
                    end_line=end_line,
                    expected_old_text=expected_old_text,
                    reject_full_file_replace=True,
                )
                _validate_raw_file_content(updated, path=target)

                diff_preview, diff_truncated = _build_unified_diff(
                    original,
                    updated,
                    target.relative_to(self.workspace_dir).as_posix(),
                    max_diff_chars,
                )
                changed = updated != original
                if changed:
                    target.write_text(updated, encoding="utf-8")

                self._log_activity(
                    "edit_file",
                    {
                        "path": str(target),
                        **edit_metadata,
                        "changed": changed,
                    },
                )
                return {
                    "path": str(target),
                    "relative_path": target.relative_to(self.workspace_dir).as_posix(),
                    "size_bytes": target.stat().st_size,
                    **edit_metadata,
                    "changed": changed,
                    "diff": diff_preview,
                    "diff_truncated": diff_truncated,
                }
        finally:
            self._finish_workspace_update(update_key)

    def multiedit_file(
        self,
        path: str,
        *,
        edits: list[dict[str, Any]],
        max_diff_chars: int = 12000,
    ) -> dict[str, Any]:
        target = self._resolve_workspace_path(path)
        update_key = self._begin_workspace_update(target)
        try:
            with self._lock:
                if not target.is_file():
                    raise SandboxError(f"Sandbox file not found: {path}")
                if not edits:
                    raise SandboxError("At least one precise edit is required.")

                original = target.read_text(encoding="utf-8", errors="replace")
                updated = original
                applied_edits: list[dict[str, Any]] = []

                for index, edit in enumerate(edits, start=1):
                    if not isinstance(edit, dict):
                        raise SandboxError(f"Edit #{index} must be a JSON object.")

                    next_updated, edit_metadata = self._apply_precise_edit(
                        updated,
                        old_text=str(edit.get("old_text") or ""),
                        new_text=str(edit.get("new_text") or ""),
                        replace_all=bool(edit.get("replace_all", False)),
                        start_line=int(edit.get("start_line") or 0),
                        end_line=int(edit.get("end_line") or 0),
                        expected_old_text=str(edit.get("expected_old_text") or ""),
                        reject_full_file_replace=True,
                    )
                    _validate_raw_file_content(next_updated, path=target)
                    applied_edits.append(
                        {
                            "index": index,
                            **edit_metadata,
                            "changed": next_updated != updated,
                        }
                    )
                    updated = next_updated

                diff_preview, diff_truncated = _build_unified_diff(
                    original,
                    updated,
                    target.relative_to(self.workspace_dir).as_posix(),
                    max_diff_chars,
                )
                changed = updated != original
                if changed:
                    target.write_text(updated, encoding="utf-8")

                self._log_activity(
                    "multiedit_file",
                    {
                        "path": str(target),
                        "edit_count": len(applied_edits),
                        "changed": changed,
                        "edits": applied_edits,
                    },
                )
                return {
                    "path": str(target),
                    "relative_path": target.relative_to(self.workspace_dir).as_posix(),
                    "size_bytes": target.stat().st_size,
                    "edit_count": len(applied_edits),
                    "changed": changed,
                    "edits": applied_edits,
                    "diff": diff_preview,
                    "diff_truncated": diff_truncated,
                }
        finally:
            self._finish_workspace_update(update_key)

    def read_file(
        self,
        path: str,
        max_chars: int = 12000,
        start_line: int = 0,
        end_line: int = 0,
        include_line_numbers: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            target = self._resolve_workspace_path(path)
            if not target.is_file():
                raise SandboxError(f"Sandbox file not found: {path}")
            content = target.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines(keepends=True)
            total_lines = len(lines)

            if bool(start_line or end_line):
                if start_line <= 0 or end_line <= 0:
                    raise SandboxError("start_line and end_line must both be positive integers.")
                if start_line > end_line:
                    raise SandboxError("start_line must be less than or equal to end_line.")
                if not lines:
                    raise SandboxError("Cannot read a non-existent line range from an empty file.")
                if end_line > total_lines:
                    raise SandboxError(
                        f"Line range {start_line}-{end_line} is outside the file. The file has {total_lines} lines."
                    )
                selected_lines = lines[start_line - 1 : end_line]
                selected_content = "".join(selected_lines)
                selected_start_line = start_line
                selected_end_line = end_line
            else:
                selected_lines = lines
                selected_content = content
                selected_start_line = 1 if total_lines else 0
                selected_end_line = total_lines

            preview, truncated = _truncate_text(selected_content, max_chars)
            payload = {
                "path": str(target),
                "relative_path": target.relative_to(self.workspace_dir).as_posix(),
                "size_bytes": target.stat().st_size,
                "content": preview,
                "truncated": truncated,
                "total_lines": total_lines,
                "selected_start_line": selected_start_line,
                "selected_end_line": selected_end_line,
            }
            if include_line_numbers:
                numbered_preview, numbered_truncated = _truncate_text(
                    _render_numbered_lines(selected_lines, selected_start_line or 1),
                    max_chars,
                )
                payload["numbered_content"] = numbered_preview
                payload["numbered_content_truncated"] = numbered_truncated
            return payload

    def list_files(self, pattern: str = "**/*", limit: int = 200) -> dict[str, Any]:
        with self._lock:
            self._ensure_directories()
            items: list[dict[str, Any]] = []
            for candidate in sorted(self.workspace_dir.glob(pattern)):
                relative_path = candidate.relative_to(self.workspace_dir).as_posix()
                items.append(
                    {
                        "path": relative_path,
                        "type": "directory" if candidate.is_dir() else "file",
                        "size_bytes": None if candidate.is_dir() else candidate.stat().st_size,
                    },
                )
                if len(items) >= limit:
                    break
            return {
                "workspace_dir": str(self.workspace_dir),
                "pattern": pattern,
                "items": items,
                "truncated": len(items) >= limit,
            }

    def list_packages(self, limit: int = 200) -> dict[str, Any]:
        with self._lock:
            self._ensure_bootstrapped()
            result = self._run_command(
                [str(self.python_executable), "-m", "pip", "list", "--format", "json"],
                timeout_sec=min(self.settings.bootstrap_timeout_sec, 120),
            )
            if not result["ok"]:
                raise SandboxError(
                    "Failed to list sandbox packages.\n"
                    f"stdout:\n{result['stdout']}\n"
                    f"stderr:\n{result['stderr']}"
                )
            packages = json.loads(result["stdout"] or "[]")
            if not isinstance(packages, list):
                raise SandboxError("Unexpected package list output from sandbox.")
            return {
                "packages": packages[:limit],
                "total": len(packages),
                "truncated": len(packages) > limit,
            }

    def install_packages(
        self,
        packages: list[str],
        *,
        upgrade: bool = False,
        timeout_sec: int | None = None,
        max_output_chars: int = 20000,
    ) -> dict[str, Any]:
        with self._lock:
            if not self.settings.allow_package_install:
                raise SandboxError("Sandbox package installation is disabled by configuration.")
            packages = [item.strip() for item in packages if item.strip()]
            if not packages:
                raise SandboxError("At least one package specifier is required.")

            self._ensure_bootstrapped()
            timeout_value = timeout_sec or self.settings.install_timeout_sec
            uv_path = shutil.which("uv")
            if uv_path:
                command = [
                    uv_path,
                    "pip",
                    "install",
                    "--python",
                    str(self.python_executable),
                    *self._command_index_args(),
                ]
            else:
                command = [
                    str(self.python_executable),
                    "-m",
                    "pip",
                    "install",
                    *self._command_index_args(),
                ]
            if upgrade:
                command.append("--upgrade")
            command.extend(packages)

            result = self._run_command(command, timeout_sec=timeout_value)
            stdout_preview, stdout_truncated = _truncate_text(result["stdout"], max_output_chars)
            stderr_preview, stderr_truncated = _truncate_text(result["stderr"], max_output_chars)
            if not result["ok"]:
                raise SandboxError(
                    "Sandbox package install failed.\n"
                    f"stdout:\n{stdout_preview}\n"
                    f"stderr:\n{stderr_preview}"
                )
            self._log_activity(
                "install_packages",
                {
                    "packages": packages,
                    "upgrade": upgrade,
                },
            )
            return {
                "packages": packages,
                "upgrade": upgrade,
                "stdout": stdout_preview,
                "stderr": stderr_preview,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "duration_sec": result["duration_sec"],
            }

    def run_python(
        self,
        *,
        code: str = "",
        script_path: str = "",
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: int | None = None,
        max_output_chars: int = 20000,
    ) -> dict[str, Any]:
        if bool(code.strip()) == bool(script_path.strip()):
            raise SandboxError("Provide exactly one of 'code' or 'script_path'.")
        if code.strip():
            _validate_raw_file_content(code, language_hint="python")

        args = [str(item) for item in (args or [])]
        timeout_value = timeout_sec or self.settings.execution_timeout_sec
        created_inline_script = False
        script_file: Path

        if code.strip():
            script_file = self.workspace_dir / ".runs" / f"inline-{int(time.time() * 1000)}.py"
        else:
            script_file = self._resolve_workspace_path(script_path)
            self._wait_for_pending_workspace_update(script_file)

        with self._lock:
            self._ensure_bootstrapped()
            if code.strip():
                inline_dir = self.workspace_dir / ".runs"
                inline_dir.mkdir(parents=True, exist_ok=True)
                script_file.write_text(code, encoding="utf-8")
                created_inline_script = True
            else:
                if not script_file.is_file():
                    raise SandboxError(f"Sandbox script not found: {script_path}")

            command = [str(self.python_executable), str(script_file), *args]
            result = self._run_command(
                command,
                timeout_sec=timeout_value,
                extra_env=env,
            )

            stdout_preview, stdout_truncated = _truncate_text(result["stdout"], max_output_chars)
            stderr_preview, stderr_truncated = _truncate_text(result["stderr"], max_output_chars)
            runtime_hints = _detect_runtime_hints(stdout_preview, stderr_preview)
            self._log_activity(
                "run_python",
                {
                    "script_path": str(script_file),
                    "created_inline_script": created_inline_script,
                    "args": args,
                },
            )
            response_payload = {
                "ok": result["ok"],
                "process_ok": result["ok"],
                "exit_code": result["exit_code"],
                "timed_out": result["timed_out"],
                "duration_sec": result["duration_sec"],
                "script_path": str(script_file),
                "relative_script_path": script_file.relative_to(self.workspace_dir).as_posix(),
                "created_inline_script": created_inline_script,
                "args": args,
                "stdout": stdout_preview,
                "stderr": stderr_preview,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "hints": runtime_hints,
                "note": (
                    "ok/process_ok only means the Python process exited successfully. "
                    "Use stdout and stderr to decide whether the actual test logic succeeded."
                ),
            }
            return response_payload

    def close(self) -> None:
        return None
