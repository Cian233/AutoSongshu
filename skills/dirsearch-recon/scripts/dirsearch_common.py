from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

_STATUS_CODES_PATTERN = re.compile(r"^[0-9,\-]+$")
_EXTENSIONS_PATTERN = re.compile(r"^[A-Za-z0-9._,\-]*$")
_HTTP_METHOD_PATTERN = re.compile(r"^[A-Za-z]+$")
_TARGET_RANGE_PATTERN = re.compile(r"^\d+\.\d+\.\d+\.\d+/\d+$")
_REQUIRED_MODULES: tuple[tuple[str, str], ...] = (
    ("requests", "requests"),
    ("httpx", "httpx"),
    ("requests_ntlm", "requests-ntlm"),
    ("httpx_ntlm", "httpx-ntlm"),
    ("requests_toolbelt", "requests-toolbelt"),
    ("bs4", "beautifulsoup4"),
    ("colorama", "colorama"),
    ("jinja2", "Jinja2"),
    ("defusedxml", "defusedxml"),
    ("defusedcsv", "defusedcsv"),
    ("mysql.connector", "mysql-connector-python"),
    ("psycopg", "psycopg[binary]"),
)
_OPTIONAL_MODULES: tuple[tuple[str, str, str], ...] = (
    ("socks", "PySocks", "Needed only for SOCKS proxies."),
)


class DirsearchScriptError(RuntimeError):
    pass


@dataclass(slots=True)
class DirsearchTarget:
    raw: str
    url: str
    host: str
    scheme: str


def load_scope_from_env() -> tuple[list[str], bool, str]:
    raw_hosts = os.getenv("AUTOSONGSHU_SCOPE_ALLOWED_HOSTS", "[]")
    try:
        parsed_hosts = json.loads(raw_hosts)
    except json.JSONDecodeError as exc:
        raise DirsearchScriptError(f"Invalid AUTOSONGSHU_SCOPE_ALLOWED_HOSTS payload: {exc}") from exc

    if not isinstance(parsed_hosts, list):
        raise DirsearchScriptError("AUTOSONGSHU_SCOPE_ALLOWED_HOSTS must be a JSON list.")

    allow_subdomains = os.getenv("AUTOSONGSHU_SCOPE_ALLOW_SUBDOMAINS", "true").strip().lower()
    start_url = os.getenv("AUTOSONGSHU_SCOPE_START_URL", "").strip()
    return [str(item).strip().lower() for item in parsed_hosts if str(item).strip()], allow_subdomains == "true", start_url


def resolve_artifact_dir() -> Path:
    raw_path = os.getenv("AUTOSONGSHU_ARTIFACT_DIR", "").strip()
    if not raw_path:
        raise DirsearchScriptError("AUTOSONGSHU_ARTIFACT_DIR is not set.")
    artifact_dir = Path(raw_path).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def resolve_dirsearch_root(skill_dir: Path) -> Path:
    return (skill_dir / "vendor" / "dirsearch").resolve()


def list_wordlist_categories(root_dir: Path) -> list[str]:
    categories_dir = root_dir / "db" / "categories"
    if not categories_dir.is_dir():
        return []

    categories: list[str] = []
    for path in sorted(categories_dir.rglob("*.txt")):
        categories.append(path.relative_to(categories_dir).with_suffix("").as_posix())
    return categories


def describe_installation(skill_dir: Path) -> dict[str, Any]:
    root_dir = resolve_dirsearch_root(skill_dir)
    entrypoint_path = root_dir / "dirsearch.py"
    config_path = root_dir / "config.ini"
    db_dir = root_dir / "db"
    categories_dir = db_dir / "categories"
    dependencies = inspect_dependencies()
    return {
        "available": entrypoint_path.is_file() and config_path.is_file() and db_dir.is_dir(),
        "source": "bundled",
        "root_dir": str(root_dir),
        "entrypoint_path": str(entrypoint_path),
        "config_path": str(config_path),
        "db_dir": str(db_dir),
        "categories_dir": str(categories_dir),
        "wordlist_categories": list_wordlist_categories(root_dir),
        "python_executable": str(Path(sys.executable).resolve()),
        "dependency_check": dependencies,
        "max_targets_per_scan": 4,
        "recommended_default_categories": ["common", "conf", "web"],
    }


