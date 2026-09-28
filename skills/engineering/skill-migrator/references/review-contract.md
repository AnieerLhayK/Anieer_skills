# Review Contract

Use this contract before either migration branch. It is the decision gate and
receipt schema, not a new durable record.

## Candidate matrix

Show one row per discovered candidate with:

- upstream path, name, purpose, and fixed revision;
- license evidence and attribution requirement;
- overlap with registered skills or platform-provided capabilities;
- resources, dependencies, state paths, and external-service assumptions;
- privacy or sensitive-material risk;
- proposed `external-skills/<category>/<skill-id>` destination;
- proposed role, authority, execution modes, invocation policy, and platforms;
- adaptation delta, validation approach, and recommendation.

Use only `engineering`, `governance`, `productivity`, `content`, or
`experimental` as the function category. Mark each candidate `migrate`,
`defer`, or `reject`, with a reason. Ask the user to confirm the exact migrate
rows and their proposed destination and exposure. The gate is closed until
that answer is explicit.

## Hard stops

- The checkout has no stable Git revision, declared remote, or usable tracking
  comparison for a branch checkout.
- The worktree is dirty, ahead of or behind its tracking ref, or would need a
  reset or overwrite. A detached fixed revision is recorded as non-tracking
  evidence rather than treated as a branch.
- License or attribution requirements cannot be determined.
- A symlink escapes the source root, or sensitive/private material may be
  copied.
- The package has no valid `SKILL.md`, or its runtime dependencies cannot be
  supported safely.
- An update cannot distinguish upstream change from the retained Workspace
  adaptation.

## Audit receipt

Use the existing task record and ledger as the durable receipt. Report:

- mode and effective authorization;
- source URL/path and old/new revision where applicable;
- selected, deferred, and rejected candidates;
- license and attribution evidence;
- source and destination paths plus adaptation delta;
- role, authority, execution modes, invocation policy, and exposures;
- validation and platform discovery evidence;
- task record, outcome state, and the stop or next-step condition.

Do not create a parallel provenance or migration-receipt file.
