# Skill Adaptator Contract

Plans use `schema_version: "1.0"` and retain `mode`, `source`, `target`,
`adaptations`, `files`, `payload`, and `plan_sha256`. They also record
`portability`, `distribution`, `dependency_resolution`, and `residual_scan`.
Each file records a portable path, source SHA-256, rendered SHA-256, and byte
count. Replacements must match exactly once.

Portable sources may pass through unchanged. Host-adapted sources require a
recorded resolution for every declared dependency. Workspace-bound sources
require those resolutions plus a clean residual scan after reviewed
replacements, including obsolete Workspace dependencies in frontmatter.
The additive `dependency_resolution.evidence` array records source and rendered
hashes for changed files. Apply recomputes that evidence and the residual scan;
resolution descriptions are review context, not proof that content was adapted.
Legacy schema-1.0 plans remain readable; workspace-bound apply still requires
observable adaptation and no detected Workspace dependencies. The scan covers
known CLI forms, declared Workspace dependencies, and normalized host paths;
it does not prove the behavior of arbitrary dynamically constructed commands.
A plan hash covers all of these fields.

The project receipt at `.workspace/skill-adaptator/manifest.json` has
`schema_version: "1.0"` and a `managed` array. Each entry identifies one
source/target pair and contains source hash, target root, portability,
distribution, dependency resolution, residual scan, managed files,
adaptations, and plan hash. It is project data and must be committed by the
external project owner.

Authorization invokes the Workspace Python module from its source root, avoiding
Windows shell-launcher resolution. External TASK verification requires an active
`workspace_write` registration bound to the agent and exact project root. Every
apply requires `--lease PATH` with an existing capability lease; the target and
receipt are checked independently, and both must pass authorization before the
first write. The CLI rejects an omitted lease before invoking Workspace checks.
