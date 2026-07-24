# AI collaboration entry

Read this file and the root README before work. Run `git status --short --branch` before a material task.

- Work on the user-selected non-default branch; use a task branch when no branch is supplied.
- Resolve the task before changes: `python scripts/resolve_task_context.py <task_id>`. Read every `required_read` item and write only inside `write_scope`.
- Read in order: root `AGENTS.md` → `COLLABORATION/AGENTS.md` → role `AGENTS.md` → role `CLAUDE.md` (a pure reference).
- Keep project facts in their role area. Use a handoff or explicit authorization for a cross-role change.
- Before commit, run `python scripts/check_change_scope.py --task <task_id> --role <role> --staged`. Explain each warning; warnings are advisory.
- For an AI stage that changes project facts, add `--ai-work <work-item>` and stage `team/<role>/AI-records/<work-item>.md`.
- Treat root rules, shared scripts, task routing, CI and ignore rules as maintainer work. Read `COLLABORATION/governance/` before changing them.
- Before merge or branch synchronization, read `COLLABORATION/governance/merge.md`; review one branch at a time and verify after each merge.
- Finish with changed areas, validation, risks, commit status and push status.
