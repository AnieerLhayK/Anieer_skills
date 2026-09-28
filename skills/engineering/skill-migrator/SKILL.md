---
name: skill-migrator
description: Migrate or synchronize reviewed external skills into this Workspace.
disable-model-invocation: true
metadata:
  portability: workspace-bound
  distribution: review-required
  requires: [python, PyYAML, git, workspace-cli, optional-workspace-manifest]
---

# Skill Migrator

Move an external skill through a review gate into the Workspace adaptation
layer. The external checkout is evidence; `external-skills/` is the editable
source; platform projections are installed views.

## Run

1. Fix the mode and source. Use `intake` for a new source and `update` for an
   existing adaptation. Accept an exact Git checkout or URL whose revision can
   be pinned. For a URL or checkout refresh, propose the exact path under
   `workspace_manifest.yaml -> external_roots.raw_skills` and obtain a
   `cleanup_migration` record with `external_write` before changing it.
2. Resolve this skill's installed or source directory and run its bundled
   read-only inventory by absolute path:

   ```text
   python <skill-directory>/scripts/inventory_external_skills.py --source <checkout> --format json
   ```

   Continue only from a clean checkout with a remote, fixed revision, license
   evidence, and valid `SKILL.md` candidates. Inspect the license text and the
   candidate contents; the inventory deliberately makes no compatibility
   decision.
3. Read [references/review-contract.md](references/review-contract.md). Compare
   every candidate with the manifest and current skill sources, present the
   matrix, and wait for the user to confirm the exact candidates, categories,
   invocation policies, and platforms. No migration write precedes this gate.
4. After confirmation, create an active `skill_architecture_update` record and
   work in an isolated Git worktree. For a new adaptation read
   [references/intake.md](references/intake.md); for an upstream refresh read
   [references/update.md](references/update.md). The branch is complete only
   when every selected candidate and every retained local adaptation is
   accounted for.
5. Update the existing evidence chain: the external-skill queue, third-party
   notices, adapted source, manifest registration, and task record. Validate
   each source package, manifest/protocol contracts, requested platform
   discovery, projection links, focused behavior, and Git diff before applying
   the confirmed local projections.
6. Return the audit receipt defined in the review contract. Treat `main`
   integration and public publication as separate approvals; route registered
   remote publication to `far-repo-governor`.

## Stop conditions

Apply every hard stop in the review contract. Return the evidence gathered and
the next safe action while preserving the checkout, current adaptation, and
projections in place.
