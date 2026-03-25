---
name: recon-web
description: Safe first-pass web reconnaissance workflow for browser-assisted pentesting. Use when starting assessment on a web app, mapping exposed pages and flows, collecting passive evidence, or deciding whether deeper scripted discovery such as dirsearch, nmap, or sqlmap is justified.
activation: auto
requires_browser: true
requires_tools:
  - browser_navigate
  - browser_snapshot
  - browser_list_forms
  - browser_list_links
  - browser_extract_route_hints
  - analyze_security_headers
  - http_discover_surface
  - http_request
  - list_skill_scripts
  - record_finding
---

# Recon Web

Use this skill when assessing a web app for the first time.

## Recommended workflow

1. Confirm browser availability with `browser_status`, then navigate to the start page with `browser_navigate`.
2. Capture a broader structured view with `browser_snapshot(max_chars=8000, max_forms=40, max_inputs=40, max_links=120, storage_items=50)`.
3. Enumerate forms with `browser_list_forms(max_forms=40, max_inputs=40)` and links with `browser_list_links(limit=120)`.
4. Call `http_discover_surface(url=..., max_pages=6, max_candidates_per_page=40, max_passive_files=8)` early to perform shallow same-origin discovery, passive file collection, and route/API hint extraction.
5. Call `browser_extract_route_hints(max_html_chars=30000, max_response_bodies=60, max_candidates=120)` to mine the current DOM and recent XHR/fetch/script/document bodies for hidden routes, API endpoints, docs, and SPA navigation targets.
6. Inspect response headers via `analyze_security_headers`.
7. Review cookies, storage, console messages, recent network entries, and recent response bodies.
8. Visit the highest-value same-origin links instead of stopping at the landing page, especially login, registration, account, admin, API explorer, docs, upload, and search flows.
9. Call `list_skill_scripts()` during reconnaissance when the surface still looks incomplete or likely extends beyond what browser and HTTP passive discovery have exposed.
10. If conservative path discovery is justified, prefer `dirsearch-recon` through `run_skill_script(...)` instead of writing ad-hoc sandbox brute-force code.
11. If host-level reachability, port exposure, or service enumeration matters, prefer `nmap-recon` through `run_skill_script(...)` instead of one-off sandbox scanning code.
12. If parameterized URLs, suspicious forms, database error signals, or likely SQLi sinks appear, immediately prefer `sqlmap-sqli` through `run_skill_script(...)` instead of ad-hoc sandbox verification scripts unless the operator explicitly asks for custom exploit development.
13. Record only evidence-backed findings with `record_finding`.

## Scripted follow-ons

- `dirsearch-recon` is the preferred on-demand helper for scoped content discovery. Start with `list_skill_scripts(skill_name="dirsearch-recon")`, then `run_skill_script(skill_name="dirsearch-recon", script_name="dirsearch_status.py")`, then `dirsearch_scan.py`.
- `nmap-recon` is the preferred on-demand helper for scoped host and port discovery. Start with `list_skill_scripts(skill_name="nmap-recon")`, then `run_skill_script(skill_name="nmap-recon", script_name="nmap_status.py")`, then `nmap_scan.py`.
- `sqlmap-sqli` is the preferred helper for scoped SQL injection verification on explicit targets. Start with `list_skill_scripts(skill_name="sqlmap-sqli")`, then `run_skill_script(skill_name="sqlmap-sqli", script_name="sqlmap_status.py")`, then `sqlmap_scan.py`.
- Prefer `http_discover_surface` before moving to heavier scripted discovery so the first pass already includes `robots.txt`, sitemap entries, manifest hints, and shallow same-origin traversal.
- Prefer `browser_extract_route_hints` on SPAs or authenticated flows where the interesting surface lives in inline scripts, network responses, or front-end route tables instead of visible links.

## Notes

- Prefer low-impact checks before active input probes.
- Treat the landing page as the starting point, not the entire reconnaissance surface.
- Use `cdp_send` only when the higher-level browser tools are insufficient.
- Mark heuristic results clearly when a missing defense is inferred instead of proven.
- Prefer a single host or URL before widening scope to multiple targets.

