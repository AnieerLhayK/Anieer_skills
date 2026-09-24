---
name: disk-scan-reporter
description: Inventory Windows disk usage with bounded, read-only coverage reporting; use for capacity evidence, not AI-tool migration or cleanup.
metadata:
  portability: host-adapted
  distribution: review-required
  requires: [windows, python, optional-workspace-manifest]
---

# Disk Scan Reporter

Produce metadata-only storage evidence. The configured two-stage plan defines the boundary; candidates remain candidates for manual review.

## Authority

Read only configured roots and permitted metadata. The only allowed side effect is writing Markdown and JSON reports to policy-approved output roots. Do not follow links, request elevation, alter system/tool settings, or turn a finding into cleanup authority.

## Run

1. Inspect `config/scan_config.json` and its audit policy. For the default C/D plan, confirm inventory depths and budgets, automatic deep-scan thresholds, hard-protected paths, and `review_only` paths. Complete when both stages and the output boundary are known.
2. Run `python scripts/audit_guard.py`. A `FAIL` stops the scan. Complete when the audit status is recorded.
3. Run the absolute `scripts/disk_scan.py` path with `--config`. Without `--output`, reports resolve through `AI_TOOL_STAGING_DIR`, the Workspace staging root, then the system temp directory. An explicit `--output` retains the existing policy-approved-root behavior. Complete when the report is written or its failure is reported.
4. Read the generated report's inventory lower bounds, promotion reasons, deep-scan coverage, budgets, skipped paths, and categorized errors before ranking candidates. Use [coverage_schema.md](references/coverage_schema.md) and [report_schema.json](references/report_schema.json) for machine interpretation. Treat depth or budget exhaustion as partial coverage, not a reason to broaden scope or privileges. Complete when each stage's coverage state is classified.

## Receipt

State the inventory and deep-scan scope, read-only authority, configuration, static-audit, report artifacts, lower-bound caveat, coverage status, and stop condition. Include the fingerprint, budgets, promotion decisions, skips/errors, and path mode. State `COMPLETE_WITHIN_CONFIG`, the reported partial state, or failure exactly as the report does.

## Validate

Run from this directory:

```powershell
python -m unittest discover tests
python scripts/audit_guard.py
python scripts/disk_scan.py --config config/scan_config.json
```

The tests use temporary fixtures. The audit command statically checks production
scripts for configured destructive APIs and commands. The final command performs
the configured read-only C/D plan and may record missing or inaccessible paths.
