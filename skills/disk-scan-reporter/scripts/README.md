# Scripts

`disk_scan.py` performs the bounded read-only metadata scan and writes Markdown
and schema-versioned JSON reports with categorized errors, per-root coverage,
logical and allocated sizes, and hardlink-aware byte totals.

`audit_guard.py` statically checks production scripts for configured destructive
operations, restricts report writes to approved roots, and provides shallow
before/after snapshot helpers.

Run both from the skill directory as documented in `SKILL.md`.
