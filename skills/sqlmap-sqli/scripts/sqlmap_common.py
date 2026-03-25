from __future__ import annotations

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

_HEADER_PATTERN = re.compile(r"^[^:\r\n]+:\s*.*$")
_HTTP_METHOD_PATTERN = re.compile(r"^[A-Za-z]+$")
_REQUEST_LINE_PATTERN = re.compile(r"^(?P<method>[A-Za-z]+)\s+(?P<target>\S+)\s+HTTP/\d+(?:\.\d+)?$")
_TARGET_RANGE_PATTERN = re.compile(r"^\d+\.\d+\.\d+\.\d+/\d+$")
_TECHNIQUE_PATTERN = re.compile(r"^[BEUSTQ]+$")
_VERSION_PATTERN = re.compile(r'^VERSION\s*=\s*"([^"]+)"', re.MULTILINE)
_TYPE_PATTERN = re.compile(r'^TYPE\s*=\s*"([^"]+)"', re.MULTILINE)


class SqlmapScriptError(RuntimeError):
    pass


@dataclass(slots=True)
class SqlmapTarget:
    raw: str
    url: str
    host: str
    scheme: str


def load_scope_from_env() -> tuple[list[str], bool, str]:
    raw_hosts = os.getenv("AUTOSONGSHU_SCOPE_ALLOWED_HOSTS", "[]")
    try:
        parsed_hosts = json.loads(raw_hosts)
    except json.JSONDecodeError as exc:
        raise SqlmapScriptError(f"Invalid AUTOSONGSHU_SCOPE_ALLOWED_HOSTS payload: {exc}") from exc

    if not isinstance(parsed_hosts, list):
        raise SqlmapScriptError("AUTOSONGSHU_SCOPE_ALLOWED_HOSTS must be a JSON list.")

    allow_subdomains = os.getenv("AUTOSONGSHU_SCOPE_ALLOW_SUBDOMAINS", "true").strip().lower()
    start_url = os.getenv("AUTOSONGSHU_SCOPE_START_URL", "").strip()
    return [str(item).strip().lower() for item in parsed_hosts if str(item).strip()], allow_subdomains == "true", start_url


def resolve_artifact_dir() -> Path:
    raw_path = os.getenv("AUTOSONGSHU_ARTIFACT_DIR", "").strip()
    if not raw_path:
        raise SqlmapScriptError("AUTOSONGSHU_ARTIFACT_DIR is not set.")
    artifact_dir = Path(raw_path).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def resolve_sqlmap_root(skill_dir: Path) -> Path:
    return (skill_dir / "vendor" / "sqlmap").resolve()


def describe_installation(skill_dir: Path) -> dict[str, Any]:
    root_dir = resolve_sqlmap_root(skill_dir)
    entrypoint_path = root_dir / "sqlmap.py"
    config_path = root_dir / "sqlmap.conf"
    settings_path = root_dir / "lib" / "core" / "settings.py"
    version = read_version(settings_path)
    return {
        "available": entrypoint_path.is_file() and config_path.is_file() and settings_path.is_file(),
        "source": "bundled",
        "root_dir": str(root_dir),
        "entrypoint_path": str(entrypoint_path),
        "config_path": str(config_path),
        "settings_path": str(settings_path),
        "python_executable": str(Path(sys.executable).resolve()),
        "version": version.get("version"),
        "version_type": version.get("type"),
        "version_string": version.get("version_string"),
        "max_targets_per_scan": 1,
        "recommended_defaults": {
            "level": 1,
            "risk": 1,
            "threads": 1,
            "technique": "BEUSTQ",
        },
    }


def read_version(settings_path: Path) -> dict[str, str | None]:
    if not settings_path.is_file():
        return {"version": None, "type": None, "version_string": None}

    raw = settings_path.read_text(encoding="utf-8", errors="replace")
    version_match = _VERSION_PATTERN.search(raw)
    type_match = _TYPE_PATTERN.search(raw)
    version = version_match.group(1) if version_match else None
    version_type = type_match.group(1) if type_match else None
    version_string = f"{version}#{version_type}" if version and version_type else version
    return {
        "version": version,
        "type": version_type,
        "version_string": version_string,
    }


