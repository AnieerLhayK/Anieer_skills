# Scripts

`disk_scan_report_runtime` is the supported Workspace entry point. Run it from
the Workspace root with the current session ID; it creates a dedicated TASK and
report-root lease, invokes `disk_scan.py`, applies 30-day report retention, and
records the receipt. The scanner CLI accepts `--record-id` and `--lease` only
when called through that governed runtime.

`disk_scan.py` performs the bounded read-only metadata scan. The default plan
first records C/D directory lower bounds, then deep-scans only eligible promoted
roots under independent budgets; it writes schema 2.0 Markdown and JSON reports.
Legacy `scan_paths` configurations retain the original single-stage behavior.

`disk_scan_manual.py` implements explicit `--deep-scan` requests without drive
inventory or automatic promotion gates. Targets share one total budget; source
repositories, protected paths and links remain excluded. Cleanup lives in the
separate Workspace adapter linked from `references/cleanup.md`, outside the
audited metadata-only scanner scripts.

`init_config.py` creates the external scan profile from tracked examples, or
copies the current local profile with `--migrate-current`. External writes
require an active `external_write` TASK and validated lease passed with
`--record-id` and `--lease`. It never overwrites existing external files. The
active audit policy must match its reviewed template; `--sync-audit-policy`
requires explicit confirmation and creates a verified rollback copy first.

`audit_guard.py` statically checks production scripts for configured destructive
operations, restricts report writes to approved roots, and provides shallow
before/after snapshot helpers.

Run the Workspace runtime from the Workspace root as documented in `SKILL.md`.
