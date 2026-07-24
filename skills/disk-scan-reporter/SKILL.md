---
name: disk-scan-reporter
description: Generate bounded, read-only Markdown and JSON disk usage reports from configurable Windows paths. Use when Codex needs to inspect disk usage, find large or old files, identify cache, build, dependency, log, temporary, or archive candidates for manual review, or prepare a cleanup-oriented report without deleting, moving, compressing, renaming, or modifying user files.
---

# Disk Scan Reporter

## Contract

This skill is read-only.

- Never delete, move, compress, rename, or modify user files.
- Never execute cleanup commands or generate and execute cleanup scripts.
- Generate Markdown and JSON reports only.
- When uncertain, mark the item as `HIGH` risk and require manual review.
- Do not scan entire system drives by default.
- Do not request administrator privileges.
- Do not modify shell profiles, the registry, system proxy, `PATH`, scheduled
  tasks, or global tool configuration.

## Workflow

1. Confirm or inspect the bounded scan configuration in `config/scan_config.json`.
2. Keep scan roots user-supplied or explicitly configured. Never broaden them
   to a drive root or whole user profile.
3. Run the static safety audit:

   ```powershell
   python scripts/audit_guard.py
   ```

4. Run:

   ```powershell
   python scripts/disk_scan.py --config config/scan_config.json
   ```

5. Read the safety and coverage audit sections before interpreting candidates.
6. Read the generated Markdown summary and schema-versioned JSON data under
   `reports/`. Use `references/report_schema.json` for machine consumers.
7. Present findings as candidates for manual review only. Never describe a
   candidate as something that should be deleted.
8. Report skipped paths and categorized scan errors without retrying with
   elevated privileges.
9. Keep `report_path_mode` set to `relative` when reports may be shared. Use
   absolute paths only for local review when exact locations are necessary.

## Safety Rules

- Read only path, size, modification time, extension, directory, and link/type
  metadata.
- Do not follow links unless the user explicitly changes the configuration.
- Even when link following is enabled, retain cycle detection and depth limits.
- Treat `.git`, Windows, Program Files, System Volume Information, and recycle
  bin paths as `DO_NOT_TOUCH`.
- Treat dependency directories and unknown items as `HIGH`.
- Treat every risk level, including `LOW`, as advisory only.
- Create only the selected report output directory and report files. Never
  create a missing scan target.
- Keep candidate, error, and skipped-path detail lists bounded. Preserve total
  counters when detail records are omitted.
- Count hard-linked files once in logical and allocated byte totals while
  retaining the observed file-entry count.
- Treat logical size as the stable ranking basis. Report allocated size
  separately and mark it incomplete when the filesystem does not expose it.
- Keep file-count and elapsed-time budgets enabled. A budget-limited scan is a
  partial result, not a reason to broaden scope or request elevation.
- Write runtime artifacts only under `reports/`, `state/`, or `logs/`. Reject
  lexical or resolved paths that escape those roots.
- Treat shallow before/after snapshots as anomaly indicators only; they cannot
  prove that no concurrent process changed file content.

## Validation

Run from this skill directory:

```powershell
python -m unittest discover tests
python scripts/audit_guard.py
python scripts/disk_scan.py --config config/scan_config.json
```

The tests use temporary fixtures. The audit command statically checks production
scripts for configured destructive APIs and commands. The final command performs
the configured read-only scan and may record missing or inaccessible paths.
