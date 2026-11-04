---
name: disk-scan-reporter
description: Inspect Windows disk usage, deep-scan explicitly requested directories, and execute exact user-approved cleanup batches in the same chat; use for capacity review, not tool migration.
metadata:
  portability: host-adapted
  distribution: review-required
  requires: [windows, python, optional-workspace-manifest, workspace-cli-for-cleanup]
---

# Disk Scan Reporter

Produce metadata-only storage evidence, then continue in the same chat when the user requests deeper inspection or approves an exact cleanup batch.

## Authority

Default to read-only inspection and report writing. Scheduled runs use the configured automatic plan; thresholds and `review_only` constrain automatic promotion only. An explicit request for a named directory authorizes its bounded read-only deep scan without another confirmation or TASK. It does not authorize deletion.

For user-approved cleanup, read [cleanup.md](references/cleanup.md). That branch uses `environment_cleanup_apply` and `environment_write`, with an automatically managed TASK and exact-path lease. Reports, risk labels, earlier deletions and scheduled prompts never grant cleanup approval. Keep system protection, links, source repositories and configured private/runtime exclusions intact; stop on a denied operation without changing mechanisms.

## Run

1. Inspect `config/scan_config.json` and its audit policy. Select automatic inventory or explicit manual deep scan. Read the relevant budgets, protected/excluded paths and report output boundary. Complete when the requested targets and mode are resolved.
2. Run `python scripts/audit_guard.py`. A `FAIL` stops the scan. Complete when the audit status is recorded.
3. Run the absolute `scripts/disk_scan.py` path with `--config`. For a manual request, append `--deep-scan "<absolute-directory>"` for each requested target. This scans only those targets, skips inventory, bypasses size thresholds and `review_only`, and shares 900 seconds / 500,000 files across the batch. It does not change future scan scope. Do not restart or ask again at the automatic per-directory limits; report partial coverage at the shared limit. Without `--output`, reports resolve through `AI_TOOL_STAGING_DIR`, Workspace staging, then system temp. Complete when the report is written or its failure is reported.
4. Read coverage, selection reasons, budgets, skips and errors before drawing conclusions. For automatic inventory, directory totals are lower bounds; for manual scans, state that inventory was not run. Use [coverage_schema.md](references/coverage_schema.md) and [report_schema.json](references/report_schema.json) for machine interpretation. Complete when every requested root is classified and conclusions distinguish observed evidence from unscanned scope.

## Receipt

State mode, scope, report paths, audit result, fingerprint, effective budgets, selection reasons, coverage and stop condition. Use `COMPLETE_WITHIN_CONFIG`, the reported partial state, or failure exactly as reported. Give useful conclusions within that coverage and actionable candidates; a candidate becomes executable only through the approved cleanup branch.

## Validate

Run from this directory:

```powershell
python -m unittest discover tests
python scripts/audit_guard.py
```

The tests use temporary fixtures; set TEMP/TMP to Workspace staging on this host.
The static audit covers scanner scripts, which contain no cleanup execution.
Validate the cleanup adapter with `python -m unittest scripts.tests.workspace.test_disk_scan_cleanup`
from the Workspace source root. For live scanning, use only the requested scope;
validation does not require a full C/D run or deletion of real candidates.
