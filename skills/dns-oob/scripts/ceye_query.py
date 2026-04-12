#!/usr/bin/env python3
"""CEYE DNS/HTTP OOB record query script.

Usage:
    ceye_query.py [--type TYPE] [--filter FILTER] [--count N] [--json]

Options:
    --type TYPE     Query type: "dns" or "http". Default: "dns".
    --filter FILTER Subdomain prefix filter (max 20 chars).
    --count N       Max number of records to return. Default: 20.
    --json          Output raw JSON from the API.

Environment:
    CEYE_API_TOKEN  Your CEYE API token (required).

Exit codes:
    0  Success
    1  Error (missing token, network failure, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse


CEYE_API_BASE = "http://api.ceye.io/v1/records"


def query_ceye(
    token: str,
    query_type: str = "dns",
    filter_str: str = "",
    count: int = 20,
) -> dict:
    """Query CEYE API for DNS or HTTP records.

    Args:
        token: CEYE API token.
        query_type: "dns" or "http".
        filter_str: Optional subdomain prefix filter (max 20 chars).
        count: Max records to return.

    Returns:
        Parsed JSON response from the CEYE API.
    """
    params: dict[str, str] = {
        "token": token,
        "type": query_type,
    }
    if filter_str:
        params["filter"] = filter_str[:20]

    url = f"{CEYE_API_BASE}?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", "AutoSongshu-DNSOOB/1.0")

    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def format_result(data: dict, query_type: str) -> str:
    """Format API response into a human-readable summary."""
    meta = data.get("meta", {})
    count = meta.get("count", 0)

    lines = [
        f"CEYE {query_type.upper()} Records",
        f"{'=' * 40}",
        f"Total: {count}",
        f"{'=' * 40}",
    ]

    records = data.get("data", [])
    if not records:
        lines.append("(No records found)")
        return "\n".join(lines)

    for i, record in enumerate(records, 1):
        if query_type == "dns":
            domain = record.get("domain", "")
            rtype = record.get("type", "")
            remote_addr = record.get("remote_addr", "")
            created_at = record.get("created_at", "")[:19]
            lines.append(
                f"\n[{i}] {domain}"
            )
            lines.append(f"    Type: {rtype}  |  From: {remote_addr}  |  At: {created_at}")
        else:
            url = record.get("url", "")
            remote_addr = record.get("remote_addr", "")
            method = record.get("method", "")
            created_at = record.get("created_at", "")[:19]
            lines.append(
                f"\n[{i}] {method} {url}"
            )
            lines.append(f"    From: {remote_addr}  |  At: {created_at}")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query CEYE DNS/HTTP OOB records",
    )
    parser.add_argument(
        "--type",
        choices=["dns", "http"],
        default="dns",
        help="Query type (default: dns)",
    )
    parser.add_argument(
        "--filter",
        default="",
        help="Subdomain prefix filter (max 20 chars)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Max records to return (default: 20)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON",
    )
    args = parser.parse_args()

    token = os.environ.get("CEYE_API_TOKEN", "")
    if not token:
        print(json.dumps({"ok": False, "error": "CEYE_API_TOKEN environment variable is not set"}))
        sys.exit(1)

    try:
        data = query_ceye(
            token=token,
            query_type=args.type,
            filter_str=args.filter,
            count=args.count,
        )
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        print(json.dumps({"ok": False, "error": f"HTTP {e.code}: {body}"}))
        sys.exit(1)
    except urllib.error.URLError as e:
        print(json.dumps({"ok": False, "error": f"Network error: {e.reason}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_result(data, args.type))


if __name__ == "__main__":
    main()