def status(skill_dir: Path) -> dict[str, Any]:
    payload = describe_installation(skill_dir)
    if not payload["available"]:
        return payload

    dependency_result = run_command(
        [payload["python_executable"], payload["entrypoint_path"], "--dependencies"],
        cwd=Path(payload["root_dir"]),
        timeout_sec=30,
    )
    warnings = [
        line.strip()
        for line in dependency_result["stdout"].splitlines()
        if "[WARNING]" in line
    ]
    payload["dependency_check"] = {
        "startup_ok": dependency_result["ok"],
        "exit_code": dependency_result["exit_code"],
        "timed_out": dependency_result["timed_out"],
        "warning_count": len(warnings),
        "warnings": warnings,
        "stdout_preview": truncate_text(dependency_result["stdout"], 12000),
        "stderr_preview": truncate_text(dependency_result["stderr"], 6000),
        "required_available": True,
        "missing_required": [],
    }
    return payload


def scan(
    *,
    skill_dir: Path,
    targets: list[str],
    request_file: str = "",
    method: str = "",
    data: str = "",
    cookie: str = "",
    headers: list[str] | None = None,
    referer: str = "",
    user_agent: str = "",
    random_agent: bool = False,
    mobile: bool = False,
    auth_type: str = "",
    auth_cred: str = "",
    proxy: str = "",
    ignore_code: str = "",
    ignore_redirects: bool = False,
    ignore_timeouts: bool = False,
    force_ssl: bool = False,
    csrf_token: str = "",
    csrf_url: str = "",
    csrf_method: str = "",
    csrf_data: str = "",
    csrf_retries: int = 0,
    test_parameter: str = "",
    skip_parameter: str = "",
    skip_static: bool = False,
    param_exclude: str = "",
    param_filter: str = "",
    dbms: str = "",
    level: int = 1,
    risk: int = 1,
    technique: str = "BEUSTQ",
    string: str = "",
    not_string: str = "",
    regexp: str = "",
    code: int = 0,
    text_only: bool = False,
    titles: bool = False,
    threads: int = 1,
    delay: float = 0.0,
    timeout: float = 15.0,
    retries: int = 1,
    time_sec: int = 5,
    forms: bool = False,
    crawl_depth: int = 0,
    crawl_exclude: str = "",
    smart: bool = False,
    unstable: bool = False,
    flush_session: bool = False,
    fresh_queries: bool = False,
    parse_errors: bool = False,
    fingerprint: bool = False,
    banner: bool = False,
    current_user: bool = False,
    current_db: bool = False,
    dbs: bool = False,
    tables: bool = False,
    columns: bool = False,
    database: str = "",
    table: str = "",
    column: str = "",
    exclude_sysdbs: bool = False,
    timeout_sec: int = 900,
    max_output_chars: int = 20000,
) -> dict[str, Any]:
    installation = describe_installation(skill_dir)
    if not installation["available"]:
        raise SqlmapScriptError(f"Bundled sqlmap source is not available: {installation['entrypoint_path']}")

    allowed_hosts, allow_subdomains, start_url = load_scope_from_env()
    normalized_request_file = request_file.strip()
    if normalized_request_file:
        request_file_path, target = validate_request_file(
            normalized_request_file,
            allowed_hosts=allowed_hosts,
            allow_subdomains=allow_subdomains,
            start_url=start_url,
            force_ssl=force_ssl,
        )
        reject_request_file_conflicts(
            targets=targets,
            method=method,
            data=data,
            cookie=cookie,
            headers=headers or [],
            referer=referer,
            user_agent=user_agent,
            mobile=mobile,
            auth_type=auth_type,
            auth_cred=auth_cred,
            forms=forms,
            crawl_depth=crawl_depth,
            crawl_exclude=crawl_exclude,
        )
        validated_targets = [target]
    else:
        request_file_path = None
        validated_targets = validate_targets(
            targets,
            allowed_hosts=allowed_hosts,
            allow_subdomains=allow_subdomains,
            start_url=start_url,
        )
        target = validated_targets[0]

    normalized_method = method.strip().upper()
    if normalized_method and not _HTTP_METHOD_PATTERN.fullmatch(normalized_method):
        raise SqlmapScriptError("method must contain only letters.")
    normalized_csrf_method = csrf_method.strip().upper()
    if normalized_csrf_method and not _HTTP_METHOD_PATTERN.fullmatch(normalized_csrf_method):
        raise SqlmapScriptError("csrf_method must contain only letters.")
    if level < 1 or level > 5:
        raise SqlmapScriptError("level must be between 1 and 5.")
    if risk < 1 or risk > 3:
        raise SqlmapScriptError("risk must be between 1 and 3.")
    normalized_technique = technique.strip().upper() or "BEUSTQ"
    if not _TECHNIQUE_PATTERN.fullmatch(normalized_technique):
        raise SqlmapScriptError("technique must contain only characters from BEUSTQ.")
    if threads < 1 or threads > 4:
        raise SqlmapScriptError("threads must be between 1 and 4.")
    if delay < 0:
        raise SqlmapScriptError("delay must be greater than or equal to 0.")
    if timeout <= 0:
        raise SqlmapScriptError("timeout must be greater than 0.")
    if retries < 0 or retries > 10:
        raise SqlmapScriptError("retries must be between 0 and 10.")
    if time_sec < 1 or time_sec > 60:
        raise SqlmapScriptError("time_sec must be between 1 and 60.")
    if crawl_depth < 0 or crawl_depth > 3:
        raise SqlmapScriptError("crawl_depth must be between 0 and 3.")
    if csrf_retries < 0 or csrf_retries > 10:
        raise SqlmapScriptError("csrf_retries must be between 0 and 10.")
    if timeout_sec <= 0:
        raise SqlmapScriptError("timeout_sec must be greater than 0.")
    if code and (code < 100 or code > 599):
        raise SqlmapScriptError("code must be between 100 and 599.")
    if table.strip() and not database.strip():
        raise SqlmapScriptError("database is required when table is provided.")
    if column.strip() and not table.strip():
        raise SqlmapScriptError("table is required when column is provided.")
    for header in headers or []:
        normalized_header = str(header).strip()
        if normalized_header and not _HEADER_PATTERN.fullmatch(normalized_header):
            raise SqlmapScriptError(f"Invalid header format: {header}")

    has_explicit_input = any(
        [
            data.strip(),
            cookie.strip(),
            test_parameter.strip(),
            param_filter.strip(),
        ],
    )
    if (
        request_file_path is None
        and "*" not in target.url
        and not urlparse(target.url).query
        and not forms
        and crawl_depth <= 0
        and not has_explicit_input
    ):
        raise SqlmapScriptError(
            "Target must include a query string, request body, cookie/parameter hint, form parsing, crawl depth, or a '*' injection marker.",
        )

    artifact_dir = resolve_artifact_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target_slug = slugify(target.host)
    base_relative = f"sqlmap/{stamp}-{target_slug}"
    run_dir = ensure_directory(artifact_dir, base_relative)
    output_dir = ensure_directory(run_dir, "output")
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    result_path = run_dir / "result.json"

    command = [
        installation["python_executable"],
        installation["entrypoint_path"],
        "--batch",
        "--disable-coloring",
        "--output-dir",
        str(output_dir),
        "--level",
        str(level),
        "--risk",
        str(risk),
        "--technique",
        normalized_technique,
        "--threads",
        str(threads),
        "--timeout",
        str(timeout),
        "--retries",
        str(retries),
        "--time-sec",
        str(time_sec),
    ]
    if request_file_path is not None:
        command.extend(["-r", str(request_file_path)])
    else:
        command.extend(["-u", target.url])
    if normalized_method:
        command.extend(["--method", normalized_method])
    if data.strip():
        command.extend(["--data", data.strip()])
    if cookie.strip():
        command.extend(["--cookie", cookie.strip()])
    if referer.strip():
        command.extend(["--referer", referer.strip()])
    if user_agent.strip():
        command.extend(["-A", user_agent.strip()])
    if random_agent:
        command.append("--random-agent")
    if mobile:
        command.append("--mobile")
    if auth_type.strip():
        command.extend(["--auth-type", auth_type.strip()])
    if auth_cred.strip():
        command.extend(["--auth-cred", auth_cred.strip()])
    if proxy.strip():
        command.extend(["--proxy", proxy.strip()])
    if ignore_code.strip():
        command.extend(["--ignore-code", ignore_code.strip()])
    if ignore_redirects:
        command.append("--ignore-redirects")
    if ignore_timeouts:
        command.append("--ignore-timeouts")
    if force_ssl:
        command.append("--force-ssl")
    if csrf_token.strip():
        command.extend(["--csrf-token", csrf_token.strip()])
    if csrf_url.strip():
        normalized_csrf_url = validate_scoped_url(
            csrf_url.strip(),
            allowed_hosts=allowed_hosts,
            allow_subdomains=allow_subdomains,
            start_url=target.url,
        )
        command.extend(["--csrf-url", normalized_csrf_url.url])
    else:
        normalized_csrf_url = None
    if normalized_csrf_method:
        command.extend(["--csrf-method", normalized_csrf_method])
    if csrf_data.strip():
        command.extend(["--csrf-data", csrf_data.strip()])
    if csrf_retries:
        command.extend(["--csrf-retries", str(csrf_retries)])
    if test_parameter.strip():
        command.extend(["-p", test_parameter.strip()])
    if skip_parameter.strip():
        command.extend(["--skip", skip_parameter.strip()])
    if skip_static:
        command.append("--skip-static")
    if param_exclude.strip():
        command.extend(["--param-exclude", param_exclude.strip()])
    if param_filter.strip():
        command.extend(["--param-filter", param_filter.strip()])
    if dbms.strip():
        command.extend(["--dbms", dbms.strip()])
    if string.strip():
        command.extend(["--string", string.strip()])
    if not_string.strip():
        command.extend(["--not-string", not_string.strip()])
    if regexp.strip():
        command.extend(["--regexp", regexp.strip()])
    if code:
        command.extend(["--code", str(code)])
    if text_only:
        command.append("--text-only")
    if titles:
        command.append("--titles")
    if delay:
        command.extend(["--delay", str(delay)])
    if forms:
        command.append("--forms")
    if crawl_depth:
        command.extend(["--crawl", str(crawl_depth)])
    if crawl_exclude.strip():
        command.extend(["--crawl-exclude", crawl_exclude.strip()])
    if smart:
        command.append("--smart")
    if unstable:
        command.append("--unstable")
    if flush_session:
        command.append("--flush-session")
    if fresh_queries:
        command.append("--fresh-queries")
    if parse_errors:
        command.append("--parse-errors")
    if fingerprint:
        command.append("--fingerprint")
    if banner:
        command.append("--banner")
    if current_user:
        command.append("--current-user")
    if current_db:
        command.append("--current-db")
    if dbs:
        command.append("--dbs")
    if tables:
        command.append("--tables")
    if columns:
        command.append("--columns")
    if exclude_sysdbs:
        command.append("--exclude-sysdbs")
    if database.strip():
        command.extend(["-D", database.strip()])
    if table.strip():
        command.extend(["-T", table.strip()])
    if column.strip():
        command.extend(["-C", column.strip()])
    for header in headers or []:
        normalized_header = str(header).strip()
        if normalized_header:
            command.extend(["-H", normalized_header])

    result = run_command(command, cwd=Path(installation["root_dir"]), timeout_sec=timeout_sec)
    stdout_path.write_text(result["stdout"], encoding="utf-8")
    stderr_path.write_text(result["stderr"], encoding="utf-8")

    critical_messages = extract_log_messages(result["stdout"], result["stderr"], level="CRITICAL")
    payload = {
        "ok": result["ok"] and not critical_messages,
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "duration_sec": result["duration_sec"],
        "command": result["command"],
        "targets": [target.url],
        "target_hosts": [target.host],
        "target_count": len(validated_targets),
        "scan_source": "request_file" if request_file_path is not None else "url",
        "request_file": str(request_file_path) if request_file_path is not None else None,
        "method": normalized_method or None,
        "data_supplied": bool(data.strip()),
        "cookie_supplied": bool(cookie.strip()),
        "header_count": len([item for item in (headers or []) if str(item).strip()]),
        "referer": referer.strip() or None,
        "random_agent": random_agent,
        "mobile": mobile,
        "auth_type": auth_type.strip() or None,
        "proxy": proxy.strip() or None,
        "ignore_code": ignore_code.strip() or None,
        "ignore_redirects": ignore_redirects,
        "ignore_timeouts": ignore_timeouts,
        "force_ssl": force_ssl,
        "csrf_token": csrf_token.strip() or None,
        "csrf_url": normalized_csrf_url.url if normalized_csrf_url is not None else None,
        "csrf_method": normalized_csrf_method or None,
        "csrf_data_supplied": bool(csrf_data.strip()),
        "csrf_retries": csrf_retries,
        "test_parameter": test_parameter.strip() or None,
        "skip_parameter": skip_parameter.strip() or None,
        "skip_static": skip_static,
        "param_exclude": param_exclude.strip() or None,
        "param_filter": param_filter.strip() or None,
        "dbms": dbms.strip() or None,
        "level": level,
        "risk": risk,
        "technique": normalized_technique,
        "string": string.strip() or None,
        "not_string": not_string.strip() or None,
        "regexp": regexp.strip() or None,
        "code": code or None,
        "text_only": text_only,
        "titles": titles,
        "threads": threads,
        "delay": delay,
        "timeout": timeout,
        "retries": retries,
        "time_sec": time_sec,
        "forms": forms,
        "crawl_depth": crawl_depth,
        "crawl_exclude": crawl_exclude.strip() or None,
        "smart": smart,
        "unstable": unstable,
        "flush_session": flush_session,
        "fresh_queries": fresh_queries,
        "parse_errors": parse_errors,
        "fingerprint": fingerprint,
        "banner": banner,
        "current_user": current_user,
        "current_db": current_db,
        "dbs": dbs,
        "tables": tables,
        "columns": columns,
        "database": database.strip() or None,
        "table": table.strip() or None,
        "column": column.strip() or None,
        "exclude_sysdbs": exclude_sysdbs,
        "installation": installation,
        "artifacts": {
            "run_dir": str(run_dir),
            "output_dir": str(output_dir),
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "result_path": str(result_path),
            "run_relative_path": run_dir.relative_to(artifact_dir).as_posix(),
            "output_relative_path": output_dir.relative_to(artifact_dir).as_posix(),
            "stdout_relative_path": stdout_path.relative_to(artifact_dir).as_posix(),
            "stderr_relative_path": stderr_path.relative_to(artifact_dir).as_posix(),
            "result_relative_path": result_path.relative_to(artifact_dir).as_posix(),
        },
        "summary": summarize_run(result["stdout"], result["stderr"], output_dir),
        "stdout": truncate_text(result["stdout"], max_output_chars),
        "stderr": truncate_text(result["stderr"], max_output_chars),
    }
    payload["summary"]["critical_messages"] = critical_messages
    payload["summary"]["last_critical_message"] = critical_messages[-1] if critical_messages else None
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    append_jsonl(
        artifact_dir / "sqlmap-log.jsonl",
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "target": target.url,
            "ok": payload["ok"],
            "exit_code": result["exit_code"],
            "duration_sec": result["duration_sec"],
            "run_path": payload["artifacts"]["run_relative_path"],
        },
    )
    return payload


