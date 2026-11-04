# Coverage Audit Schema

Schema 2.0 measures coverage independently for two stages. Inventory coverage
is limited by its configured drive depth and budget; its byte totals are
observed lower bounds, not complete directory sizes. Deep-scan coverage is
measured against each promoted root and its independent budget, plus the
whole-run deadline.

Each root records:

- `planned_root`: report-safe root label.
- `started` and `completed`: whether traversal began and ended normally.
- `files_scanned` and `dirs_scanned`: observed metadata counts.
- `skipped_by_depth`, `skipped_by_exclusion`, `skipped_links`,
  `skipped_duplicates`, and `skipped_unsupported`.
- `permission_errors`, `not_found_errors`, `interrupted_errors`,
  `metadata_errors`, and `unknown_errors`.
- `hardlink_duplicates_skipped`.
- `file_budget_hit` and `time_budget_hit`.
- `terminal_reason`.
- `before_snapshot`, `after_snapshot`, and `snapshot_comparison`.

Statuses:

- `COMPLETE_WITHIN_CONFIG`: traversal completed without skips or errors.
- `PARTIAL_WITH_EXPLAINED_SKIPS`: configured depth, exclusion, link, duplicate,
  or unsupported-entry rules caused explicit skips.
- `PARTIAL_BUDGET_EXHAUSTED`: the run reached its file or time budget.
- `PARTIAL_PERMISSION_LIMITED`: permission errors limited coverage.
- Other categorized scan errors produce `PARTIAL_WITH_EXPLAINED_SKIPS`.
- `FAILED`: a planned root was missing, invalid, or failed unexpectedly.

A shallow before/after snapshot is diagnostic only. Concurrent applications can
change a directory during a scan, and unchanged shallow metadata cannot prove
that file content was untouched.

Inventory aggregates also record the path policy (`hard_protected`,
`review_only`, or `auto_deep`), observed bytes, threshold, and promotion
reason. `hard_protected` paths and links are never traversed; `review_only`
paths can be included in the bounded inventory but are never automatically
promoted.

## Explicit Manual Deep Scans

Tool 2.1 retains schema 2.0 with optional `run_mode` (`automatic` or
`manual_deep`). Reports without this field retain their historical meaning.
Manual `request` records safe drive-relative target labels, the user-requested
selection reason and shared limits. Its inventory stage is `not_run` with empty
drive/aggregate lists; its deep stage is `manual_shared_budget`, with
`max_total_seconds` and `max_total_files` instead of per-target budgets.
Each deep target has `selection_reason: user_requested`.

The default manual budget is 900 seconds / 500,000 files for all targets combined,
with no automatic per-target stop. Thresholds and `review_only` do not gate this
mode. Duplicate/nested roots are coalesced, protection remains effective, and the
fingerprint includes the effective request and exclusions. Exhausted or unstarted
roots remain visible as partial/failed coverage. The report never asserts a full
drive inventory or cleanup. Cleanup receipts live separately in TASK records.
