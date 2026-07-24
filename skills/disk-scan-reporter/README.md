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
python scripts/disk_scan.py --config config/scan_config.json --output reports
python scripts/disk_scan.py --config config/scan_config.json --max-depth 6
python scripts/disk_scan.py --config config/scan_config.json --json-only
python scripts/disk_scan.py --config config/scan_config.json --md-only
```

The output directory is created when needed. Missing scan roots are not created;
they are recorded under `skipped`.

## Configure the Scan

Edit `config/scan_config.json`:

- `scan_paths`: explicit roots to inspect. Environment variables such as
  `%USERPROFILE%` and `%LOCALAPPDATA%` are expanded.
- `exclude_paths`: absolute paths or directory names to skip.
- `large_file_mb`, `very_large_file_mb`, `old_file_days`: classification
  thresholds.
- `max_depth`: recursion limit below each configured root.
- `follow_symlinks`: defaults to `false`; keep it false unless link traversal is
  explicitly required.
- `max_report_items`: bounds detailed candidate records while summary counters
  continue to reflect the scan.
- `max_diagnostic_items`: independently bounds stored error and skipped-path
  details while preserving total counters.
- `max_files_per_run`: stops traversal after the configured number of observed
  files and reports `PARTIAL_BUDGET_EXHAUSTED`.
- `max_scan_seconds`: bounds elapsed traversal time for the complete run.
- `audit_policy`: names the policy file in the same configuration directory.
- `report_path_mode`: defaults to `relative`, replacing local absolute paths
  with numbered scan-root labels. Set it to `absolute` only when the report
  will remain local and exact paths are required.

Do not configure a whole system drive or whole user profile as a scan root.
The shipped configuration scans only Downloads and the current user's local
temporary directory. Add AI cache or data roots explicitly after reviewing
their scope; do not scan the workspace source tree by default.

## Read the Reports

Each run writes timestamped files:

```text
reports/disk_report_YYYY-MM-DD_HHMMSS.md
reports/disk_report_YYYY-MM-DD_HHMMSS.json
```

The Markdown report summarizes scope, skipped paths, categorized errors,
logical and allocated size, hardlink de-duplication, top large files,
manual-review candidates, high-risk findings, and `DO_NOT_TOUCH` paths.

The JSON report declares `schema_version`, `tool_version`, and a deterministic
SHA-256 `config_fingerprint`. Machine consumers should validate
`references/report_schema.json` and reject unknown schema versions. Logical
bytes are the stable ranking basis; allocated bytes are reported separately
and may be `null` when the filesystem cannot provide complete evidence.

With the default relative path mode, `<scan_root_1>` and similar labels map to
the ordered `scan_paths` entries in the local configuration. This reduces
username and local-layout disclosure when a report is shared. Relative mode is
not anonymization: filenames and directory names below each root can still be
sensitive.

## Safety and Coverage Audits

Run the standalone static audit with:

```powershell
python scripts/audit_guard.py
```

`config/audit_policy.json` defines production source roots, destructive APIs and
command tokens, allowed runtime write roots, and shallow snapshot behavior.
The scanner fails closed if the static audit finds a configured destructive
operation. Report output is accepted only under `reports/`, `state/`, or
`logs/`, with both lexical and resolved-path containment checks.

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
