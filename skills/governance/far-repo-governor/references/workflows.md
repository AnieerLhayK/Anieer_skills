# Projection Workflows and Authority

## Select the target

Read `managed_platform_publishers` in `shared/governance/agent_governance.yaml`. Select only an entry named by the user or directly implicated by the requested source change. Use its publisher script, staging path, remote URL, contract, and license fields as applicable. Do not maintain a second repository list.

For the selected entry, inspect only its synchronizer, generator, checker, tests, and the source README/template that owns generated documentation. Script-generated README prose lives in `scripts/publishing/readme_templates/`; follow the selected generator to the specific template. The QQ filter README is already source-owned in its package and is copied from there. Treat an entry as a source-to-remote projection unless the user explicitly identifies the remote as authoritative for this operation and that choice is recorded in the receipt.

## Create or register a projection

First prepare the source module, generator/checker plan, and a concrete path contract using [the example contract](projection-contract.example.json) as a format reference. Before creating a GitHub repository or adding a target to the registry, show that proposal and get user authorization for the exact owner/repository, visibility, authoritative source, and allowed content paths. Public is the default visibility. The authorization covers only that named target and path set.

Establish one source module, a generator, a checker, focused tests, a registered staging path, and one registered remote. Keep the contract as the path authority. Generate in disposable staging, run its checker and relevant tests, and confirm the remote contents match the contract before reporting completion. Do not include private data, local/task/cache/report/governance state, machine-specific paths, or unrelated neighboring repository content.

## Maintain a registered projection

Edit the authoritative source, README template, generator, checker, contract, or tests in the workspace. Generated staging and remote files are outputs. If the requested change adds material outside the current contract, show the proposed paths and reason and wait for explicit authorization before changing the contract or publishing them.

When the main source changes, inspect the current diff and trace affected paths through the selected publisher and contract. Report the matching projections and suggest useful content additions; do not silently broaden any projection. Run the registered aggregate synchronizer only after required source integration and with its existing active task record and external-write checks.

## Temporary preview

Preview a registered projection on a temporary branch in its registered remote. Select its publisher explicitly and run the aggregate synchronizer in an interactive terminal, for example `python -m scripts.publishing.sync_public_projections --publisher <registered-id> --record-id <TASK-ID> --preview`. The synchronizer generates and verifies in disposable staging, creates a unique `codex-preview/<random>` branch only if that exact remote ref is absent, and prints the branch for inspection. After inspection it deletes only the branch created by this run, using a ref lease so concurrent changes stop cleanup instead of deleting someone else's update. If remote state is ambiguous, it attempts a guarded deletion at this run's commit; if that cannot be confirmed or the branch moved, it reports the branch name and leaves it untouched for safe follow-up. `--force-dirty` permits a preview from uncommitted source changes; previews still require registered publisher authorization and never update the remote's default branch.

## Remote-only repository

If a remote has no registered source, audit and classify it before proposing any edit. Do not infer that it is disposable. With explicit user authorization, record it as an independent authoritative source in its owning repository workflow and hand off ongoing code and documentation maintenance there. Do not misregister it as a generated publisher or overwrite it through a projection synchronizer.

## Completion receipt

Report the selected publisher and mode, authoritative source and remote revisions, contract and validation results, local staging cleanup status when applicable, and any proposed projection expansion or authorized next action. A failed check, ambiguous source, or authorization denial is an incomplete operation.
