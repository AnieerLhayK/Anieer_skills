# Merge and branch synchronization

1. Run `git fetch --prune` and `git status --short --branch`; inspect remote commits before integrating.
2. Start from current default branch on a temporary integration branch. Merge one reviewed branch with `--no-ff`.
3. Resolve conflicts by artifact responsibility and evidence; run relevant checks after each important merge.
4. Advance and push the default branch only after validation. Fast-forward a collaboration branch only after confirming it has no unintegrated commits.
5. Preserve remote history; stop when a push is rejected or the remote state is uncertain.
