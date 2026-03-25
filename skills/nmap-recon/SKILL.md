---
name: nmap-recon
description: Scoped host-level reconnaissance with the bundled Nmap distribution. Use when the operator explicitly asks for nmap, port scanning, service enumeration, host reachability checks, or low-risk host discovery on authorized targets.
activation: auto
requires_tools:
  - list_skill_scripts
  - run_skill_script
---

# Nmap Recon

Use this skill for low-risk host reconnaissance inside the authorized scope.

## Workflow

1. Call `list_skill_scripts(skill_name="nmap-recon")` if you need to confirm the packaged script names.
2. Run `scripts/nmap_status.py` through `run_skill_script` first to confirm the bundled binary is available.
3. Run `scripts/nmap_scan.py` through `run_skill_script` for actual scans.
4. Scan only explicit in-scope hosts. Prefer a single host unless there is a clear reason to batch.
5. Start conservatively:
   - Use `top_ports` before broad `ports` ranges.
   - Keep `service_version=true` when service fingerprinting matters.
   - Keep `os_detection=false` unless the operator clearly needs OS guesses.
6. Treat `skip_host_discovery=true` as a fallback for hosts that block ping discovery.
7. Review the saved artifacts under `artifacts/.../nmap/` and summarize only evidence-backed conclusions.

## Notes

- The bundled `scripts/` directory is for deterministic helper logic. Use `list_skill_scripts` to inspect it.
- `run_skill_script(skill_name="nmap-recon", script_name="nmap_scan.py", args_json='["--target","app.example.internal","--top-ports","20"]')` is the preferred scan entrypoint.
- `nmap_scan.py` enforces scope, rejects CIDR ranges, and records structured artifacts.
- Results are saved as `.xml`, `.txt`, and `.json`, plus an `nmap-log.jsonl` audit trail.
- If the scan returns `ok=false`, inspect `stderr`, `parse_error`, and the saved text output before concluding the host is unreachable.
- Prefer this packaged scripted workflow over writing one-off sandbox scan code when the task is clearly host or port reconnaissance.
