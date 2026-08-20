---
name: windows-ai-storage-governor
description: Windows AI-storage governance. Use when bounded audit, reversible planning, or verification is needed.
---

# Windows AI Storage Governor

Produce an auditable chain: **audit -> plan -> verify**. Preserve unknown or durable data until evidence and the appropriate authority exist.

## Authority

Own bounded inspection, classification, reversible plans, and read-only verification for AI-tool storage. Do not own whole-profile or project-tree migration, disposal of unclear data, or automatic link repair.

`apply` is not implied by a plan: it belongs to a separately authorized execution path with exact user approval and runtime write authority. `cleanup` needs a separate exact-path confirmation. Read [safety-policy.md](references/safety-policy.md) before either path; it defines approval gates, mutation constraints, and stop conditions.

## Run

1. Record mode, explicit paths/tools, target root, and report location. Inspect only supplied paths, bounded known candidates, and direct link targets. Complete when the scope is explicit.
2. Audit with `scripts/audit-environment.ps1` or `scripts/inspect-path.ps1`; preserve observed links. Classify with [path-classification.md](references/path-classification.md), marking uncertain purpose `unknown`. Complete when every observed path has evidence and a disposition.
3. For planning, run `scripts/build-migration-plan.ps1` from an audit report. Each action must retain source, target, risk, prerequisites, verification, rollback, and approval state; the generator executes nothing. Complete when every proposed action is whitelisted or blocked.
4. Verify a plan with `scripts/validate-migration.ps1`. Use [tool-adapters.md](references/tool-adapters.md) for tool-specific probes and [migration-runbook.md](references/migration-runbook.md) for an approved reversible execution path. Complete when verification status and residual-write state are recorded.

## Receipt

Link audit, plan, and verification `report_id` values to the scoped mode and actual authority; include findings, action IDs, approvals, warnings/errors, residual-write state, and final status. Name the stop gate or authorized next step. Stop on unknown purpose, drift, unexpected destination content, link mismatch, insufficient prerequisites, or failed verification. [report-schema.md](references/report-schema.md) defines the stable fields.
