# Retirement safety policy

The retirement gate is deliberately narrower than ordinary cleanup.

- Accept only an existing registry ID and its recorded exact checkout path.
- Require a normal Git checkout whose top-level directory equals that path.
  Reject drive roots, the workspace and its descendants, symbolic links, and
  junctions.
- Require a clean worktree, an accessible GitHub `origin`, a resolvable remote
  default branch, local HEAD equal to that remote branch, and no local branch
  or tag absent from the remote.
- Treat a changed fingerprint, Git error, unavailable remote, or unparseable
  metadata as a block. Do not silently degrade the audit.
- Use only the bundled parameterized recycle-bin adapter. Never construct a
  shell command from a registry field, Git output, or model output.
- Apply removes only launcher entries and external-project entries whose
  normalized local path exactly equals the retired checkout. It does not scan
  other files or directories.
- Ignored-resource audit reads only Git's ignored-file list and filesystem
  metadata. It never reads resource contents during audit.
- A preservation plan must cover every reported candidate. Each preservation
  destination is an explicit, absent absolute path outside the checkout and is
  included in the approved environment-write scope.
- Copy only regular files that Git still confirms as ignored. Reject links,
  junctions, reparse points, changed candidate inventories, existing targets,
  and tracked files. Hash every source and copy before publishing the target.
- A failed copy leaves the checkout intact. Keep the staging path for recovery;
  do not remove a partial preservation attempt automatically.
- `local-directory` is an opt-in retirement mode. It may recreate the original
  path only after the checkout is confirmed absent from the Recycle Bin action.
  The recreated path must be a normal directory with no `.git` entry and only
  the hash-verified paths listed in its local-directory receipt.

The user may restore manually with the recorded GitHub URL and default branch.
The Skill does not clone, permanently delete, or alter the remote repository.
