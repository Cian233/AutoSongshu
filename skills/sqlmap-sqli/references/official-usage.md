Official sqlmap usage references for this skill:
- README: https://github.com/sqlmapproject/sqlmap/blob/master/README.md
- User manual: https://github.com/sqlmapproject/sqlmap/wiki/Usage

# Common Workflows

## URL-first checks

Use `--target` when the injectable surface is already visible in the URL or when a simple body or cookie override is enough.

- Detection-first: keep `--level 1 --risk 1`
- Focus the test with `--test-parameter` or `--param-filter`
- Add `--banner`, `--current-db`, or `--current-user` only after detection succeeds

## Raw request replay

The official docs support `-r REQUESTFILE` for replaying a captured HTTP request. Prefer this workflow when the target depends on session cookies, custom headers, JSON bodies, or unusual paths.

Use the wrapper's `--request-file` argument instead of `--target` for this mode.

- Save one complete HTTP request from Burp or another proxy to disk
- Keep the request scoped to a single authorized host
- Use `--force-ssl` if the request file is HTTP-formatted but the engagement should stay on HTTPS
- Keep form crawling disabled in this mode to avoid mixing workflows

## Forms and crawl-assisted discovery

The official docs expose `--forms` and `--crawl`. Use them only when there is no obvious injectable query string or request replay file.

- `--forms` for login or search forms reachable from one page
- `--crawl-depth 1` or `2` for small, controlled discovery
- `--crawl-exclude` for logout paths or noisy sections

## Anti-CSRF handling

The official docs expose `--csrf-token`, `--csrf-url`, `--csrf-method`, `--csrf-data`, and `--csrf-retries`.

Use these when requests fail because tokens rotate between requests.

- `--csrf-token` is usually enough when the token lives on the main page
- Add `--csrf-url` when the token must be fetched from a separate endpoint
- Keep the CSRF URL in scope and on the same application unless the operator explicitly states otherwise

## False-positive reduction

The official docs expose `--string`, `--not-string`, `--regexp`, `--code`, `--text-only`, and `--titles`.

Use them when the page is unstable, always returns 200, or reflects user input heavily.

- Prefer `--string` or `--code` when there is a stable success marker
- Prefer `--not-string` when failures have a reliable marker
- Use `--text-only` or `--titles` only when HTML markup causes noisy comparisons

## Transport and stability tuning

The official docs expose `--random-agent`, `--mobile`, `--ignore-code`, `--ignore-redirects`, `--ignore-timeouts`, `--time-sec`, and `--unstable`.

Use them to make testing more reliable, not more aggressive.

- `--random-agent` for naive User-Agent filtering
- `--ignore-code` when the app intentionally throws a known blocking status during probing
- `--time-sec` only when time-based probes are clearly too short or too slow
- `--unstable` when the site intermittently resets TLS or drops connections during longer detection runs

# Guardrails

This skill intentionally does not automate sqlmap's higher-risk areas such as:
- table dumping
- arbitrary SQL execution
- file-system access
- operating-system access
- tamper-script orchestration

If the operator explicitly needs those flows, pause and confirm before widening the skill.
