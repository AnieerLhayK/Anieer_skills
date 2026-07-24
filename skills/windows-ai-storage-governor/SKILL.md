---
name: windows-ai-storage-governor
description: Audit, classify, plan, apply, and verify reversible Windows storage changes for AI tools, caches, sessions, MCP artifacts, user-profile clutter, and selected global install locations. Use when Codex or Claude Code needs to inspect paths used by tools such as Gemini CLI, npm, Playwright, MCP hosts, Hermes, Codex, Claude Code, OpenCode, or Copilot; decide whether data is cache, configuration, runtime, session, source, backup, link, stale artifact, or unknown; reduce new system-drive writes; or prepare a user-approved migration to another drive without disturbing stable junctions or symlinks.
---

# Windows AI Storage Governor

## Contract

Govern Windows AI-related storage with auditability, explicit approval, and rollback.
Default to read-only work. Treat unknown paths as preserve-and-report.

Own:

- Bounded inspection of user-supplied paths and known tool candidates.
- Path classification and risk labeling.
- Reversible migration and cleanup plans.
- User-approved application of plan-whitelisted actions.
- Post-change verification and residual-write reporting.

Do not own:

- Whole-profile, whole-`Users`, whole-`AppData`, or project-tree migration.
- Deletion of private corpora or data with unclear ownership.
- Rebuilding a stable junction or symlink without a specific failure and approval.
- Unplanned deletion, move, overwrite, archive, or rename operations.
- Source-tree cleanup unrelated to AI storage governance.

## Modes

### audit

Perform read-only inspection. Report observed paths, links, classifications, risks,
and missing evidence. Do not create destination directories as a convenience.

### plan

Convert an audit into a whitelist of proposed actions. For every action include:
source, destination, reason, risk, prerequisites, verification, and rollback.
Separate required, optional, report-only, and blocked items.

### apply

Enter only after the user explicitly approves the exact plan or named action IDs.
Re-read [references/safety-policy.md](references/safety-policy.md) and
[references/migration-runbook.md](references/migration-runbook.md). Execute only
approved whitelist items, one reversible step at a time. Stop on drift, ambiguity,
unexpected existing content, or failed verification.

### verify

Check command availability, configured locations, link targets, destination
health, and new system-drive residue. Verification is read-only.

### cleanup

Treat cleanup as stricter than apply. Require a separate confirmation that names
the exact paths and acknowledges irreversibility. Never infer cleanup approval
from migration approval.

## Required Workflow

1. Establish scope.
   - Record the requested mode, paths, tools, target root, and report location.
   - Resolve the target root from a user value or environment configuration.
   - Never assume a particular drive letter.
2. Inspect safely.
   - Use `scripts/audit-environment.ps1` for bounded environment audits.
   - Use `scripts/inspect-path.ps1` for a user-named path.
   - Preserve observed link state; do not recreate links during inspection.
3. Classify evidence.
   - Apply [references/path-classification.md](references/path-classification.md).
   - Mark uncertain items `unknown`; do not guess from a directory name alone.
4. Plan before mutation.
   - Use `scripts/build-migration-plan.ps1` to generate a non-executing plan.
   - Explain risk and rollback before requesting approval.
5. Apply narrowly when approved.
   - Verify source and destination have not drifted since the plan.
   - Prefer supported tool configuration, then environment variables, then a
     reversible directory link. Preserve the original until validation passes.
   - Do not execute destructive cleanup in the same approval step.
6. Verify.
   - Use `scripts/validate-migration.ps1`.
   - Report pass, warning, or blocked status and any residual system-drive writes.

## Path Strategy

- Accept `-TargetRoot`, a user-provided path, or a documented environment value.
- Keep internal skill paths relative to this skill directory.
- Do not encode a fixed target drive in policy, scripts, fixtures, or reports.
- Treat system-drive location as a risk signal, not automatic permission to move.
- Inspect only explicit paths, bounded known candidates, and direct link targets.
- Do not recursively scan an entire drive, user profile, `Users`, or `AppData`.

## Failure Strategy

- Missing required input: stop with `ERROR` and name the missing value.
- Missing optional tool or candidate: emit `WARNING` and continue in degraded mode.
- Unknown path purpose: classify as `unknown`, preserve it, and request evidence.
- Conflicting source, target, or link state: stop before mutation.
- Failed verification: stop subsequent actions and present rollback steps.
- Never fabricate a path, tool setting, migration success, or cleanup eligibility.

## Outputs

Use [references/report-schema.md](references/report-schema.md) for:

- Audit report.
- Migration plan.
- Apply record.
- Verification result.
- Risk and residual-write summary.

## Resources

- [references/safety-policy.md](references/safety-policy.md): approval and mutation rules.
- [references/path-classification.md](references/path-classification.md): categories and dispositions.
- [references/migration-runbook.md](references/migration-runbook.md): reversible execution sequence.
- [references/report-schema.md](references/report-schema.md): stable output fields.
- [references/tool-adapters.md](references/tool-adapters.md): bounded tool-specific probes.
- `fixtures/safe-sandbox-profile.json`: non-live sample input for tests and dry runs.