def validate_targets(
    raw_targets: list[str],
    *,
    allowed_hosts: list[str],
    allow_subdomains: bool,
    start_url: str,
) -> list[SqlmapTarget]:
    validated: list[SqlmapTarget] = []
    for raw_target in raw_targets:
        if not str(raw_target or "").strip():
            continue
        target = coerce_target(str(raw_target), start_url=start_url)
        if not is_host_allowed(target.host, allowed_hosts=allowed_hosts, allow_subdomains=allow_subdomains):
            raise SqlmapScriptError(f"Target host '{target.host}' is outside the authorized scope.")
        validated.append(target)

    if not validated:
        raise SqlmapScriptError("No valid sqlmap targets were provided.")
    if len(validated) > 1:
        raise SqlmapScriptError("sqlmap scans are limited to a single target per run.")
    return validated


def validate_request_file(
    raw_request_file: str,
    *,
    allowed_hosts: list[str],
    allow_subdomains: bool,
    start_url: str,
    force_ssl: bool,
) -> tuple[Path, SqlmapTarget]:
    path = Path(raw_request_file).expanduser().resolve()
    if not path.is_file():
        raise SqlmapScriptError(f"request_file does not exist: {path}")

    target = parse_request_file_target(path, start_url=start_url, force_ssl=force_ssl)
    if not is_host_allowed(target.host, allowed_hosts=allowed_hosts, allow_subdomains=allow_subdomains):
        raise SqlmapScriptError(f"Target host '{target.host}' from request_file is outside the authorized scope.")
    return path, target


