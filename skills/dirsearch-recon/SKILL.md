---
name: dirsearch-recon
description: Scoped web content discovery with the bundled dirsearch source tree. Use when the operator explicitly asks for dirsearch, directory enumeration, hidden file discovery, content brute forcing, or low-risk path discovery on authorized HTTP or HTTPS targets.
activation: auto
requires_tools:
  - list_skill_scripts
  - run_skill_script
---

# Dirsearch Recon

Use this skill for conservative web path discovery on authorized targets.

## Workflow

1. Call `list_skill_scripts(skill_name="dirsearch-recon")` if you need to confirm the packaged script names.
2. Run `scripts/dirsearch_status.py` first to confirm the vendored source tree and Python dependencies are ready.
3. Run `scripts/dirsearch_scan.py` for actual scans.
4. Target explicit in-scope URLs only. Prefer a single URL unless there is a clear reason to batch.
5. Start conservatively:
   - Keep `threads` low.
   - Prefer `wordlist_categories` before custom large wordlists.
   - Keep recursion disabled unless the operator clearly needs depth.
6. Review the saved artifacts under `artifacts/.../dirsearch/` and summarize only evidence-backed paths.

## Notes

- The bundled `scripts/` directory is for deterministic helper logic. Use `list_skill_scripts` to inspect it.
- `run_skill_script(skill_name="dirsearch-recon", script_name="dirsearch_scan.py", args_json='["--target","https://app.example.internal","--wordlist-categories","common,conf,web"]')` is the preferred scan entrypoint.
- `dirsearch_scan.py` enforces scope, saves plain and JSON reports, and records a `dirsearch-log.jsonl` audit trail.
- If `dependency_check.required_available=false`, install the missing packages into the repo environment before scanning.
- Prefer this packaged scripted workflow over writing ad-hoc sandbox directory brute-force code when the task is clearly path discovery.
