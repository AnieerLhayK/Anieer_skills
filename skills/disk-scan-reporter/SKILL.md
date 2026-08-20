---
name: disk-scan-reporter
description: Bounded disk-scan reports. Use when Windows storage needs read-only reporting and manual review, not cleanup.
---

# Disk Scan Reporter

Produce metadata-only storage evidence. The scan configuration and audit policy define the boundary; candidates remain candidates for manual review.

## Authority

Read only configured or explicitly supplied roots and their permitted metadata. The only allowed side effect is writing Markdown and JSON reports to policy-approved output roots. Do not broaden a scan to a drive or profile, follow links unless configured, request elevation, alter system/tool settings, or turn a finding into cleanup authority.

## Run

1. Inspect `config/scan_config.json` and its audit policy. Keep roots bounded, file/time budgets enabled, and relative report paths for shared output. Complete when the configuration and output boundary are known.
2. Run `python scripts/audit_guard.py`. A `FAIL` stops the scan. Complete when the audit status is recorded.
3. Run `python scripts/disk_scan.py --config config/scan_config.json`; use its output option only within approved report roots. Complete when the report is written or its failure is reported.
4. Read the generated report's safety audit, coverage, budgets, skipped paths, and categorized errors before ranking candidates. Use [coverage_schema.md](references/coverage_schema.md) and [report_schema.json](references/report_schema.json) for machine interpretation. Treat budget exhaustion as partial coverage, not a reason to broaden scope or privileges. Complete when its coverage state is classified.

## Receipt

State root scope/mode and read-only authority; identify the configuration, static-audit, and report artifacts; give the coverage status; and name the stop condition or authorized manual-review next step. Include fingerprint, budgets, skips/errors, and path mode. State `COMPLETE_WITHIN_CONFIG`, the reported partial state, or failure exactly as the report does.

## Validate

Run from this directory:

```powershell
python -m unittest discover tests
python scripts/audit_guard.py
python scripts/disk_scan.py --config config/scan_config.json
```

The tests use temporary fixtures. The audit command statically checks production
scripts for configured destructive APIs and commands. The final command performs
the configured read-only scan and may record missing or inaccessible paths.
