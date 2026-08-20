---
name: far-repo-governor
description: "Source-to-GitHub projection governance. Use when contracts, registered publishing, remote audit, or drift repair are needed."
---

# Far-repo Governor

Use a one-way chain: **authoritative source -> disposable staging -> registered publisher -> remote**. A public projection is generated output, not an editable source.

## Authority

| Repository | Authority | Required path |
| --- | --- | --- |
| Managed projection | Registered source and publisher | Repair source/publisher, regenerate, publish. |
| New projection | Named source module | Define contract, publisher, checker, register, publish. |
| Remote-only | No registered source | Establish contract, staging, checker, publisher, and source first. |

Read `shared/governance/agent_governance.yaml -> managed_platform_publishers`. Managed staging and remotes are generated outputs. Publish only with a routed task record and external authority.

## Run

1. Define or read [the contract](references/projection-contract.example.json): permitted paths, usable surface, adopter materials, and public-safe provenance. Exclude private material and local/task/report/cache/governance data. Complete when the checker has an authoritative contract.
2. Generate in disposable staging; keep source unchanged, scrub excluded/machine-specific content, and run the checker and relevant tests. Keep discoverability links in the contract or generator. Complete when staging satisfies the contract.
3. Audit named public content without broad cloning:

   ```powershell
   python scripts/audit_remote.py --repo OWNER/REPO --branch main --contract references/projection-contract.example.json
   ```

   Complete when the audit is `PASS`, or a `WARN`/`FAIL` has its required decision or repair.

4. Publish after required source integration. Use the registered aggregate synchronizer, then confirm remote revision and CI. `FAIL` requires source/publisher repair; `WARN` requires a recorded decision before release. Complete when the remote satisfies the contract.

## Receipt

State projection scope/mode and publisher authority, task-record and contract/audit artifacts, source/staging/remote revisions with CI, release status, and the repair or authorized next publishing action.

## Validate

Run `python -m unittest discover tests` and `python scripts/audit_remote.py --help`.
