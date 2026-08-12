---
name: far-repo-governor
description: Govern safe extraction from an authoritative source into GitHub projections. Use for projection boundaries, registered publishers, remote audits, and projection drift.
---

# Far-repo Governor

Treat an existing source tree as authoritative. A public projection is a generated artifact, not a second editable source.

## Choose the path

| Repository | Authority | Action |
| --- | --- | --- |
| Managed projection | Registered source and publisher | Repair source/publisher, regenerate, then publish. |
| New projection | Named source module | Define a contract, publisher, checker, register, then publish. |
| Remote-only | Declared remote branch | Audit first; record its source of truth before editing. |

For a managed projection, read `shared/governance/agent_governance.yaml -> managed_platform_publishers`. Never patch its generated checkout or remote directly.

## Define and generate

Start from [references/projection-contract.example.json](references/projection-contract.example.json). A contract names the repository and branch, required and forbidden paths, smallest usable surface, adopter-facing docs/license/tests, and source revision/publisher traceability. Exclude private corpora, credentials, local paths, task records, reports, caches, and unrelated governance.

Generate into disposable staging. The publisher must scrub machine-specific or excluded content, leave the source tree unchanged, and run a contract checker plus relevant tests. Register the publisher once; use the aggregate synchronizer thereafter. Record workspace and approved external writes under the routed task record.

## README discoverability

When a projection has a related, parent, or source repository that users should discover, generate a short, visible README link to it. State the relationship plainly and keep the link in the projection generator or contract—never as a hand patch to generated output. Do not expose private source locations or imply a relationship that the registered contract cannot support.

## Audit and publish

Audit without cloning broadly:

```powershell
python scripts/audit_remote.py --repo OWNER/REPO --branch main --contract references/projection-contract.example.json
```

Use `gh api` only for named public files when content review is needed. A failed audit requires a source/publisher repair; a warning needs a documented decision.

For managed repositories: change source and publisher, validate staging, integrate as required by workspace governance, run the registered publisher with its record ID, then confirm the remote revision and CI. For remote-only repositories, record owner authorization, branch, source of truth, and exact file set before a small reviewable API commit or PR; re-audit afterward.

Finish when generated staging and remote satisfy the contract, relevant tests pass, excluded material is absent, and the published revision identifies its source. Run:

```powershell
python -m unittest discover tests
python scripts/audit_remote.py --help
```