def inspect_dependencies() -> dict[str, Any]:
    required: list[dict[str, Any]] = []
    missing_required: list[str] = []
    for module_name, package_name in _REQUIRED_MODULES:
        available = _module_available(module_name)
        required.append(
            {
                "module": module_name,
                "package": package_name,
                "available": available,
            },
        )
        if not available:
            missing_required.append(package_name)

    optional: list[dict[str, Any]] = []
    missing_optional: list[str] = []
    for module_name, package_name, reason in _OPTIONAL_MODULES:
        available = _module_available(module_name)
        optional.append(
            {
                "module": module_name,
                "package": package_name,
                "available": available,
                "reason": reason,
            },
        )
        if not available:
            missing_optional.append(package_name)

    return {
        "required": required,
        "optional": optional,
        "required_available": not missing_required,
        "missing_required": missing_required,
        "missing_optional": missing_optional,
    }


def status(skill_dir: Path) -> dict[str, Any]:
    payload = describe_installation(skill_dir)
    if not payload["available"] or not payload["dependency_check"]["required_available"]:
        return payload

    version_result = run_command(
        [payload["python_executable"], payload["entrypoint_path"], "--version"],
        cwd=Path(payload["root_dir"]),
        timeout_sec=20,
    )
    payload.update(
        {
            "version_ok": version_result["ok"],
            "version_exit_code": version_result["exit_code"],
            "version_output": version_result["stdout"].splitlines()[0] if version_result["stdout"] else "",
            "version_stderr": version_result["stderr"],
        },
    )
    return payload


