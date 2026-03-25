---
name: sqlmap-sqli
description: Scoped SQL injection verification with the bundled sqlmap source tree. Use when the operator explicitly asks for sqlmap, SQL injection testing, raw HTTP request replay, form or anti-CSRF-aware injectable parameter verification, or conservative database fingerprinting and schema enumeration on authorized HTTP or HTTPS targets.
activation: auto
requires_tools:
  - list_skill_scripts
  - run_skill_script
---

# Sqlmap SQLi

Use this skill for conservative SQL injection verification on authorized targets.

## Workflow

1. Call `list_skill_scripts(skill_name="sqlmap-sqli")` if you need to confirm the packaged script names.
2. Run `scripts/sqlmap_status.py` first to confirm the vendored source tree is available.
3. Choose one scan workflow:
   - URL-first: use `--target` for a single explicit in-scope URL.
   - Raw replay: use `--request-file` for a captured HTTP request with cookies, custom headers, JSON bodies, or awkward paths.
   - Discovery assist: use `--target` with `--forms` or low `--crawl-depth` only when there is no clear request to replay.
4. Read `references/official-usage.md` when the target needs raw request replay, anti-CSRF handling, response comparison tuning, or crawl guidance.
5. Start conservatively:
   - Keep `level=1` and `risk=1` unless the operator clearly needs broader coverage.
   - Prefer detection and fingerprinting before schema enumeration.
   - Prefer `--test-parameter`, `--skip-static`, `--param-filter`, or `--param-exclude` before raising coverage.
   - Use `--string`, `--not-string`, `--regexp`, `--code`, `--text-only`, or `--titles` when the page is noisy and false positives are possible.
   - Use `--csrf-token` and `--csrf-url` when tokens rotate between requests.
   - If the target is flaky or sqlmap reports SSL connection failures mid-run, first try `threads=1`, then add `--unstable`.
6. Review the saved artifacts under `artifacts/.../sqlmap/` and summarize only evidence-backed results.

## Notes

- The bundled `scripts/` directory is for deterministic helper logic. Use `list_skill_scripts` to inspect it.
- `run_skill_script(skill_name="sqlmap-sqli", script_name="sqlmap_scan.py", args_json='["--target","https://app.example.internal/item.php?id=1","--banner","--current-db"]')` is the preferred scan entrypoint.
- For raw request replay, prefer `run_skill_script(skill_name="sqlmap-sqli", script_name="sqlmap_scan.py", args_json='["--request-file","C:\\\\captures\\\\item-request.txt","--force-ssl","--test-parameter","id"]')`.
- `sqlmap_scan.py` enforces scope, saves a structured sidecar JSON, stores stdout and stderr transcripts, and records a `sqlmap-log.jsonl` audit trail.
- If sqlmap prints `[CRITICAL]` lines such as `can't establish SSL connection`, the wrapper now marks the run as failed even when sqlmap exits with code `0`.
- Prefer this packaged scripted workflow over ad-hoc sandbox exploit code when the task is SQL injection verification, parameter testing, or conservative enumeration.
- The wrapper intentionally exposes detection and limited enumeration only. It does not automate dumping table contents, operating-system takeover, file-system access, or tamper-script chaining.
