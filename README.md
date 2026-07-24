# Anieer Skills

A portable, generated collection of independently usable Codex skills.

## Included skills

- [`collaboration-builder`](skills/collaboration-builder/SKILL.md)
- [`disk-scan-reporter`](skills/disk-scan-reporter/SKILL.md)
- [`far-repo-governor`](skills/far-repo-governor/SKILL.md)
- [`windows-ai-storage-governor`](skills/windows-ai-storage-governor/SKILL.md)

Each directory is a skill source package. Read its `SKILL.md`; do not edit generated copies when a managed source is available.

## Install and use

Copy one selected `skills/<id>/` directory into your Codex skill directory, then invoke it by its frontmatter name. Keep the directory intact so its scripts and references remain available.

## Maintenance

This repository is generated from its managed workspace source. Propose changes against that source, update the projection boundary and tests, then regenerate the collection. Do not patch the generated repository directly; direct changes will be replaced at the next synchronization.