def scan(
    *,
    skill_dir: Path,
    targets: list[str],
    extensions: str = "",
    wordlist_categories: str = "",
    wordlists: list[str] | None = None,
    threads: int = 10,
    recursive: bool = False,
    max_recursion_depth: int = 0,
    include_status: str = "200-399,401,403",
    exclude_status: str = "",
    follow_redirects: bool = False,
    http_method: str = "GET",
    headers: list[str] | None = None,
    cookie: str = "",
    force_extensions: bool = False,
    async_mode: bool = False,
    subdirs: str = "",
    timeout: float = 7.5,
    delay: float = 0.0,
    max_rate: int = 0,
    retries: int = 1,
    max_time: int = 180,
    timeout_sec: int = 300,
    max_output_chars: int = 16000,
) -> dict[str, Any]:
    installation = describe_installation(skill_dir)
    if not installation["available"]:
        raise DirsearchScriptError(f"Bundled dirsearch source is not available: {installation['entrypoint_path']}")
    if not installation["dependency_check"]["required_available"]:
        missing = ", ".join(installation["dependency_check"]["missing_required"])
        raise DirsearchScriptError(f"dirsearch dependencies are missing from the repo environment: {missing}")

    allowed_hosts, allow_subdomains, start_url = load_scope_from_env()
    validated_targets = validate_targets(
        targets,
        allowed_hosts=allowed_hosts,
        allow_subdomains=allow_subdomains,
        start_url=start_url,
    )

    normalized_extensions = extensions.strip()
    if normalized_extensions and not _EXTENSIONS_PATTERN.fullmatch(normalized_extensions):
        raise DirsearchScriptError("extensions must contain only letters, digits, dots, underscores, commas, and hyphens.")
    if threads <= 0 or threads > 50:
        raise DirsearchScriptError("threads must be between 1 and 50.")
    if max_recursion_depth < 0 or max_recursion_depth > 10:
        raise DirsearchScriptError("max_recursion_depth must be between 0 and 10.")
    if max_recursion_depth and not recursive:
        raise DirsearchScriptError("max_recursion_depth requires recursive=true.")
    if include_status and not _STATUS_CODES_PATTERN.fullmatch(include_status.strip()):
        raise DirsearchScriptError("include_status must contain only digits, commas, and hyphens.")
    if exclude_status and not _STATUS_CODES_PATTERN.fullmatch(exclude_status.strip()):
        raise DirsearchScriptError("exclude_status must contain only digits, commas, and hyphens.")

    normalized_method = http_method.strip().upper()
    if not normalized_method or not _HTTP_METHOD_PATTERN.fullmatch(normalized_method):
        raise DirsearchScriptError("http_method must contain only letters.")
    if timeout <= 0:
        raise DirsearchScriptError("timeout must be greater than 0.")
    if delay < 0:
        raise DirsearchScriptError("delay must be greater than or equal to 0.")
    if max_rate < 0:
        raise DirsearchScriptError("max_rate must be greater than or equal to 0.")
    if retries < 0:
        raise DirsearchScriptError("retries must be greater than or equal to 0.")
    if max_time < 0:
        raise DirsearchScriptError("max_time must be greater than or equal to 0.")
    if timeout_sec <= 0:
        raise DirsearchScriptError("timeout_sec must be greater than 0.")

    available_categories = set(installation["wordlist_categories"])
    normalized_categories = wordlist_categories.strip()
    if not normalized_categories and not (wordlists or []):
        normalized_categories = "common,conf,web"
    category_list = [item.strip() for item in normalized_categories.split(",") if item.strip()]
    unknown_categories = [item for item in category_list if available_categories and item not in available_categories]
    if unknown_categories:
        raise DirsearchScriptError(
            "Unknown wordlist_categories: "
            + ", ".join(unknown_categories)
            + ". Available categories: "
            + ", ".join(sorted(available_categories))
        )

    resolved_wordlists = resolve_wordlists(wordlists or [], skill_dir=skill_dir, root_dir=Path(installation["root_dir"]))

    artifact_dir = resolve_artifact_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target_slug = slugify("-".join(item.host for item in validated_targets[:2]))
    base_relative = f"dirsearch/{stamp}-{target_slug}"
    output_template = artifact_path(artifact_dir, f"{base_relative}-{{format}}.{{extension}}")
    plain_path = artifact_path(artifact_dir, f"{base_relative}-plain.txt")
    json_report_path = artifact_path(artifact_dir, f"{base_relative}-json.json")
    log_path = artifact_path(artifact_dir, f"{base_relative}.log")
    session_dir = ensure_directory(artifact_dir, f"{base_relative}-sessions")

    command = [
        installation["python_executable"],
        installation["entrypoint_path"],
        "--config",
        installation["config_path"],
        "--sessions-dir",
        str(session_dir),
        "--log",
        str(log_path),
        "--no-color",
        "--full-url",
        "-q",
        "-O",
        "plain,json",
        "-o",
        str(output_template),
        "-t",
        str(threads),
        "--timeout",
        str(timeout),
        "--retries",
        str(retries),
        "-m",
        normalized_method,
    ]
    if normalized_extensions:
        command.extend(["-e", normalized_extensions])
    if normalized_categories:
        command.extend(["--wordlist-categories", normalized_categories])
    if resolved_wordlists:
        command.extend(["-w", ",".join(str(path) for path in resolved_wordlists)])
    if include_status:
        command.extend(["-i", include_status.strip()])
    if exclude_status:
        command.extend(["-x", exclude_status.strip()])
    if recursive:
        command.append("-r")
    if max_recursion_depth:
        command.extend(["-R", str(max_recursion_depth)])
    if follow_redirects:
        command.append("-F")
    if cookie.strip():
        command.extend(["--cookie", cookie.strip()])
    if force_extensions:
        command.append("-f")
    if async_mode:
        command.append("--async")
    if subdirs.strip():
        command.extend(["--subdirs", subdirs.strip()])
    if delay:
        command.extend(["--delay", str(delay)])
    if max_rate:
        command.extend(["--max-rate", str(max_rate)])
    if max_time:
        command.extend(["--max-time", str(max_time)])
    for header in headers or []:
        normalized = str(header).strip()
        if normalized:
            command.extend(["-H", normalized])
    for target in validated_targets:
        command.extend(["-u", target.url])

    result = run_command(command, cwd=Path(installation["root_dir"]), timeout_sec=timeout_sec)
    summary, report_error = parse_json_report(json_report_path)
    plain_preview = truncate_text(read_text_if_exists(plain_path), max_output_chars)
    payload = {
        "ok": result["ok"],
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "duration_sec": result["duration_sec"],
        "command": result["command"],
        "targets": [item.url for item in validated_targets],
        "target_hosts": [item.host for item in validated_targets],
        "target_count": len(validated_targets),
        "extensions": normalized_extensions or None,
        "wordlist_categories": category_list or None,
        "wordlists": [str(path) for path in resolved_wordlists] or None,
        "threads": threads,
        "recursive": recursive,
        "max_recursion_depth": max_recursion_depth,
        "include_status": include_status.strip() or None,
        "exclude_status": exclude_status.strip() or None,
        "follow_redirects": follow_redirects,
        "http_method": normalized_method,
        "subdirs": subdirs.strip() or None,
        "force_extensions": force_extensions,
        "async_mode": async_mode,
        "timeout": timeout,
        "delay": delay,
        "max_rate": max_rate,
        "retries": retries,
        "max_time": max_time,
        "installation": installation,
        "artifacts": {
            "output_template": str(output_template),
            "plain_path": str(plain_path),
            "json_path": str(json_report_path),
            "log_path": str(log_path),
            "sessions_dir": str(session_dir),
            "plain_relative_path": plain_path.relative_to(artifact_dir).as_posix(),
            "json_relative_path": json_report_path.relative_to(artifact_dir).as_posix(),
            "log_relative_path": log_path.relative_to(artifact_dir).as_posix(),
            "sessions_relative_path": session_dir.relative_to(artifact_dir).as_posix(),
        },
        "summary": summary,
        "report_error": report_error,
        "plain_preview": plain_preview,
        "stdout": truncate_text(result["stdout"], max_output_chars),
        "stderr": truncate_text(result["stderr"], max_output_chars),
    }
    json_report_sidecar = artifact_path(artifact_dir, f"{base_relative}.json")
    payload["artifacts"]["sidecar_path"] = str(json_report_sidecar)
    payload["artifacts"]["sidecar_relative_path"] = json_report_sidecar.relative_to(artifact_dir).as_posix()
    json_report_sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    append_jsonl(
        artifact_dir / "dirsearch-log.jsonl",
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "targets": [item.url for item in validated_targets],
            "ok": result["ok"],
            "exit_code": result["exit_code"],
            "duration_sec": result["duration_sec"],
            "json_path": payload["artifacts"]["json_relative_path"],
            "plain_path": payload["artifacts"]["plain_relative_path"],
        },
    )
    return payload


