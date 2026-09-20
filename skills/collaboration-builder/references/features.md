# Optional features

All features default to `enabled: false` and work with every layout.

- `ai_records` creates per-role `ai-records/` templates and a staged coverage checker. Its enforcement is `blocking` by default; set `enforcement: advisory` only when a project explicitly accepts warnings.
- `work_session_lock` creates explicit acquire, release, handoff and check commands. Locks are local to the Git common directory, carry owner/work item/paths/expiry, and block overlapping active paths.
- `git_hooks` creates `.githooks/` and an installer. The installer must be run explicitly and refuses an incompatible existing `core.hooksPath`.

`ai-record-gather` is not a dependency of these features. It remains a separate read-only audit skill.
