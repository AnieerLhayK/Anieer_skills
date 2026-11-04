# Disk Scan Reporter

`disk-scan-reporter` inspects Windows disk usage, deep-scans explicitly named
directories, and continues with exact user-approved cleanup in the same chat.
Its scanner reads filesystem metadata and writes Markdown and JSON reports.

The scanner never modifies scanned files, elevates privileges, changes system
settings, or creates missing scan targets. Cleanup uses a separate Workspace
adapter after approval; see [cleanup.md](references/cleanup.md).

## Run

From this skill directory:

```powershell
python scripts/disk_scan.py --config config/scan_config.json
```

Optional controls:

```powershell
python scripts/disk_scan.py --config config/scan_config.json --max-depth 6
python scripts/disk_scan.py --config config/scan_config.json --json-only
python scripts/disk_scan.py --config config/scan_config.json --md-only
python scripts/disk_scan.py --config config/scan_config.json --deep-scan "D:\Dev\package-cache"
```

The output directory is created when needed. With no `--output`, the scanner
uses `AI_TOOL_STAGING_DIR`, then the Workspace `runtime_roots.staging` setting,
then the system temporary directory, always under `disk-scan-reporter/`.
An explicit output keeps the legacy policy-approved-root checks for existing
callers; new automation should omit `--output` and keep reports outside source.
Missing scan
roots are not created; they are recorded under `skipped`.

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

`scan_paths` remains supported for legacy single-stage configurations. Keep
reports in relative-path mode when they may be shared.

## Read the Reports

Each run writes timestamped files below the resolved output root:

```text
disk-scan-reporter/disk_report_YYYY-MM-DD_HHMMSS.md
disk-scan-reporter/disk_report_YYYY-MM-DD_HHMMSS.json
```

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

`config/audit_policy.json` defines production source roots, destructive APIs and
command tokens, allowed runtime write roots, and shallow snapshot behavior.
The scanner fails closed if the static audit finds a configured destructive
operation. Explicit report output is accepted only under `reports/`, `state/`,
or `logs/`; the resolved default staging directory is separately allowlisted.
Both paths use lexical and resolved-path containment checks.

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
