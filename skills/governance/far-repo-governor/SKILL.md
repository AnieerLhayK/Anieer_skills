---
name: far-repo-governor
description: "Govern GitHub projections when creating or registering a target, maintaining a registered projection, auditing remote drift, or previewing a source change."
metadata:
  portability: host-adapted
  distribution: review-required
  requires: [python, git, github, registered-publisher]
---

# Far-repo Governor

Use the registered publisher table in `shared/governance/agent_governance.yaml` as the only target registry. The default authoritative source is this workspace; accept a different source when the user names one.

For setup, registered maintenance, temporary previews, and remote-only repositories, read [the workflow and authority rules](references/workflows.md). For a requested audit, read [the remote audit procedure](references/remote-audit.md).

When this skill runs for a main-source change, compare the changed paths with the selected generator, contract, and checker. Recommend any useful projection expansion with its rationale; get authorization before adding public paths or content. Publish only through the registered aggregate synchronizer with the active task record and external-write authority.
