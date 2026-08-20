---
name: collaboration-builder
description: Collaboration operating-model scaffolds. Use when a repository needs a new scaffold or dry-run adoption plan.
---

# Collaboration Builder

Build the **operating model**: one configured source for task boundaries, role ownership, evidence, and handoff. The target repository owns its project facts and policy choices.

## Authority

Own scaffold generation, configuration guidance, and read-only validation. Generate only into a new or empty target. For an existing repository, use `--dry-run` and generate beside it; the owner decides which blocks to integrate. Do not overwrite entry files or decide project roles, writable roots, protected paths, task scope, CI, or domain validation.

## Run

1. Inspect the target's entry files, branch policy, roles, generated outputs, and CI. Record only facts required by the scaffold.
   - Complete when role IDs, candidate writable/protected roots, required checks, and existing entries are identified.
2. Generate the smallest scaffold.
   - New or empty target: run `scripts/bootstrap_collaboration.py --target <directory> --project-name <name> --roles <role-a,role-b>`.
   - Existing target: run the same command with `--dry-run`, then let the owner integrate selected blocks.
   - Complete when every generated rule has an owner and each role has an isolated root.
3. In a new or empty target, configure `PROJECT_CONTEXT/roles.yaml` and `task_registry.yaml` from its facts. For an existing target, prepare proposed configuration beside it; its owner integrates it. Read [configuration.md](references/configuration.md) before changing schema or adding a role/task type.
   - Complete when each task declares `required_read`, `write_scope`, and validation, or the owner has the proposed configuration.
4. Run `python scripts/validate_collaboration.py <target>` and inspect one route per task with the target's resolver.
   - Complete when validation passes, no placeholder remains, and one resolver route for every task type matches its configured role boundary.

## Receipt

State the scaffold scope/mode, who may integrate it, command and validation artifacts, final status, and whether owner integration is next or validation blocks adoption. Include target state, dry-run status, approved integrations, and configuration sources.

For existing-repository adoption, CI, or a substantial governance upgrade, read [adoption.md](references/adoption.md). The bundled starter is the generated artifact; project-specific source, data, experiments, and results stay in the target repository.
