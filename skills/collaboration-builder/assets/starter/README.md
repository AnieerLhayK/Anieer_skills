# {{PROJECT_NAME}}

## Start here

1. Run `git status --short --branch`.
2. List routes with `python -m scripts.workspace.resolve_task_context --list`, then resolve one task ID.
3. Read root rules, `COLLABORATION/AGENTS.md`, and your role rules.
4. Work inside your role root; use a handoff for facts another role must rely on.

## Operating model

Roles: {{ROLE_NAMES}}. The maintainer owns shared governance. `PROJECT_CONTEXT/` routes AI work; `COLLABORATION/` owns common policy and handoff templates; `team/` contains role-owned project work.

The scope checker warns about accidental cross-area changes. It does not replace review or authorization.
