from __future__ import annotations

import argparse
import json
from pathlib import Path

from nmap_common import scan


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a scoped nmap scan for the nmap-recon skill.")
    parser.add_argument("--target", action="append", default=[], help="Explicit target host or URL. Repeat for multiple.")
    parser.add_argument("--ports", default="", help="Port list or ranges such as 80,443,8000-8100.")
    parser.add_argument("--top-ports", type=int, default=0, help="Scan the top N ports.")
    parser.add_argument("--service-version", type=_parse_bool, default=True, help="Enable service version detection.")
    parser.add_argument("--os-detection", action="store_true", help="Enable OS detection.")
    parser.add_argument("--skip-host-discovery", action="store_true", help="Skip ping discovery and treat hosts as up.")
    parser.add_argument("--timing", default="T3", help="Nmap timing template T0-T5.")
    parser.add_argument("--timeout-sec", type=int, default=300, help="Command timeout in seconds.")
    parser.add_argument("--max-output-chars", type=int, default=12000, help="Maximum stdout/stderr preview length.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    payload = scan(
        skill_dir=Path(__file__).resolve().parents[1],
        targets=args.target,
        ports=args.ports,
        top_ports=args.top_ports,
        service_version=args.service_version,
        os_detection=args.os_detection,
        skip_host_discovery=args.skip_host_discovery,
        timing=args.timing,
        timeout_sec=args.timeout_sec,
        max_output_chars=args.max_output_chars,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
