# Approved Cleanup in the Same Chat

Use this branch after inspection identifies exact targets. Keep the scan report
as read-only evidence; cleanup has a separate receipt. The Workspace adapter is
`scripts/workspace/disk_scan_cleanup.py`, resolved from the manifest source root.
It uses native PowerShell deletion outside the audited scanner package.

## Prepare and approve

1. Inspect ownership and current use. Prepare a staging JSON array of actions
   with `path`, `method` (`recycle` or `permanent`), `purpose`, `impact`, and
   `backup`. Unknown ownership requires inspection before a proposal. Each path
   is absolute and literal; exclude whole drive/user roots, system protection,
   links, repositories, private material and configured excluded trees. Tool
   uninstall and migration use their owning workflows, in the same chat when
   supported; they are not generic disk cleanup.
2. From the source root, run `python -B -m scripts.workspace.disk_scan_cleanup
   prepare --actions "<staging-actions.json>"` and save its JSON stdout as the
   proposed staging plan. Preparation reads metadata, writes no TASK or lease,
   and rejects overlapping targets. Display each action's ID, exact path, size,
   purpose, impact, disposition and recovery/backup status. Explicitly describe
   permanent deletion as irreversible and whether a backup exists. Recycle Bin
   placement ordinarily does not free the original drive's space.
3. Ask once for approval of that displayed batch. A reply such as “清理第 1、3 项”
   approves those displayed paths and methods without requiring the user to
   repeat them. For a subset, prepare a plan containing only those unchanged
   actions and verify the proposal metadata did not change; the user's approval
   covers that subset. Record the correspondence in the chat. A changed target,
   method or impact requires a fresh proposal. Approval never covers later
   scheduled runs, extra targets, or emptying the whole Recycle Bin.

## Execute and verify

1. Once the user approves, run `python -B -m scripts.workspace.disk_scan_cleanup
   apply --plan "<approved-staging-plan.json>" --approved-digest "<plan-digest>"
   --session "<current-chat-session-id>"`. The agent supplies the digest; the user
   need not type it. Never infer approval from a scanner finding or supply a digest
   before the user's approval. Do not invoke the native helper directly.
2. The adapter automatically starts an owned `cleanup_migration` TASK with
   `workspace_write` / `external_write`, binds its plan and targets, and issues
   a Codex lease limited to those exact paths for at most one hour. It checks
   registration, acting skill, lease and current target metadata before each
   action. Native PowerShell uses literal paths; it does not elevate, stop
   applications or retry through another deletion mechanism. A failure stops
   the remaining batch. Previously removed items are not silently rolled back.
   The host defaults to Windows PowerShell; `DISK_SCAN_POWERSHELL=pwsh.exe`
   explicitly selects PowerShell 7 for a run. Both hosts execute the same native
   script without changing execution policy. Never select a different host to
   retry a denied batch unless the user explicitly authorizes that change.
3. The adapter verifies absence at the original paths, runs the routed workflow
   check, revokes the lease, finalizes the TASK and returns the per-action
   receipt. Report removed, failed and unattempted actions distinctly. Distinguish
   logical bytes removed from measured free space; do not claim a recycle operation
   released disk space. Permanent deletions have the approved recovery limitation.
   If record finalization fails, report the open record and do not claim closure.

Metadata fingerprints detect ordinary changes; they do not provide an atomic
filesystem snapshot or cryptographic proof of human approval. Inspect a stable
target; a concurrent app recreating files is a reason to stop and reassess.
Keep durable receipts in TASK/lease stores; remove transient action/plan files
from staging after successful use, retaining any failed batch needed for review.

## Standing report-retention exception

The owner approved automatic 30-day retention for this skill's generated
reports. This is the sole exception to per-batch cleanup approval and applies
only to direct regular files under the manifest-resolved
`disk-scan-reporter/reports` directory whose names exactly match
`disk_report_YYYY-MM-DD_HHMMSS.md` or `.json` and whose filename timestamp and
last-write time are both more than 30 days old. Nested directories, links,
reparse points, unrelated files, and younger reports are never candidates.

Each scan creates a `disk_scan_report_retention` TASK and a lease limited to
that exact report directory. The scanner checks authorization before report
writes; the retention adapter rechecks the active TASK, lease, path, age and
file fingerprint before each permanent deletion. It runs after the current
report is written, records the exact deleted paths, revokes the lease and
finalizes the TASK. There is no per-run confirmation. Expired reports have no
backup; deletion is irreversible, and a new scan cannot reproduce the exact
historical snapshot. This exception authorizes no other target or cleanup.
