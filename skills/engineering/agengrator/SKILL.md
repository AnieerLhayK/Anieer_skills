---
name: agengrator
description: Build a review-gated portable Codex handoff bundle from an explicit whitelist.
disable-model-invocation: true
metadata:
  portability: host-adapted
  distribution: review-required
  requires: [python, windows, host-write-authorization, optional-workspace-manifest]
---

# Agengrator

Maintain a cross-platform, text-only Codex handoff bundle. The **review gate** is the invariant: inventory and planning are read-only; every external write matches an approved plan hash.

## Run

1. Resolve the explicit workspace root, explicit skill roots, and output root. Default the output to `${LOCAL_PATH}` only on this host. Read [safety-policy.md](references/safety-policy.md) before inspecting candidates. Complete when every read root and exclusion is visible to the user.
2. Run `inventory` and present candidates without reading session, cache, credential, private-project, or character/style-corpus roots. Ask the user for an exact whitelist and export mode for each item. `agengrator` itself is a candidate only when explicitly requested. Complete when the whitelist is explicit.
3. Define the desired payload from an approved staging tree or explicit source roots composed in memory. Prefer in-memory composition when staging writes are not authorized. Copy self-contained text skills faithfully; create a portable adaptation when local paths or dependencies remain. Seed bundle guidance from `assets/`, and record logical provenance, license, attribution, and adaptation status in the selection. Read [package-contract.md](references/package-contract.md) for the selection schema and payload layout. Complete when every materialized file is UTF-8 text and every selection has provenance and license metadata.
4. Run `plan`. A blocker leaves the current bundle untouched. Show creates, updates, unchanged files, collisions, and proposed deletions plus the plan SHA-256. Complete when the user has reviewed the exact plan.
5. Enter `environment_write` only after the user approves that plan and the host's task-record and authorization checks allow the output root. Run `apply` with the approved plan hash; pass the separate deletion hash only when the user explicitly approved those deletions. Complete when the exact approved plan applied or the previous managed state was restored.
6. Run `validate`, then report the bundle entrypoint, selected items, exact/adapted modes, managed-file count, and validation result. Complete when hashes, relative paths, review-gate text, and the machine manifest all pass.

## Commands

Run from this skill directory:

```powershell
python scripts/agengrator.py inventory --workspace-root <root> --skill-root <root>
python scripts/agengrator.py plan --selection <selection.json> --output-root <bundle> --plan-file <plan.json>
python scripts/agengrator.py apply --plan <plan.json> --approve-plan-sha256 <sha256> [--approve-deletions-sha256 <sha256>]
python scripts/agengrator.py validate --output-root <bundle>
```

Use `--selection-stdin` or `--plan-stdin` instead of the corresponding file option when local control-file writes are outside the approved boundary.

Use `python -m unittest discover tests` and the workspace validators when maintaining this skill.
