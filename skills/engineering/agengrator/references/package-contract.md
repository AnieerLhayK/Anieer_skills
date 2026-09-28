# Package Contract

Agengrator synchronizes a selected payload into one output root. The agent decides what the payload means; the CLI proves which bytes were approved. Payload bytes may come from a prepared staging tree or from an in-memory composition of explicit source roots.

## Selection file

The selection file is staging input and may contain local paths. It never enters the bundle.

```json
{
  "schema_version": "1.0",
  "bundle_id": "migra-codex",
  "payload_sources": [
    {
      "source_root": "<absolute selected source path>",
      "target_root": "skills/research"
    }
  ],
  "selections": [
    {
      "id": "research",
      "kind": "skill",
      "export_mode": "exact",
      "source_id": "workspace:research",
      "license": "MIT",
      "attribution": "Required notice retained"
    }
  ]
}
```

Required values:

- `schema_version` is `1.0`.
- `bundle_id` uses lowercase letters, digits, and hyphens.
- Use exactly one materialization mode: `payload_root` for an existing prepared directory, or `payload_sources` for explicit source directories composed in memory. `payload_files` may add individual files in source-composition mode.
- Every source path is absolute, exists outside the final bundle, and remains local to the selection/plan inputs. Source paths never enter the generated manifest.
- `text_replacements` may adapt an exact target file. Each replacement must match exactly once, and the transformed UTF-8 text passes the same portability and sensitive-content scan.
- `selections` contains unique `(kind, id)` pairs.
- `export_mode` is `exact` or `adapted`.
- `source_id`, `license`, and `attribution` are non-empty logical descriptions. They must not contain local absolute paths.

## Payload

The materialized payload is the complete desired managed tree except `agengrator-manifest.json`, which the CLI writes last. In source-composition mode it is virtual: `plan` hashes transformed bytes without creating a staging directory. It must contain:

```text
START_HERE.md
SECURITY_BOUNDARY.md
skills/<selected-id>/...
plugins/RECOMMENDATIONS.md
workspace-template/...
```

Only UTF-8 text is supported in v1. Relative paths must be portable, free of `.` and `..` segments, and must not use reserved metadata names. Symlinks, junctions, and reparse points are blockers.

## Plan and approval

`plan` compares payload hashes with the previous machine manifest. It does not write the output root. A selection may be supplied by file or stdin. Its canonical JSON body produces `plan_sha256`; proposed deletions independently produce `deletions_sha256`.

`apply` accepts the reviewed plan by file or stdin and rechecks every payload hash, the current managed state, the plan hash, and any deletion hash. Unknown files are preserved, but an unknown file occupying a planned managed path is a collision and blocks the run. Updates use temporary siblings and atomic replacement. On failure, previously managed bytes are restored before the command returns.

## Bundle manifest

`agengrator-manifest.json` contains only portable facts:

- schema and bundle identifiers;
- generator name;
- logical selections with export, provenance, license, and attribution metadata;
- managed relative paths and SHA-256 hashes.

It excludes source paths, host identifiers, account data, task records, and timestamps. Excluding timestamps keeps identical bundles byte-stable.
