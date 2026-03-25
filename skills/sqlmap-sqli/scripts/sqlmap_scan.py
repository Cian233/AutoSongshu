from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlmap_common import scan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a scoped sqlmap scan for the sqlmap-sqli skill.")
    parser.add_argument("--target", action="append", default=[], help="Explicit target URL. Repeat is not supported.")
    parser.add_argument("--request-file", default="", help="Raw HTTP request file for complex replay workflows.")
    parser.add_argument("--method", default="", help="Optional HTTP method override.")
    parser.add_argument("--data", default="", help="Optional request body for POST-style testing.")
    parser.add_argument("--cookie", default="", help="Optional Cookie header value.")
    parser.add_argument("--header", action="append", default=[], help="Extra header in 'Name: Value' format.")
    parser.add_argument("--referer", default="", help="Optional Referer header value.")
    parser.add_argument("--user-agent", default="", help="Optional User-Agent override.")
    parser.add_argument("--random-agent", action="store_true", help="Use a random built-in User-Agent value.")
    parser.add_argument("--mobile", action="store_true", help="Imitate a mobile browser User-Agent.")
    parser.add_argument("--auth-type", default="", help="Optional HTTP auth type.")
    parser.add_argument("--auth-cred", default="", help="Optional HTTP auth credentials.")
    parser.add_argument("--proxy", default="", help="Optional upstream proxy URL.")
    parser.add_argument("--ignore-code", default="", help="Comma-separated HTTP status codes to ignore.")
    parser.add_argument("--ignore-redirects", action="store_true", help="Ignore redirect responses.")
    parser.add_argument("--ignore-timeouts", action="store_true", help="Ignore connection timeout failures.")
    parser.add_argument("--force-ssl", action="store_true", help="Force HTTPS when replaying a raw request file.")
    parser.add_argument("--csrf-token", default="", help="Parameter name that carries an anti-CSRF token.")
    parser.add_argument("--csrf-url", default="", help="Optional URL to fetch before extracting the anti-CSRF token.")
    parser.add_argument("--csrf-method", default="", help="Optional HTTP method for the anti-CSRF token fetch.")
    parser.add_argument("--csrf-data", default="", help="Optional POST body for the anti-CSRF token fetch.")
    parser.add_argument("--csrf-retries", type=int, default=0, help="Retry count for anti-CSRF token retrieval.")
    parser.add_argument("--test-parameter", default="", help="Parameter names to focus on.")
    parser.add_argument("--skip-parameter", default="", help="Parameter names to skip.")
    parser.add_argument("--skip-static", action="store_true", help="Skip parameters that do not appear dynamic.")
    parser.add_argument("--param-exclude", default="", help="Regexp for parameter names to exclude.")
    parser.add_argument("--param-filter", default="", help="Optional parameter place filter such as GET or POST.")
    parser.add_argument("--dbms", default="", help="Force a specific back-end DBMS.")
    parser.add_argument("--level", type=int, default=1, help="sqlmap test level (1-5).")
    parser.add_argument("--risk", type=int, default=1, help="sqlmap test risk (1-3).")
    parser.add_argument("--technique", default="BEUSTQ", help="Technique letters from BEUSTQ.")
    parser.add_argument("--string", default="", help="String that marks a True response.")
    parser.add_argument("--not-string", default="", help="String that marks a False response.")
    parser.add_argument("--regexp", default="", help="Regexp that marks a True response.")
    parser.add_argument("--code", type=int, default=0, help="HTTP status code that marks a True response.")
    parser.add_argument("--text-only", action="store_true", help="Compare only textual content.")
    parser.add_argument("--titles", action="store_true", help="Compare only HTML titles.")
    parser.add_argument("--threads", type=int, default=1, help="Concurrent request count (1-4).")
    parser.add_argument("--delay", type=float, default=0.0, help="Delay in seconds between HTTP requests.")
    parser.add_argument("--timeout", type=float, default=15.0, help="HTTP request timeout in seconds.")
    parser.add_argument("--retries", type=int, default=1, help="Retry count for HTTP timeouts.")
    parser.add_argument("--time-sec", type=int, default=5, help="Delay used for time-based blind tests.")
    parser.add_argument("--forms", action="store_true", help="Parse and test forms on the target URL.")
    parser.add_argument("--crawl-depth", type=int, default=0, help="Website crawl depth (0-3).")
    parser.add_argument("--crawl-exclude", default="", help="Regexp to exclude pages from crawling.")
    parser.add_argument("--smart", action="store_true", help="Enable sqlmap smart testing mode.")
    parser.add_argument("--unstable", action="store_true", help="Adjust sqlmap defaults for unstable connections.")
    parser.add_argument("--flush-session", action="store_true", help="Flush prior sqlmap session files for the target.")
    parser.add_argument("--fresh-queries", action="store_true", help="Ignore cached query results from prior sessions.")
    parser.add_argument("--parse-errors", action="store_true", help="Parse DBMS errors from HTTP responses.")
    parser.add_argument("--fingerprint", action="store_true", help="Perform extended DBMS fingerprinting.")
    parser.add_argument("--banner", action="store_true", help="Retrieve the DBMS banner.")
    parser.add_argument("--current-user", action="store_true", help="Retrieve the DBMS current user.")
    parser.add_argument("--current-db", action="store_true", help="Retrieve the DBMS current database.")
    parser.add_argument("--dbs", action="store_true", help="Enumerate database names.")
    parser.add_argument("--tables", action="store_true", help="Enumerate table names.")
    parser.add_argument("--columns", action="store_true", help="Enumerate column names.")
    parser.add_argument("--database", default="", help="Database name used with --tables or --columns.")
    parser.add_argument("--table", default="", help="Table name used with --columns.")
    parser.add_argument("--column", default="", help="Column name filter used with --columns.")
    parser.add_argument("--exclude-sysdbs", action="store_true", help="Exclude system databases from enumeration.")
    parser.add_argument("--timeout-sec", type=int, default=900, help="Overall process timeout in seconds.")
    parser.add_argument("--max-output-chars", type=int, default=20000, help="Maximum stdout/stderr preview length.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    payload = scan(
        skill_dir=Path(__file__).resolve().parents[1],
        targets=args.target,
        request_file=args.request_file,
        method=args.method,
        data=args.data,
        cookie=args.cookie,
        headers=args.header,
        referer=args.referer,
        user_agent=args.user_agent,
        random_agent=args.random_agent,
        mobile=args.mobile,
        auth_type=args.auth_type,
        auth_cred=args.auth_cred,
        proxy=args.proxy,
        ignore_code=args.ignore_code,
        ignore_redirects=args.ignore_redirects,
        ignore_timeouts=args.ignore_timeouts,
        force_ssl=args.force_ssl,
        csrf_token=args.csrf_token,
        csrf_url=args.csrf_url,
        csrf_method=args.csrf_method,
        csrf_data=args.csrf_data,
        csrf_retries=args.csrf_retries,
        test_parameter=args.test_parameter,
        skip_parameter=args.skip_parameter,
        skip_static=args.skip_static,
        param_exclude=args.param_exclude,
        param_filter=args.param_filter,
        dbms=args.dbms,
        level=args.level,
        risk=args.risk,
        technique=args.technique,
        string=args.string,
        not_string=args.not_string,
        regexp=args.regexp,
        code=args.code,
        text_only=args.text_only,
        titles=args.titles,
        threads=args.threads,
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        time_sec=args.time_sec,
        forms=args.forms,
        crawl_depth=args.crawl_depth,
        crawl_exclude=args.crawl_exclude,
        smart=args.smart,
        unstable=args.unstable,
        flush_session=args.flush_session,
        fresh_queries=args.fresh_queries,
        parse_errors=args.parse_errors,
        fingerprint=args.fingerprint,
        banner=args.banner,
        current_user=args.current_user,
        current_db=args.current_db,
        dbs=args.dbs,
        tables=args.tables,
        columns=args.columns,
        database=args.database,
        table=args.table,
        column=args.column,
        exclude_sysdbs=args.exclude_sysdbs,
        timeout_sec=args.timeout_sec,
        max_output_chars=args.max_output_chars,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