def reject_request_file_conflicts(
    *,
    targets: list[str],
    method: str,
    data: str,
    cookie: str,
    headers: list[str],
    referer: str,
    user_agent: str,
    mobile: bool,
    auth_type: str,
    auth_cred: str,
    forms: bool,
    crawl_depth: int,
    crawl_exclude: str,
) -> None:
    conflicts: list[str] = []
    if any(str(item or "").strip() for item in targets):
        conflicts.append("target")
    if method.strip():
        conflicts.append("method")
    if data.strip():
        conflicts.append("data")
    if cookie.strip():
        conflicts.append("cookie")
    if any(str(item or "").strip() for item in headers):
        conflicts.append("header")
    if referer.strip():
        conflicts.append("referer")
    if user_agent.strip():
        conflicts.append("user_agent")
    if mobile:
        conflicts.append("mobile")
    if auth_type.strip():
        conflicts.append("auth_type")
    if auth_cred.strip():
        conflicts.append("auth_cred")
    if forms:
        conflicts.append("forms")
    if crawl_depth:
        conflicts.append("crawl_depth")
    if crawl_exclude.strip():
        conflicts.append("crawl_exclude")
    if conflicts:
        rendered = ", ".join(conflicts)
        raise SqlmapScriptError(
            f"request_file mode cannot be combined with request-shaping URL workflow arguments: {rendered}",
        )


