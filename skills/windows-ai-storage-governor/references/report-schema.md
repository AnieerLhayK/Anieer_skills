# Report Schema

Use UTF-8 JSON for script output. Human summaries may be Markdown.

## Common Fields

```json
{
  "schema_version": "1.0",
  "report_type": "audit | plan | apply | verify",
  "report_id": "stable task-local id",
  "generated_at": "ISO-8601 timestamp",
  "mode": "audit | plan | apply | verify | cleanup",
  "status": "PASS | WARNING | BLOCKED | ERROR",
  "target_root": "optional user-selected root",
  "commands": [],
  "findings": [],
  "warnings": [],
  "errors": []
}
```

## Audit Finding

Required fields: `path`, `exists`, `path_type`, `classification`, `disposition`,
`link_type`, `link_target`, `system_drive`, `tool`, `evidence`, and `risk`.

Command observations contain `command`, `found`, and `source`. Do not treat a
missing standalone command as proof that no package, MCP host, or embedded
Playwright runtime exists.

## Plan Action

Required fields: `action_id`, `source`, `target`, `classification`, `operation`,
`reason`, `risk`, `prerequisites`, `verification`, `rollback`,
`irreversible`, and `approved`.

Allowed planned operations for the MVP:

- `configure-location`
- `copy-then-link`
- `report-only`
- `preserve`
- `blocked`

The plan generator does not execute these operations.

## Verification Result

Required fields: `action_id`, `source_state`, `target_state`, `link_state`,
`command_state`, `residual_write_state`, `status`, and `message`.
