from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_PORTS_PATTERN = re.compile(r"^[0-9,\-]+$")
_TIMING_PATTERN = re.compile(r"^T[0-5]$")
_TARGET_RANGE_PATTERN = re.compile(r"^\d+\.\d+\.\d+\.\d+/\d+$")


class NmapScriptError(RuntimeError):
    pass


@dataclass(slots=True)
class NmapTarget:
    raw: str
    host: str


def load_scope_from_env() -> tuple[list[str], bool]:
    raw_hosts = os.getenv("AUTOSONGSHU_SCOPE_ALLOWED_HOSTS", "[]")
    try:
        parsed_hosts = json.loads(raw_hosts)
    except json.JSONDecodeError as exc:
        raise NmapScriptError(f"Invalid AUTOSONGSHU_SCOPE_ALLOWED_HOSTS payload: {exc}") from exc

    if not isinstance(parsed_hosts, list):
        raise NmapScriptError("AUTOSONGSHU_SCOPE_ALLOWED_HOSTS must be a JSON list.")

    allow_subdomains = os.getenv("AUTOSONGSHU_SCOPE_ALLOW_SUBDOMAINS", "true").strip().lower()
    return [str(item).strip().lower() for item in parsed_hosts if str(item).strip()], allow_subdomains == "true"


def resolve_artifact_dir() -> Path:
    raw_path = os.getenv("AUTOSONGSHU_ARTIFACT_DIR", "").strip()
    if not raw_path:
        raise NmapScriptError("AUTOSONGSHU_ARTIFACT_DIR is not set.")
    artifact_dir = Path(raw_path).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def resolve_nmap_binary(skill_dir: Path) -> tuple[Path, str, Path]:
    vendor_root = skill_dir / "vendor" / "nmap"
    executable_name = "nmap.exe" if os.name == "nt" else "nmap"
    bundled_binary = vendor_root / executable_name
    if bundled_binary.is_file():
        return bundled_binary.resolve(), "bundled", vendor_root.resolve()

    system_binary = shutil.which("nmap")
    if system_binary:
        return Path(system_binary).resolve(), "system", vendor_root.resolve()

    return bundled_binary.resolve(), "missing", vendor_root.resolve()


def describe_binary(skill_dir: Path) -> dict[str, Any]:
    binary_path, source, bundled_root = resolve_nmap_binary(skill_dir)
    return {
        "available": binary_path.is_file(),
        "binary_path": str(binary_path),
        "root_dir": str(binary_path.parent if binary_path.exists() else bundled_root),
        "bundled_root_dir": str(bundled_root),
        "source": source,
        "max_targets_per_scan": 8,
    }


