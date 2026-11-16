# Disk Scan Reporter

`disk-scan-reporter` inspects Windows disk usage, deep-scans explicitly named
directories, and continues with exact user-approved cleanup in the same chat.
Its scanner reads filesystem metadata and writes Markdown and JSON reports.

The scanner never modifies scanned files, elevates privileges, changes system
settings, or creates missing scan targets. Each run is launched through a
Workspace runtime that records a TASK and short-lived report lease. The runtime
also permanently removes only generated reports older than 30 days; see
[cleanup.md](references/cleanup.md). User-approved cleanup uses a separate
adapter.

## Run

The active configuration and reports are stored outside the Workspace at the
`runtime_roots.workspace_governance` location from `workspace_manifest.yaml`.
Initialize a new external profile only under an active `external_write` TASK
whose resolved route scope covers the config directory, and a validated lease
scoped to those exact paths:

```powershell
python scripts/init_config.py --record-id TASK-... --lease ${LOCAL_PATH}
```

To preserve the existing local scan plan during its first migration, use
`--migrate-current`. The initializer checks the TASK and lease before writing,
copies without removing source files, and refuses to overwrite either external
file. From the Workspace root, run the scanner through the governed runtime so
each report write and retention delete has its own TASK and lease. Pass `--config`
only when selecting an explicit configuration path:

```powershell
python -B -m scripts.workspace.disk_scan_report_runtime --session <SESSION-ID>
```

Pass scanner options after the session ID, for example:

```powershell
python -B -m scripts.workspace.disk_scan_report_runtime --session <SESSION-ID> --md-only
python -B -m scripts.workspace.disk_scan_report_runtime --session <SESSION-ID> --deep-scan "D:\Dev\package-cache"
```

The 30-day rule permanently deletes only direct `disk_report_YYYY-MM-DD_HHMMSS.md`
and `.json` files whose filename timestamp and last-write time are both older
than 30 days. There is no backup for expired reports.

The runtime forwards these scanner controls:

```powershell
python -B -m scripts.workspace.disk_scan_report_runtime --session <SESSION-ID> --max-depth 6
python -B -m scripts.workspace.disk_scan_report_runtime --session <SESSION-ID> --json-only
python -B -m scripts.workspace.disk_scan_report_runtime --session <SESSION-ID> --md-only
python -B -m scripts.workspace.disk_scan_report_runtime --session <SESSION-ID> --deep-scan "D:\Dev\package-cache"
```

Reports default to the external `disk-scan-reporter/reports` directory. Explicit
`--output` paths must remain inside that same directory. Missing scan roots are
not created; they are recorded under `skipped`.

## Configure the Scan

The default `two_stage_plan` inventories C and D before it deep-scans anything.
It observes C to depth 3 (60 seconds / 100,000 files) and D to depth 4 (120
seconds / 200,000 files). These directory totals are lower bounds, not a claim
of complete drive usage.

Only eligible paths whose observed bytes strictly exceed 4 GiB on C or 8 GiB
on D are promoted. Promoted roots recurse without a depth limit, but each has a
180-second / 100,000-file budget and the full run has a 15-minute ceiling.
System paths and links are never traversed. Application and development roots
are inventory-only; notably `${LOCAL_PATH}` is review-only and cannot be
auto-promoted. `large_file_mb` and `very_large_file_mb` are 1 GiB and 4 GiB;
file age is review context rather than a candidate rule.

Explicit `--deep-scan` targets bypass automatic thresholds and `review_only`,
skip drive inventory, and share 900 seconds / 500,000 files. Repeat the option
for multiple absolute directories. The request is read-only, requires no TASK
or repeated approval, and does not change the automatic configuration. System
protection, links, `.git`, source repositories and configured exclusions remain
in force. A shared budget stop produces partial coverage without an automatic
restart or a request to register more work.