def validate_scoped_url(
    raw_target: str,
    *,
    allowed_hosts: list[str],
    allow_subdomains: bool,
    start_url: str,
) -> SqlmapTarget:
    target = coerce_target(raw_target, start_url=start_url)
    if not is_host_allowed(target.host, allowed_hosts=allowed_hosts, allow_subdomains=allow_subdomains):
        raise SqlmapScriptError(f"Target host '{target.host}' is outside the authorized scope.")
    return target


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


def parse_request_file_target(request_path: Path, *, start_url: str, force_ssl: bool) -> SqlmapTarget:
    raw_text = request_path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff")
    lines = raw_text.splitlines()
    if not lines:
        raise SqlmapScriptError(f"request_file is empty: {request_path}")

    request_line = ""
    for line in lines:
        candidate = line.strip()
        if candidate:
            request_line = candidate
            break
    if not request_line:
        raise SqlmapScriptError(f"request_file is empty: {request_path}")

    match = _REQUEST_LINE_PATTERN.fullmatch(request_line)
    if not match:
        raise SqlmapScriptError(f"Unable to parse HTTP request line in request_file: {request_path}")

    raw_target = match.group("target").strip()
    if raw_target.lower().startswith(("http://", "https://")):
        target = coerce_target(raw_target, start_url=start_url)
        if force_ssl and target.scheme != "https":
            target = coerce_target(_replace_url_scheme(target.url, "https"), start_url=start_url)
        return target

    host_value = ""
    seen_header = False
    for line in lines[1:]:
        candidate = line.strip()
        if not candidate:
            if seen_header:
                break
            continue
        if ":" not in candidate:
            continue
        seen_header = True
        name, value = candidate.split(":", 1)
        if name.strip().lower() == "host":
            host_value = value.strip()
            break
    if not host_value:
        raise SqlmapScriptError(f"request_file is missing a Host header: {request_path}")

    base_scheme = "https" if force_ssl else (urlparse(start_url).scheme.lower() if start_url else "http")
    if raw_target.startswith("/"):
        candidate_url = f"{base_scheme}://{host_value}{raw_target}"
    else:
        candidate_url = f"{base_scheme}://{host_value}/{raw_target.lstrip('/')}"
    return coerce_target(candidate_url, start_url=start_url)


