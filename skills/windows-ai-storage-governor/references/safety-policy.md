# Safety Policy

## Approval Gates

| Mode | Default authority | Confirmation |
| --- | --- | --- |
| `audit` | Read paths and metadata | No mutation approval |
| `plan` | Write an optional report only | Confirm report path if outside task workspace |
| `apply` | Execute approved migration actions | Approve exact plan or action IDs |
| `verify` | Read paths, settings, and link targets | No mutation approval |
| `cleanup` | Remove approved stale originals or artifacts | Separate exact-path confirmation |

Approval for `apply` does not approve `cleanup`.

## Mutation Rules

- Explain source risk, target risk, downtime, rollback, and verification first.
- Compare current source state with the plan before every action.
- Preserve stable junctions and symlinks unless the approved action repairs that exact link.
- Prefer native tool configuration or environment variables over filesystem links.
- When a link is necessary, copy or synchronize to a new target, validate it, preserve
  the original, then create the link only after the source path is safely vacant.
- Never merge into an unexpected non-empty target.
- Never use broad wildcards for delete, move, rename, archive, or overwrite.
- Never mutate project source, private corpus, `Users`, or `AppData` as a whole.

## Irreversible Actions

Mark an action `irreversible: true` when rollback cannot restore the same bytes,
metadata, permissions, or tool state. Do not execute it through normal `apply`.
Require cleanup confirmation and a backup or an explicit backup waiver.

## Stop Conditions

Stop when:

- The path purpose is `unknown`.
- The source or target changed after planning.
- A destination contains unplanned data.
- A link target differs from the planned target.
- Free space, permissions, or command availability is insufficient.
- Verification fails after an action.
