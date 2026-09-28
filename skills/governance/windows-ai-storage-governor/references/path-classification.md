# Path Classification

Classify from evidence, not name alone.

| Category | Typical evidence | Default disposition |
| --- | --- | --- |
| `cache` | Re-creatable downloads, package cache, browser binaries | Migration candidate |
| `temp` | Tool-owned temporary work with no durable contract | Report; cleanup needs confirmation |
| `session data` | Conversation, checkpoints, local history, recovery state | Preserve; migrate only with tool-aware rollback |
| `configuration` | Settings, credentials references, registries, profiles | Preserve; prefer supported relocation |
| `runtime data` | Databases, indexes, logs, models, mutable tool state | Plan tool-aware migration |
| `project source` | Repository files, source, tests, project assets | Do not move |
| `backup` | Recovery copy, export, snapshot, archive | Preserve until retention is approved |
| `junction / symlink` | Reparse point with a resolvable target | Preserve and verify |
| `duplicate / stale artifact` | Hash or provenance confirms replacement | Report; cleanup needs confirmation |
| `unknown` | Purpose or ownership is not proven | Preserve and request evidence |

## Decision Labels

- `preserve`: no move or cleanup proposed.
- `migrate-candidate`: may move after tool-specific checks and approval.
- `report-only`: include in findings but take no action.
- `cleanup-candidate`: potentially removable only in cleanup mode.
- `blocked`: evidence or safety prerequisite is missing.

Do not label an item `safe-to-delete`. Use `cleanup-candidate` plus evidence,
retention, backup, and confirmation requirements.