def validate_targets(
    raw_targets: list[str],
    *,
    allowed_hosts: list[str],
    allow_subdomains: bool,
    start_url: str,
) -> list[DirsearchTarget]:
    validated: list[DirsearchTarget] = []
    for raw_target in raw_targets:
        if not str(raw_target or "").strip():
            continue
        target = coerce_target(str(raw_target), start_url=start_url)
        if not is_host_allowed(target.host, allowed_hosts=allowed_hosts, allow_subdomains=allow_subdomains):
            raise DirsearchScriptError(f"Target host '{target.host}' is outside the authorized scope.")
        validated.append(target)

    if not validated:
        raise DirsearchScriptError("No valid dirsearch targets were provided.")
    if len(validated) > 4:
        raise DirsearchScriptError(f"Too many targets for a single dirsearch scan: {len(validated)} > 4")
    return validated


def is_host_allowed(host: str | None, *, allowed_hosts: list[str], allow_subdomains: bool) -> bool:
    if not host:
        return False
    candidate = host.strip().lower()
    for pattern in allowed_hosts:
        if pattern.startswith("*."):
            suffix = pattern[2:]
            if candidate == suffix or candidate.endswith(f".{suffix}"):
                return True
            continue
        if candidate == pattern:
            return True
        if allow_subdomains and candidate.endswith(f".{pattern}"):
            return True
    return False