`config/scan_config.example.json` is a generic initialization template;
`config/audit_policy.example.json` is the reviewed safety-policy template. The
active files are external and missing files stop the scan. The active audit
policy must match its template. Run `python scripts/init_config.py
--sync-audit-policy --record-id TASK-... --lease <LEASE-PATH>` to review and
explicitly synchronize a changed template. The script verifies a rollback copy
before replacing the active policy.
`scan_paths` remains supported for legacy single-stage configurations. Keep
reports in relative-path mode when they may be shared.

## Read the Reports

Each run writes timestamped files below the resolved output root:

Files are named `disk_report_YYYY-MM-DD_HHMMSS.md` and
`disk_report_YYYY-MM-DD_HHMMSS.json` under the external reports directory.

Schema 2.0 reports separate inventory lower bounds, path-policy and promotion
decisions, deep-scan coverage, and manual-review candidates. Inventory uses
drive labels; deep-scan paths use relative promoted-root labels.

The JSON report declares `schema_version`, `tool_version`, and a deterministic
SHA-256 `config_fingerprint`. Readers accept historical schema 1.0 reports;
new reports use schema 2.0 and should validate against
`references/report_schema.json`.

Tool 2.1 adds optional `run_mode` and `request` fields within schema 2.0.
Manual reports mark inventory `not_run`, record safe requested-root labels,
and report `manual_shared_budget`; their fingerprint includes the effective
request and budget. Historical 1.0 and automatic 2.0 reports remain readable.

Relative mode reduces local-layout disclosure but is not anonymization:
filenames and directory names below promoted roots can still be sensitive.

## Safety and Coverage Audits

Run the standalone static audit with:

```powershell
python scripts/audit_guard.py
```

`config/audit_policy.example.json` defines production source roots, destructive
APIs and command tokens, and shallow snapshot behavior. The scanner fails closed
if the static audit finds a configured destructive operation or the active
external policy differs from that template. To synchronize a changed policy,
pass `--record-id` and `--lease` to `init_config.py --sync-audit-policy`; the
script creates and verifies a rollback copy before replacement. Report output is accepted only
under the external reports directory, with lexical and resolved-path checks.

Each report includes per-root coverage:

- whether traversal started and completed;
- observed file and directory counts;
- depth, exclusion, link, duplicate, and unsupported-entry skips;
- permission, not-found, interrupted, metadata, and unknown errors;
- hardlink duplicates omitted from byte totals;
- file/time budget exhaustion;
- a coverage status such as `COMPLETE_WITHIN_CONFIG`,
  `PARTIAL_WITH_EXPLAINED_SKIPS`, `PARTIAL_BUDGET_EXHAUSTED`,
  `PARTIAL_PERMISSION_LIMITED`, or `FAILED`.

Coverage is evaluated against configured roots and budgets, not against an
entire drive. See `references/coverage_schema.md`.

The optional direct-child before/after snapshot records counts, root mtime, and
a name hash. It can flag obvious concurrent changes but cannot prove that no
file content changed.

Risk meanings:

- `LOW`: a comparatively common review candidate, still never auto-cleaned.
- `MEDIUM`: inspect ownership and current use before considering any action.
- `HIGH`: uncertain, dependency-related, or otherwise unsafe without careful
  manual review.
- `DO_NOT_TOUCH`: system, source-control, or explicitly protected content.

No risk label is permission to delete. Automatic cleanup cannot safely infer
ownership, recoverability, active use, or business value from file metadata.

## Workspace Integration

The source package lives at the manifest-relative path
`skills/governance/disk-scan-reporter`. The workspace catalog registers its role,
default audit authority, explicitly approved cleanup authority, execution modes, required files, and
Codex exposure. The manifest projection points the Codex loading surface back
to this single source directory; platform directories are not independent
copies and must not be edited directly.

## Weekly Scan and Follow-up

The weekly job runs the automatic read-only scan and reports coverage and
candidates every time. In that result's chat, an explicit deeper-inspection
request runs immediately within the manual budget. Cleanup requires one
approval of a displayed exact-path batch with each method, impact and recovery
limit. Codex manages the TASK, a maximum one-hour exact-path lease, checks and
closure. Recycle Bin placement is distinct from freeing disk space. Approval
does not persist into future weekly runs.