def coerce_target(raw_target: str, *, start_url: str) -> SqlmapTarget:
    cleaned = str(raw_target or "").strip()
    if not cleaned:
        raise SqlmapScriptError("Target must not be empty.")
    if _TARGET_RANGE_PATTERN.fullmatch(cleaned):
        raise SqlmapScriptError(f"CIDR ranges are not allowed for sqlmap targets: {cleaned}")

    if cleaned.startswith("/"):
        if not start_url:
            raise SqlmapScriptError("Relative targets require AUTOSONGSHU_SCOPE_START_URL to be set.")
        parsed_start = urlparse(start_url)
        if not parsed_start.scheme or not parsed_start.netloc or not parsed_start.hostname:
            raise SqlmapScriptError(f"Invalid AUTOSONGSHU_SCOPE_START_URL: {start_url}")
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
            raise SqlmapScriptError("Target URLs must not embed username or password credentials.")
        if parsed.scheme.lower() not in {"http", "https"}:
            raise SqlmapScriptError(f"Unsupported URL scheme for sqlmap target: {parsed.scheme}")
        if not parsed.hostname:
            raise SqlmapScriptError(f"Unable to extract a hostname from target: {cleaned}")
        netloc = parsed.hostname.lower()
        if parsed.port is not None:
            netloc = f"{netloc}:{parsed.port}"
        normalized_url = urlunparse((parsed.scheme.lower(), netloc, parsed.path or "/", "", parsed.query, ""))

    parsed_target = urlparse(normalized_url)
    if not parsed_target.hostname:
        raise SqlmapScriptError(f"Unable to extract a hostname from target: {cleaned}")
    return SqlmapTarget(
        raw=cleaned,
        url=normalized_url,
        host=parsed_target.hostname.lower(),
        scheme=parsed_target.scheme.lower(),
    )


