# Disk Scan Reporter

`disk-scan-reporter` is a read-only Windows disk-usage diagnostic skill. It
scans only configured paths, reads filesystem metadata, classifies manual-review
candidates, and writes a human-readable Markdown report plus a machine-readable
JSON report.

It never deletes, moves, renames, compresses, truncates, or modifies user files.
It does not run cleanup utilities, request administrator privileges, change
system settings, or create missing scan targets.

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
`skills/disk-scan-reporter`. `workspace_manifest.yaml` registers its role,
read-only audit authority, report-write execution mode, required files, and
Codex exposure. The manifest projection points the Codex loading surface back
to this single source directory; platform directories are not independent
copies and must not be edited directly.

## Future Automation

A later, separately reviewed automation may schedule the same read-only command
and send only a summary. Possible extensions include comparison with the prior
report, newly added large files, fastest-growing directories, and weekly
summary delivery. Any future automation must preserve the no-cleanup boundary
and must not turn recommendations into deletion actions.
