---
name: skill-adaptator
description: Publish an explicitly selected, reviewed Workspace skill into an external Git project through a read-only adaptation plan and authorized apply.
disable-model-invocation: true
metadata:
  portability: workspace-bound
  distribution: review-required
  requires: [python, pyyaml, git, workspace-cli, optional-workspace-manifest]
---

# Skill Adaptator

Publish a reviewed Workspace skill into an external Git project. This direction
is fixed: external-to-Workspace intake belongs to `skill-migrator`. The default
operation is `plan`; `apply` requires confirmation and an active
external-origin `workspace_write` task record plus a valid scoped lease.

## Run

1. Resolve a manifest skill id or an explicit source path inside the Workspace.
   Require an explicit Git `--project-root` and project-relative `--target-root`.
2. Run `scripts/adapt_skill.py plan` with `--source`, `--project-root`,
   `--target-root`, and `--output plan.json`. Use `--mode update` for an
   existing managed entry and repeatable `--replace FILE=OLD=NEW` only for
   reviewed exact-once transformations. For `host-adapted` and
   `workspace-bound` sources, record every declared dependency with repeatable
   `--resolve-dependency REQUIREMENT=RESOLUTION`.
3. Review the plan with the user. After confirmation, register an external-origin
   `workspace_write` task using `records external-start` with the project as
   client root, then run
   `scripts/adapt_skill.py apply --plan plan.json --record-id TASK-ID --lease LEASE.json`.
   Apply verifies that exact agent/project binding and separately authorizes both
   the target and receipt paths. Every apply requires an existing scoped
   `--lease` covering both exact paths; denial stops apply before any target or
   receipt write.
4. Report source/target, plan hash, managed files, adaptations, validation,
   task record, and outcome.

## Boundaries

- Copy only UTF-8 text files. Reject links, reparse points, credentials,
  private corpus material, caches, reports, and unresolved absolute paths.
- Existing unmanaged files or changed managed hashes are hard conflicts. Never
  overwrite, delete, or merge automatically.
- `portable` may plan without adaptation. `host-adapted` must resolve every
  declared host dependency. `workspace-bound` must additionally remove every
  detected Workspace marker from rendered output; it cannot be published
  verbatim. Update the rendered dependency declarations as well as commands
  and paths. Resolution prose alone is insufficient: the plan records hashes
  of changed files, and apply rechecks the actual payload against current source.
- Preserve frontmatter and UI metadata unless a reviewed adaptation changes it.
- `publish` creates a managed entry; `update` requires one. Revocation is out
  of scope.

Plans and receipts retain schema 1.0 while adding portability, distribution,
dependency-resolution, and residual-scan fields. Read
[references/contract.md](references/contract.md) for the complete contract.
