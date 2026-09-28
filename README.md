# Anieer Skills

A generated collection of Codex skills. Portability and host requirements vary by skill; check each entry before installing.

## Related project

- [Frame-for-AI-workspace](https://github.com/AnieerLhayK/Frame-for-AI-workspace): the governed framework and source project for this collection.

## Included skills

- [`agengrator`](skills/engineering/agengrator/SKILL.md) — portability: `host-adapted`; requires: `python, windows, host-write-authorization, optional-workspace-manifest`
- [`collaboration-builder`](skills/productivity/collaboration-builder/SKILL.md) — portability: `portable`; requires: `python, pyyaml, git`
- [`disk-scan-reporter`](skills/governance/disk-scan-reporter/SKILL.md) — portability: `host-adapted`; requires: `windows, python, optional-workspace-manifest`
- [`far-repo-governor`](skills/governance/far-repo-governor/SKILL.md) — portability: `host-adapted`; requires: `python, git, github, registered-publisher`
- [`kill-for-remote`](skills/governance/kill-for-remote/SKILL.md) — portability: `workspace-bound`; requires: `windows, python, git, github, workspace-cli`
- [`mardocx`](skills/content/mardocx/SKILL.md) — portability: `portable`; requires: `python, PyYAML, python-docx, pandoc`
- [`showcase-packer`](skills/content/showcase-packer/SKILL.md) — portability: `portable`; requires: `python`
- [`skill-adaptator`](skills/engineering/skill-adaptator/SKILL.md) — portability: `workspace-bound`; requires: `python, pyyaml, git, workspace-cli, optional-workspace-manifest`
- [`skill-migrator`](skills/engineering/skill-migrator/SKILL.md) — portability: `workspace-bound`; requires: `python, PyYAML, git, workspace-cli, optional-workspace-manifest`
- [`windows-ai-storage-governor`](skills/governance/windows-ai-storage-governor/SKILL.md) — portability: `host-adapted`; requires: `windows-powershell, host-write-authorization`

Each directory is a skill source package. Read its `SKILL.md`; do not edit generated copies when a managed source is available.

## Install and use

Copy one selected `skills/<category>/<id>/` directory into your Codex skill directory, then invoke it by its frontmatter name. Check the listed host requirements first; workspace-bound skills require their documented Workspace services and are not standalone portable tools. Keep the directory intact so its scripts and references remain available.

Skills marked `internal-only` are never eligible for this public collection. The registered contract is the explicit allowlist for all other releases.

## Maintenance

This repository is generated from its managed workspace source. Propose changes against that source, update the projection boundary and tests, then regenerate the collection. Do not patch the generated repository directly; direct changes will be replaced at the next synchronization.