def status(skill_dir: Path) -> dict[str, Any]:
    payload = describe_binary(skill_dir)
    if not payload["available"]:
        return payload

    version_result = run_command([str(payload["binary_path"]), "-V"], cwd=Path(payload["root_dir"]), timeout_sec=20)
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
    ports: str = "",
    top_ports: int = 0,
    service_version: bool = True,
    os_detection: bool = False,
    skip_host_discovery: bool = False,
    timing: str = "T3",
    timeout_sec: int = 300,
    max_output_chars: int = 12000,
) -> dict[str, Any]:
    scanner = describe_binary(skill_dir)
    if not scanner["available"]:
        raise NmapScriptError(f"Bundled nmap binary is not available: {scanner['binary_path']}")

    allowed_hosts, allow_subdomains = load_scope_from_env()
    validated = validate_targets(targets, allowed_hosts=allowed_hosts, allow_subdomains=allow_subdomains)

    if ports and top_ports:
        raise NmapScriptError("Provide either 'ports' or 'top_ports', not both.")
    if ports and not _PORTS_PATTERN.fullmatch(ports.strip()):
        raise NmapScriptError("Ports must contain only digits, commas, and hyphens.")
    if top_ports < 0:
        raise NmapScriptError("top_ports must be greater than or equal to 0.")
    if top_ports > 1000:
        raise NmapScriptError("top_ports must be 1000 or less.")
    if not _TIMING_PATTERN.fullmatch(timing.strip()):
        raise NmapScriptError("timing must be one of T0, T1, T2, T3, T4, or T5.")
    if timeout_sec <= 0:
        raise NmapScriptError("timeout_sec must be greater than 0.")

    artifact_dir = resolve_artifact_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target_slug = slugify("-".join(item.host for item in validated[:2]))
    base_relative = f"nmap/{stamp}-{target_slug}"
    xml_path = artifact_path(artifact_dir, f"{base_relative}.xml")
    text_path = artifact_path(artifact_dir, f"{base_relative}.txt")
    json_path = artifact_path(artifact_dir, f"{base_relative}.json")

    command = [
        str(scanner["binary_path"]),
        "--noninteractive",
        "-oX",
        str(xml_path),
        "-oN",
        str(text_path),
        "--reason",
        f"-{timing.strip()}",
        "-sT",
    ]
    if service_version:
        command.append("-sV")
    if os_detection:
        command.append("-O")
    if skip_host_discovery:
        command.append("-Pn")
    if ports:
        command.extend(["-p", ports.strip()])
    elif top_ports:
        command.extend(["--top-ports", str(top_ports)])
    command.extend(item.host for item in validated)

    result = run_command(command, cwd=Path(scanner["root_dir"]), timeout_sec=timeout_sec)
    parsed_xml, parse_error = parse_xml_output(xml_path)
    payload = {
        "ok": result["ok"],
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "duration_sec": result["duration_sec"],
        "command": result["command"],
        "targets": [item.host for item in validated],
        "target_count": len(validated),
        "ports": ports.strip() or None,
        "top_ports": top_ports or None,
        "service_version": service_version,
        "os_detection": os_detection,
        "skip_host_discovery": skip_host_discovery,
        "timing": timing.strip(),
        "scanner": scanner,
        "artifacts": {
            "xml_path": str(xml_path),
            "text_path": str(text_path),
            "json_path": str(json_path),
            "xml_relative_path": xml_path.relative_to(artifact_dir).as_posix(),
            "text_relative_path": text_path.relative_to(artifact_dir).as_posix(),
            "json_relative_path": json_path.relative_to(artifact_dir).as_posix(),
        },
        "summary": parsed_xml,
        "parse_error": parse_error,
        "stdout": truncate_text(result["stdout"], max_output_chars),
        "stderr": truncate_text(result["stderr"], max_output_chars),
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    append_jsonl(
        artifact_dir / "nmap-log.jsonl",
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "targets": [item.host for item in validated],
            "ok": result["ok"],
            "exit_code": result["exit_code"],
            "duration_sec": result["duration_sec"],
            "xml_path": payload["artifacts"]["xml_relative_path"],
            "text_path": payload["artifacts"]["text_relative_path"],
        },
    )
    return payload


def validate_targets(raw_targets: list[str], *, allowed_hosts: list[str], allow_subdomains: bool) -> list[NmapTarget]:
    validated: list[NmapTarget] = []
    for raw_target in raw_targets:
        if not str(raw_target or "").strip():
            continue
        target = coerce_target(str(raw_target))
        if not is_host_allowed(target.host, allowed_hosts=allowed_hosts, allow_subdomains=allow_subdomains):
            raise NmapScriptError(f"Target host '{target.host}' is outside the authorized scope.")
        validated.append(target)

    if not validated:
        raise NmapScriptError("No valid nmap targets were provided.")
    if len(validated) > 8:
        raise NmapScriptError(f"Too many targets for a single nmap scan: {len(validated)} > 8")
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


