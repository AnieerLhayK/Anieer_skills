# Ignored-resource disposition

Read this reference only when `audit` returns `resource_candidates`.

Audit groups Git-confirmed ignored regular files by their top-level
repository-relative path. A group becomes a candidate when it totals at least
1 GiB or has a model, checkpoint, dataset, data, weight, or archive signal.
The inventory reports paths, type hints, counts, and sizes; it does not read
file contents.

Kill for Remote cannot call `$grill-me`. Give the audit's template to the user;
they may explicitly invoke `$grill-me` to decide each candidate's value. The
returned JSON must validate against `resource-disposition.schema.json` and
cover every candidate exactly once.

Use `recycle` for material that may enter the Recycle Bin with the checkout.
Use `preserve` only with an explicit, currently absent absolute
`destination_path`; it denotes the new directory holding that candidate's
ignored files. The copy is staged beside that destination, verified with a
SHA-256 manifest, then atomically published. No default archive root exists.

The plan is current only for its repository ID, canonical checkout path, audit
fingerprint, and resource fingerprint. A later apply must re-audit and receive
the user's separate confirmation containing the ID, canonical path, and plan
digest. Pass that digest using `--confirm-resource-plan-sha256`.

## Local directory retirement

`--retirement-mode local-directory` is explicit and uses a v1.1 plan. It
recycles the whole checkout, then recreates the original path as a non-Git
directory. Candidate actions are `recycle` or `retain_local`. Use
`local_retained_paths` only for smaller paths that were not risk candidates.

Run `inventory` when a user needs to select those smaller paths: it lists only
Git-confirmed ignored regular files with relative paths and metadata. The v1.1
plan binds the audit, candidate, and complete ignored-inventory fingerprints.
All retained paths are copied to a sibling staging directory and SHA-256
verified before the checkout is recycled. Paths must not overlap and may not
name tracked files, links, junctions, or anything outside the checkout.
