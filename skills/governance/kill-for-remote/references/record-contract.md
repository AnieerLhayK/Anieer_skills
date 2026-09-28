# Remote-only record contract

`remote_only_repositories.yaml` is JSON-formatted YAML so the runtime can use
the standard library without a new dependency. Validate it against
`remote_only_repositories.schema.json` before a bulk repair.

Each repository has a stable lowercase-hyphen ID, a GitHub HTTPS URL, default
branch, original absolute local path, status, and restore guidance. The
`verification` object contains only a status, commit, timestamp, and failure
code. Never store command text, access tokens, credentials, or raw subprocess
output.

`pending_retirement` is an intention or an incomplete operation, not permission
to delete. `remote_only` means the local path was verified absent after a
successful recycle-bin operation and registry cleanup.

`local_directory_retired` means the Git checkout was retired but its original
path was recreated as a non-Git local resource directory. Its
`local_directory_receipt` records retained relative paths, count, hash-manifest
digest, and recreation time; it must not imply that source code remains local.

When a retirement preserves risk-screened ignored resources, the optional
`resource_receipt` records each source-relative candidate, disposition,
file count, total bytes, and (for preserved material) exact destination,
hash-manifest digest, and completion time. It is written only after the
checkout has been successfully retired.