def coerce_target(raw_target: str, *, start_url: str) -> DirsearchTarget:
    cleaned = str(raw_target or "").strip()
    if not cleaned:
        raise DirsearchScriptError("Target must not be empty.")
    if _TARGET_RANGE_PATTERN.fullmatch(cleaned):
        raise DirsearchScriptError(f"CIDR ranges are not allowed for dirsearch targets: {cleaned}")

    if cleaned.startswith("/"):
        if not start_url:
            raise DirsearchScriptError("Relative targets require AUTOSONGSHU_SCOPE_START_URL to be set.")
        parsed_start = urlparse(start_url)
        if not parsed_start.scheme or not parsed_start.netloc or not parsed_start.hostname:
            raise DirsearchScriptError(f"Invalid AUTOSONGSHU_SCOPE_START_URL: {start_url}")
        base = f"{parsed_start.scheme.lower()}://{parsed_start.netloc}"
        normalized_url = urljoin(base, cleaned)
    else:
        candidate = cleaned
        if "://" not in candidate:
            start_scheme = urlparse(start_url).scheme.lower() if start_url else ""
            scheme = start_scheme or "https"
            candidate = f"{scheme}://{candidate}"
        parsed = urlparse(candidate)
        if parsed.username or parsed.password:
            raise DirsearchScriptError("Target URLs must not embed username or password credentials.")
        if parsed.scheme.lower() not in {"http", "https"}:
            raise DirsearchScriptError(f"Unsupported URL scheme for dirsearch target: {parsed.scheme}")
        if not parsed.hostname:
            raise DirsearchScriptError(f"Unable to extract a hostname from target: {cleaned}")
        netloc = parsed.hostname.lower()
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        normalized_url = urlunparse((parsed.scheme.lower(), netloc, parsed.path or "/", "", "", ""))

    parsed_target = urlparse(normalized_url)
    if not parsed_target.hostname:
        raise DirsearchScriptError(f"Unable to extract a hostname from target: {cleaned}")
    return DirsearchTarget(
        raw=cleaned,
        url=normalized_url,
        host=parsed_target.hostname.lower(),
        scheme=parsed_target.scheme.lower(),
    )


def resolve_wordlists(raw_wordlists: list[str], *, skill_dir: Path, root_dir: Path) -> list[Path]:
    resolved: list[Path] = []
    for raw_wordlist in raw_wordlists:
        cleaned = str(raw_wordlist or "").strip()
        if not cleaned:
            continue

        candidate = Path(cleaned)
        possibilities = [candidate]
        if not candidate.is_absolute():
            possibilities.insert(0, root_dir / cleaned)
            possibilities.insert(0, skill_dir / cleaned)

        selected: Path | None = None
        for option in possibilities:
            if option.exists():
                selected = option.resolve()
                break
        if selected is None:
            raise DirsearchScriptError(f"Wordlist path does not exist: {cleaned}")
        resolved.append(selected)
    return resolved


def run_command(command: list[str], *, cwd: Path, timeout_sec: int) -> dict[str, Any]:
    started = datetime.now()
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        duration = round((datetime.now() - started).total_seconds(), 3)
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "timed_out": False,
            "duration_sec": duration,
            "command": command,
        }
    except subprocess.TimeoutExpired as exc:
        duration = round((datetime.now() - started).total_seconds(), 3)
        return {
            "ok": False,
            "exit_code": None,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or f"Command timed out after {timeout_sec} seconds.",
            "timed_out": True,
            "duration_sec": duration,
            "command": command,
        }


def parse_json_report(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, f"JSON report not found: {path}"

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, str(exc)

    if not isinstance(parsed, dict):
        return None, "JSON report payload must be an object."

    results = parsed.get("results")
    if not isinstance(results, list):
        return None, "JSON report is missing a results list."

    status_counts: dict[str, int] = {}
    sample_results: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
        if len(sample_results) < 25:
            sample_results.append(
                {
                    "url": item.get("url"),
                    "status": item.get("status"),
                    "content_length": item.get("contentLength"),
                    "content_type": item.get("contentType"),
                    "redirect": item.get("redirect"),
                },
            )

    return (
        {
            "info": parsed.get("info"),
            "result_count": len(results),
            "status_counts": status_counts,
            "sample_results": sample_results,
        },
        None,
    )


def artifact_path(root_dir: Path, relative_path: str) -> Path:
    target = root_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def ensure_directory(root_dir: Path, relative_path: str) -> Path:
    target = root_dir / relative_path
    target.mkdir(parents=True, exist_ok=True)
    return target


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, default=str))
        file.write("\n")


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return normalized or "scan"


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars]


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False
