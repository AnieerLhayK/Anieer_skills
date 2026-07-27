---
name: collaboration-builder
description: Build or migrate a configurable collaboration section for a new or existing repository. Use when a team needs reusable AI rules, role boundaries, task routing, soft Git scope warnings, handoff templates, or an onboarding-ready collaboration operating model.
---

# Collaboration Builder

Use the **operating model**: one explicit source for task boundaries, role ownership, evidence, and handoff. Keep project facts outside this skill's governance layer.

## Build

1. Inspect the target repository: its branch policy, existing rules, team roles, source areas, generated outputs, and CI. Identify only facts that must enter configuration; never copy domain code, data, task statements, result claims, or project-specific constraints into the scaffold.
   - Completion: list the role IDs, their writable roots, protected roots, required checks, and the repository's existing entry files.

2. Choose adoption mode.
   - For a new or empty repository, run `scripts/bootstrap_collaboration.py --target <directory> --project-name <name> --roles <role-a,role-b>`.
   - For an existing repository, run it first with `--dry-run`; then merge the generated entry blocks and configuration deliberately. Preserve existing project rules and do not overwrite a root `AGENTS.md` or `README.md` without explicit approval.
   - Completion: every generated rule has a named owner and every role has an isolated writable root.

3. Configure the generated `PROJECT_CONTEXT/roles.yaml` and `task_registry.yaml` from repository facts. Treat these as the single sources of truth for ownership and task routes. Read [configuration.md](references/configuration.md) before changing their schema or adding a role/task type.
   - Completion: each task declares `required_read`, `write_scope`, and validation; each protected path is intentional.

4. Install or retain `PyYAML`, then run `python scripts/validate_collaboration.py <target>` from this skill. In the target repository run `python -m scripts.workspace.resolve_task_context --list` and inspect one route per task type.
   - Completion: validation succeeds; no `{{PLACEHOLDER}}` remains; route output matches the written role boundaries.

5. Onboard the team using the target README: state the entry chain, role roots, task IDs, handoff location, and soft-warning behavior. Use `AI-records/<work-item>.md` only for AI work that changes project facts.
   - Completion: a new teammate can locate rules, select a route, identify their writable area, and create a handoff without verbal explanation.

## Guardrails

- Keep role names, paths, protected roots, and task IDs in configuration; keep their enforcement in scripts; keep policy prose in `COLLABORATION/`.
- Keep `CLAUDE.md` as a pure reference to its sibling `AGENTS.md`; avoid parallel rule sources.
- Use scope checks as advisory warnings. They surface accidental cross-area edits; human review remains the authorization mechanism.
- Keep source, data, experiments, results, and domain-specific validation outside the collaboration package. Add them to task routes only after the target repository defines their ownership.
- Read [adoption.md](references/adoption.md) for an existing repository, CI integration, or a substantial governance upgrade.

## Included resources

- `scripts/bootstrap_collaboration.py`: creates an empty-repository scaffold from `assets/starter/`.
- `scripts/validate_collaboration.py`: checks a generated scaffold without changing it.
- `assets/starter/`: copyable rules, task routes, templates, and target-repository scripts.
