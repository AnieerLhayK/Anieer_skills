---
name: far-repo-governor
description: Govern safe module extraction from this workspace into GitHub public projections, and audit, repair, standardize, or optimize projection repositories without maintaining an independent local checkout. Use when selecting an open-sourceable module, defining a projection boundary, registering or synchronizing a managed public repository, reviewing remote repository structure, or correcting remote drift.
---

# Far-repo Governor

Use a **projection contract**: a small, reviewable declaration of what a repository must contain, what it must never contain, and how it is regenerated. Treat the workspace source as authoritative whenever it exists.

## 1. Classify the repository

Choose one path before editing.

| Path | Authority | Action |
| --- | --- | --- |
| Managed projection | Workspace source and its registered publisher | Repair the source/publisher, then regenerate and push. |
| New module projection | A selected workspace module | Define a contract, create a deterministic publisher and checker, register it, then publish. |
| Remote-only repository | The remote's documented default branch | Audit through GitHub CLI; establish or name its source of truth before changing it. |

For a managed projection, read `shared/agent_governance.yaml -> managed_platform_publishers`. Do not edit the generated checkout or the remote directly: that creates drift.

## 2. Define the boundary

Work from explicitly named source paths and a user-stated public purpose. Inventory only that bounded module and its direct runtime, test, license, and documentation dependencies.

Write a projection contract before generating files. Start from [references/projection-contract.example.json](references/projection-contract.example.json). Require:

- a repository, branch, required paths, and forbidden path prefixes;
- the smallest usable API, command entry point, or skill surface;
- installation, configuration, validation, and license material needed by an adopter;
- traceability from the generated repository to its source revision and publisher.

Keep private corpora, local paths, credentials, task records, runtime reports, cache files, and unrelated workspace governance outside the contract. Prefer a small, independently usable module over a broad workspace copy.

## 3. Build a reproducible projection

For a new projection, make the publisher and its checker part of the workspace source. The publisher must generate into a staging directory, scrub machine-specific text and excluded content, and leave the source tree unchanged. The checker must validate the contract and execute the module's relevant tests in the generated output.

Register the publisher once in `managed_platform_publishers`; use the aggregate synchronizer thereafter. Record workspace and external writes under the routed task record. Integrate source changes as required by workspace governance before publishing.

## 4. Audit a remote without cloning it

Use the included read-only auditor:

```powershell
python scripts/audit_remote.py --repo OWNER/REPO --branch main --contract references/projection-contract.example.json
```

It reads the GitHub tree through `gh api`, checks required, forbidden, size, and top-level structure rules, and produces JSON. A failing contract is evidence for a source/publisher repair; a warning is a candidate for a documented structural improvement.

For content-level review, fetch only the named public files with `gh api repos/OWNER/REPO/contents/PATH`, then compare them to the projection contract and source. Never substitute a broad remote download for a boundary review.

## 5. Correct and publish

For managed repositories, change the source and publisher, validate the generated staging output, then run every registered public publisher with the task record ID. Confirm the published remote revision and run its CI.

For remote-only repositories, first record the exact repository, branch, owner authorization, and intended file set. Make a small, reviewable GitHub API commit or pull request only after the audit is clean and the change has a stated source of truth. Re-audit the resulting commit. If recurring maintenance is needed, migrate the repository to a managed projection rather than accumulating direct remote patches.

## Completion criteria

Finish only when the projection contract passes against the generated staging output and the target remote; required functionality tests pass; the public tree contains no excluded material; and the remote default branch or pull request identifies the published source revision. Report skipped optional improvements separately.

## Validation

Run from this skill directory:

```powershell
python -m unittest discover tests
python scripts/audit_remote.py --help
```
