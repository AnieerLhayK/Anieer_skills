---
name: disk-scan-reporter
description: Inspect Windows disk usage, deep-scan explicitly requested directories, and execute exact user-approved cleanup batches in the same chat; use for capacity review, not tool migration.
metadata:
  portability: host-adapted
  distribution: review-required
  requires: [windows, python, workspace-manifest, workspace-cli-for-cleanup]
---

# Disk Scan Reporter

Produce metadata-only storage evidence, then continue in the same chat when the user requests deeper inspection or approves an exact cleanup batch.

## Authority

Default to read-only inspection and report writing. Scheduled runs use the configured automatic plan; thresholds and `review_only` constrain automatic promotion only. An explicit request for a named directory authorizes its bounded read-only deep scan without another confirmation or TASK. It does not authorize deletion.

For user-approved cleanup, read [cleanup.md](references/cleanup.md). That branch uses `environment_cleanup_apply` and `environment_write`, with an automatically managed TASK and exact-path lease. The separate standing 30-day report-retention exception is limited to generated files in the external reports directory; it uses a dedicated TASK and lease on every scan. Reports, risk labels and prior deletions authorize no other cleanup. Keep system protection, links, source repositories and configured private/runtime exclusions intact; stop on a denied operation without changing mechanisms.

## Run

1. Resolve `runtime_roots.workspace_governance` from `workspace_manifest.yaml`. Read `disk-scan-reporter/config/scan_config.json` and `audit_policy.json` below that root. If either file is missing, stop scanning. Initialize only when both external files are absent, under an active `external_write` TASK whose resolved route scope covers the exact config paths, plus a validated lease scoped to those paths. Use `--migrate-current` only if a current local `config/scan_config.json` still exists; otherwise initialize from the tracked generic examples. If only one external file exists, stop and reconcile that partial state without overwriting it. Never bypass the write check. Complete when both files are present and the requested scan mode and boundaries are understood.
2. Run `python scripts/audit_guard.py`. A `FAIL` stops the scan. The scanner also requires the active external audit policy to match the reviewed `config/audit_policy.example.json` template. To synchronize a changed policy, use `python scripts/init_config.py --sync-audit-policy --record-id <TASK-ID> --lease <LEASE-PATH>`; it creates and verifies a rollback copy before replacement. Complete when the audit passes and the active policy matches.
3. From the Workspace root, run `python -B -m scripts.workspace.disk_scan_report_runtime --session <SESSION-ID>` with `--config` set to the external `scan_config.json` when needed. The runtime wrapper creates a `disk_scan_report_retention` TASK and a lease limited to the external reports directory, then invokes the scanner and prunes only eligible reports older than 30 days. For a manual request, append `--deep-scan "<absolute-directory>"` for each requested target. This scans only those targets, skips inventory, bypasses size thresholds and `review_only`, and shares 900 seconds / 500,000 files across the batch. It does not change future scan scope. Do not restart or ask again at the automatic per-directory limits; report partial coverage at the shared limit. Reports default to the external `disk-scan-reporter/reports` directory; explicit output must remain under that directory. Complete when the report and retention receipt are recorded or their failures are reported.
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
