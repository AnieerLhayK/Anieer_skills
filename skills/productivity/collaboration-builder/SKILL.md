---
name: collaboration-builder
description: Scaffold a YAML-configured collaboration layout with optional AI records, path-scoped sessions, or installable Git hooks.
disable-model-invocation: true
metadata:
  portability: portable
  distribution: review-required
  requires: [python, pyyaml, git]
---

# Collaboration Builder

Build a declarative **operating model**. `.collaboration.yaml` is the target repository's source of truth for layout, role paths, root governance and optional controls.

## Authority

Own scaffold generation, configuration guidance, and read-only validation. Generate only into a new or empty target. For an existing repository, use `--dry-run` and generate beside it; the owner decides which blocks to integrate. Do not overwrite entry files or decide project roles, writable roots, protected paths, task scope, CI, or domain validation.

## Run

1. Inspect the target's entry files and candidate role roots. Select a bundled layout or prepare a `custom` path template. Read [configuration.md](references/configuration.md).
   - Complete when every role path, governance root and protected/shared root is explicit in YAML.
2. For a new target, pass an external YAML with `--config`; bootstrap copies its normalized form to the target root. For an existing target, use `--dry-run`; it must not write.
   - Complete when every generated area is derived from the selected layout rather than a fixed directory convention.
3. Enable only needed controls under `features`. Read [features.md](references/features.md) before enabling a control.
   - Complete when generated controls have an explicit owner and installation boundary.
4. Run `python scripts/validate_collaboration.py <target>`.
   - Complete when configuration and every enabled feature artifact validate.

## Receipt

State the scaffold scope/mode, who may integrate it, command and validation artifacts, final status, and whether owner integration is next or validation blocks adoption. Include target state, dry-run status, approved integrations, and configuration sources.

For existing-repository adoption, read [adoption.md](references/adoption.md). For the old `--roles` entry point, read [migration.md](references/migration.md). Project-specific source, data, experiments and results stay in the target repository.
