# Intake Branch

Read this file only after the review gate selects new candidates.

1. Confirm the raw checkout is the reviewed clean revision. A missing checkout
   may be cloned to the exact manifest-owned raw-skills location only under an
   active `cleanup_migration` record with `external_write`. Preserve an
   existing path and stop on identity or state conflicts.
2. Create each destination under `external-skills/<category>/<skill-id>/`.
   Copy only the selected skill package and resources required by its live
   instructions. Keep license notices and attribution; exclude repository
   administration, unrelated skills, caches, generated output, credentials,
   private corpora, and upstream Git metadata.
3. Adapt the package to Workspace facts. Resolve paths through the manifest,
   keep writes in owned source or state roots, separate role from authority and
   execution mode, and convert platform-specific invocation or tool assumptions
   deliberately. Preserve upstream meaning unless a documented Workspace
   boundary requires a change.
4. Add or update the source row in
   `PROJECT_CONTEXT/todo/external-skills.md` and its license section in
   `external-skills/THIRD_PARTY_NOTICES.txt`. Record the reviewed revision,
   selected paths, adaptations, status, and next action once.
5. Register one source path and all confirmed platform projections in
   `workspace_manifest.yaml`. Create projections only through the manifest
   lifecycle commands, first as a dry run and then with the already confirmed
   platform scope.

The intake is complete when every selected file has an upstream or adaptation
reason, all required resources are registered, the evidence chain identifies
the reviewed revision, and every requested platform resolves to the same
Workspace source.
