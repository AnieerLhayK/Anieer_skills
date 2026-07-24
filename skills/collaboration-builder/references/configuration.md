# Configuration contract

`PROJECT_CONTEXT/roles.yaml` owns role IDs, writable roots and protected paths. Keep IDs lowercase and stable; changing an ID changes commands, record paths and handoff references.

```yaml
roles:
  maintainer:
    path: ""
  delivery:
    path: team/delivery/
protected_exact: [AGENTS.md, README.md]
protected_prefixes: [scripts/, PROJECT_CONTEXT/, COLLABORATION/]
```

`PROJECT_CONTEXT/task_registry.yaml` owns task routing. Every task needs a small reading set, an explicit write scope and checks that can be run in the target repository.

```yaml
tasks:
  team_work:
    required_read: [AGENTS.md, COLLABORATION/AGENTS.md]
    write_scope: [team/]
    validation: [git diff --check]
```

Use `maintainer` only for shared governance. Give each delivery role one path prefix. Add a shared path only when its owner and review rule are written in `COLLABORATION/governance/permissions.md`.

`--ai-work <id>` expects the staged record `team/<role>/AI-records/<id>.md`. Use a stable work-item ID from the target repository; it may be an issue, milestone, feature, or research item.