def coerce_target(raw_target: str) -> NmapTarget:
    cleaned = str(raw_target or "").strip()
    if not cleaned:
        raise NmapScriptError("Target must not be empty.")
    if _TARGET_RANGE_PATTERN.fullmatch(cleaned):
        raise NmapScriptError(f"CIDR ranges are not allowed for nmap targets: {cleaned}")

    if "://" in cleaned:
        parsed = urlparse(cleaned)
        host = parsed.hostname
    else:
        if "/" in cleaned:
            raise NmapScriptError(f"Unable to extract a hostname from target: {cleaned}")
        parsed = urlparse(f"//{cleaned}")
        host = parsed.hostname

    if not host:
        raise NmapScriptError(f"Unable to extract a hostname from target: {cleaned}")
    return NmapTarget(raw=cleaned, host=host.lower())


def run_command(command: list[str], *, cwd: Path, timeout_sec: int) -> dict[str, Any]:
    started = datetime.now()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd),
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


def parse_xml_output(xml_path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not xml_path.exists():
        return None, f"XML output not found: {xml_path}"

    try:
        root = ET.parse(xml_path).getroot()
    except Exception as exc:
        return None, str(exc)

    hosts: list[dict[str, Any]] = []
    for host_elem in root.findall("./host"):
        status_elem = host_elem.find("./status")
        status_value = status_elem.attrib.get("state") if status_elem is not None else None

        addresses = [
            {"addr": item.attrib.get("addr"), "addrtype": item.attrib.get("addrtype")}
            for item in host_elem.findall("./address")
        ]
        hostnames = [
            item.attrib.get("name")
            for item in host_elem.findall("./hostnames/hostname")
            if item.attrib.get("name")
        ]

        ports: list[dict[str, Any]] = []
        for port_elem in host_elem.findall("./ports/port"):
            state_elem = port_elem.find("./state")
            service_elem = port_elem.find("./service")
            state_text = state_elem.attrib.get("state") if state_elem is not None else None
            if state_text != "open":
                continue
            ports.append(
                {
                    "port": port_elem.attrib.get("portid"),
                    "protocol": port_elem.attrib.get("protocol"),
                    "state": state_text,
                    "reason": state_elem.attrib.get("reason") if state_elem is not None else None,
                    "service": service_elem.attrib.get("name") if service_elem is not None else None,
                    "product": service_elem.attrib.get("product") if service_elem is not None else None,
                    "version": service_elem.attrib.get("version") if service_elem is not None else None,
                    "extra_info": service_elem.attrib.get("extrainfo") if service_elem is not None else None,
                },
            )

        os_matches = [
            {"name": item.attrib.get("name"), "accuracy": item.attrib.get("accuracy")}
            for item in host_elem.findall("./os/osmatch")
        ]
        hosts.append(
            {
                "status": status_value,
                "addresses": addresses,
                "hostnames": hostnames,
                "open_ports_count": len(ports),
                "open_ports": ports,
                "os_matches": os_matches,
            },
        )

    finished_elem = root.find("./runstats/finished")
    hosts_elem = root.find("./runstats/hosts")
    return (
        {
            "scanner": root.attrib.get("scanner"),
            "args": root.attrib.get("args"),
            "start_str": root.attrib.get("startstr"),
            "version": root.attrib.get("version"),
            "xml_output_version": root.attrib.get("xmloutputversion"),
            "hosts": hosts,
            "runstats": {
                "finished_time": finished_elem.attrib.get("timestr") if finished_elem is not None else None,
                "summary": finished_elem.attrib.get("summary") if finished_elem is not None else None,
                "elapsed": finished_elem.attrib.get("elapsed") if finished_elem is not None else None,
                "up": hosts_elem.attrib.get("up") if hosts_elem is not None else None,
                "down": hosts_elem.attrib.get("down") if hosts_elem is not None else None,
                "total": hosts_elem.attrib.get("total") if hosts_elem is not None else None,
            },
        },
        None,
    )


def artifact_path(root_dir: Path, relative_path: str) -> Path:
    target = root_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, default=str))
        file.write("\n")


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return normalized or "scan"


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars]
