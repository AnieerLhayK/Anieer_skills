# Update Branch

Read this file only after the review gate selects existing adaptations for an
upstream refresh.

## Three-way adaptation merge

For each selected skill, establish three inputs:

1. the previous upstream revision recorded in the queue or third-party notice;
2. the new clean upstream revision;
3. the current Workspace adaptation.

Compare old upstream to new upstream to identify the upstream delta, then old
upstream to the adaptation to identify the local delta. Apply only compatible
upstream changes to the adaptation. Preserve Workspace authority, execution
mode, path, state-root, invocation, projection, and privacy decisions unless
the user explicitly changes them.

Account for added, changed, renamed, and removed upstream resources. A removed
upstream file stays only when a current instruction or recorded adaptation
still owns it. A new dependency remains outside the adaptation until its
availability and authority are verified.

Update the existing queue row and third-party notice in place with the new
revision and adapted path set. Keep historical revision notes needed to explain
retained files that no longer exist upstream. Re-run each focused behavior test
and every affected platform discovery check.

The update is complete when every upstream delta is absorbed, intentionally
retained, or rejected with evidence, and the adapted skill remains within its
previous contract except for user-approved changes.