def _replace_url_scheme(url: str, scheme: str) -> str:
    parsed = urlparse(url)
    return urlunparse((scheme.lower(), parsed.netloc, parsed.path, "", parsed.query, ""))


def summarize_run(stdout: str, stderr: str, output_dir: Path) -> dict[str, Any]:
    combined = "\n".join(item for item in [stdout, stderr] if item)
    injection_patterns = [
        re.compile(r"parameter '([^']+)' appears to be '([^']+)' injectable", re.IGNORECASE),
        re.compile(r"parameter '([^']+)' is vulnerable", re.IGNORECASE),
        re.compile(r"parameter '([^']+)' might be injectable", re.IGNORECASE),
    ]

    injectable_parameters: list[dict[str, str | None]] = []
    seen_parameters: set[tuple[str, str | None]] = set()
    for pattern in injection_patterns:
        for match in pattern.finditer(combined):
            parameter = match.group(1)
            technique = match.group(2) if match.lastindex and match.lastindex > 1 else None
            key = (parameter, technique)
            if key in seen_parameters:
                continue
            seen_parameters.add(key)
            injectable_parameters.append(
                {
                    "parameter": parameter,
                    "technique": technique,
                },
            )

    dbms = _extract_last_match(
        combined,
        [
            re.compile(r"the back-end DBMS is ([^\r\n]+)", re.IGNORECASE),
            re.compile(r"back-end DBMS:\s*([^\r\n]+)", re.IGNORECASE),
        ],
    )
    banner = _extract_last_match(combined, [re.compile(r"banner:\s*'?(.*?)'?$", re.IGNORECASE | re.MULTILINE)])
    current_user = _extract_last_match(combined, [re.compile(r"current user:\s*'?(.*?)'?$", re.IGNORECASE | re.MULTILINE)])
    current_database = _extract_last_match(
        combined,
        [re.compile(r"current database:\s*'?(.*?)'?$", re.IGNORECASE | re.MULTILINE)],
    )

    return {
        "injectable_parameters": injectable_parameters,
        "dbms": dbms,
        "banner": banner,
        "current_user": current_user,
        "current_database": current_database,
        "generated_files": list_relative_files(output_dir),
    }


def extract_log_messages(stdout: str, stderr: str, *, level: str) -> list[str]:
    prefix = f"[{level.upper()}]"
    messages: list[str] = []
    for raw_line in "\n".join(item for item in [stdout, stderr] if item).splitlines():
        if prefix not in raw_line:
            continue
        normalized = raw_line.strip()
        if normalized:
            messages.append(normalized)
    return messages


def _extract_last_match(text: str, patterns: list[re.Pattern[str]]) -> str | None:
    for pattern in patterns:
        matches = pattern.findall(text)
        if not matches:
            continue
        if isinstance(matches[-1], tuple):
            value = matches[-1][0]
        else:
            value = matches[-1]
        normalized = str(value).strip().strip("'").strip('"')
        if normalized:
            return normalized
    return None


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


def ensure_directory(root_dir: Path, relative_path: str) -> Path:
    target = root_dir / relative_path
    target.mkdir(parents=True, exist_ok=True)
    return target


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, default=str))
        file.write("\n")


def list_relative_files(root_dir: Path, *, max_files: int = 200) -> list[str]:
    if not root_dir.exists():
        return []

    files: list[str] = []
    for path in sorted(root_dir.rglob("*")):
        if path.is_dir():
            continue
        files.append(path.relative_to(root_dir).as_posix())
        if len(files) >= max_files:
            break
    return files


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return normalized or "scan"


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars]
