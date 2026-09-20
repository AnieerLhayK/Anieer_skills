# Scripts

`disk_scan.py` performs the bounded read-only metadata scan. The default plan
first records C/D directory lower bounds, then deep-scans only eligible promoted
roots under independent budgets; it writes schema 2.0 Markdown and JSON reports.
Legacy `scan_paths` configurations retain the original single-stage behavior.

`audit_guard.py` statically checks production scripts for configured destructive
operations, restricts report writes to approved roots, and provides shallow
before/after snapshot helpers.

Run both from the skill directory as documented in `SKILL.md`.
