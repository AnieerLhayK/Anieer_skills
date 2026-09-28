---
name: kill-for-remote
description: Retire a verified local GitHub checkout while preserving a remote-only record.
argument-hint: "<registered repository id>"
disable-model-invocation: true
metadata:
  portability: workspace-bound
  distribution: review-required
  requires: [windows, python, git, github, workspace-cli]
---

# Kill for Remote

Use this Skill only when the user explicitly invokes `$kill-for-remote` for a
registered external repository. Its **retirement gate** preserves a GitHub
repository and removes a local checkout only after a separate confirmation.

## Authority

The registry at `PROJECT_CONTEXT/references/remote_only_repositories.yaml` is
the authoritative remote-only record. `project_roots.json` remains a
machine-local launcher map, and `external_projects.yaml` remains a registry of
active local projects.

Start in audit mode. Enter apply mode only after all of the following are
present:

1. An active `cleanup_migration` task record with `workspace_write` and the
   exact binding `retirement-target=<canonical-checkout-path>`.
2. An allowed agent capability check for the environment write.
3. A successful current audit and its fingerprint.
4. A later user message that repeats both the repository ID and canonical path.

Read [the safety policy](references/safety-policy.md) before an apply request.
Read [the record contract](references/record-contract.md) when adding or
repairing a registry entry.
Read [the resource disposition contract](references/resource-disposition.md)
when audit reports ignored-resource candidates.

## Run

1. Resolve the registry ID and run `scripts/retire_repository.py audit`.
   Report the canonical path, GitHub default branch, fingerprint, and every
   blocked condition. Audit never writes or fetches.
2. If audit reports ignored-resource candidates, stop and give the user its
   disposition template. The user may explicitly invoke `$grill-me` to judge
   preservation value, then return a validated resource disposition plan.
   Do not infer a preserve destination or continue with an unresolved candidate.
   Use `inventory` only when the user needs to name a small ignored path for
   local retention; ordinary audit remains aggregated.
3. Stop unless the audit is `ready`. Do not repair local branches, push refs,
   or alter a checkout as part of retirement.
4. After the later exact confirmation and task/agent gates, rerun the audit.
   When candidates exist, require the current disposition-plan digest as part
   of that confirmation and pass it through `--confirm-resource-plan-sha256`.
   Call `apply` with the same ID, path, fingerprint, and plan. In the explicit
   `--retirement-mode local-directory`, retained ignored files are copied and
   hash-verified to a sibling staging directory before the checkout enters the
   Recycle Bin; the original path is then recreated as a non-Git local directory.
   Otherwise preserved resources are copied and hash-verified before the checkout
   enters the Windows Recycle Bin; then exact launcher/external-project cleanup
   and the final receipt are written.
   Runtime validates the task type, operation, exact target binding, registry
   write authorization, repository ID/path, current fingerprint, and approved
   resource-plan digest before resource copying, registry mutation, or recycle.
5. Return the receipt: status, GitHub URL, default branch, preflight commit,
   resource actions, removed launcher keys, migrated external-project key, and
   a restore command.

`apply` never accepts a shell command, wildcard, parent directory, or model
output as executable syntax. It rejects links, junctions, workspace-contained
targets, non-Git roots, unverified GitHub remotes, and changed preflight state.

## Completion

An audit is complete when its result is either `ready` with a fingerprint or
`blocked` with named reasons. A retirement is complete only when the original
path is absent, the record is `remote_only`, and launcher/external-project
registries no longer describe that local checkout. A failed apply remains
`pending_retirement` with a non-sensitive failure code and restore guidance.
For `local-directory`, completion instead requires `local_directory_retired`:
the original path exists as a non-Git directory containing only the explicitly
retained ignored files.
