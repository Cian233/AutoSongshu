from __future__ import annotations

import argparse
import json
from pathlib import Path

from dirsearch_common import scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a scoped dirsearch scan for the dirsearch-recon skill.")
    parser.add_argument("--target", action="append", default=[], help="Explicit target URL or host. Repeat for multiple.")
    parser.add_argument("--extensions", default="", help="Comma-separated extension list such as php,html,js.")
    parser.add_argument("--wordlist-categories", default="", help="Comma-separated bundled wordlist categories.")
    parser.add_argument("--wordlist", action="append", default=[], help="Custom wordlist file or directory. Repeat for multiple.")
    parser.add_argument("--threads", type=int, default=10, help="Number of concurrent dirsearch workers.")
    parser.add_argument("--recursive", action="store_true", help="Enable recursive discovery.")
    parser.add_argument("--max-recursion-depth", type=int, default=0, help="Maximum recursion depth when recursive mode is enabled.")
    parser.add_argument("--include-status", default="200-399,401,403", help="Include status codes or ranges.")
    parser.add_argument("--exclude-status", default="", help="Exclude status codes or ranges.")
    parser.add_argument("--follow-redirects", action="store_true", help="Follow HTTP redirects.")
    parser.add_argument("--http-method", default="GET", help="HTTP method to use for requests.")
    parser.add_argument("--header", action="append", default=[], help="Custom HTTP header. Repeat for multiple.")
    parser.add_argument("--cookie", default="", help="Cookie header value.")
    parser.add_argument("--force-extensions", action="store_true", help="Force extensions onto every wordlist entry.")
    parser.add_argument("--async-mode", action="store_true", help="Enable dirsearch async mode.")
    parser.add_argument("--subdirs", default="", help="Comma-separated subdirectories to scan from the base URL.")
    parser.add_argument("--timeout", type=float, default=7.5, help="Per-request timeout in seconds.")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay between requests in seconds.")
    parser.add_argument("--max-rate", type=int, default=0, help="Maximum requests per second. 0 disables the cap.")
    parser.add_argument("--retries", type=int, default=1, help="Retry count for failed requests.")
    parser.add_argument("--max-time", type=int, default=180, help="Maximum dirsearch runtime in seconds. 0 disables the cap.")
    parser.add_argument("--timeout-sec", type=int, default=300, help="Wrapper timeout in seconds.")
    parser.add_argument("--max-output-chars", type=int, default=16000, help="Maximum stdout/stderr/plain preview length.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    payload = scan(
        skill_dir=Path(__file__).resolve().parents[1],
        targets=args.target,
        extensions=args.extensions,
        wordlist_categories=args.wordlist_categories,
        wordlists=args.wordlist,
        threads=args.threads,
        recursive=args.recursive,
        max_recursion_depth=args.max_recursion_depth,
        include_status=args.include_status,
        exclude_status=args.exclude_status,
        follow_redirects=args.follow_redirects,
        http_method=args.http_method,
        headers=args.header,
        cookie=args.cookie,
        force_extensions=args.force_extensions,
        async_mode=args.async_mode,
        subdirs=args.subdirs,
        timeout=args.timeout,
        delay=args.delay,
        max_rate=args.max_rate,
        retries=args.retries,
        max_time=args.max_time,
        timeout_sec=args.timeout_sec,
        max_output_chars=args.max_output_chars,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
