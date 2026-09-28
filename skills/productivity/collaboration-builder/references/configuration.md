# Configuration

Use an external YAML for first bootstrap. The generated target then owns the normalized `.collaboration.yaml`.

```yaml
schema_version: 1
layout: nested-project-cells
variables:
  workspace: sample
roles:
  - id: role-a
  - id: role-b
governance:
  root: governance
  protected_prefixes: [shared]
tasks:
  role_work:
    required_read: [AGENTS.md]
    write_scope: ["{role_path}/"]
    validation: [git diff --check]
features:
  ai_records: {enabled: false}
  work_session_lock: {enabled: false}
  git_hooks: {enabled: false}
```

Layout IDs are `isolated-areas`, `nested-project-cells`, `shared-core`, and `delivery-streams`. Layout files under `config/layouts/` define only English path templates. `custom` requires `custom.role_path`, for example `work/{project}/areas/{role}`, and may declare `custom.shared_roots`.

Roles use lowercase English IDs. A role may supply variables used by its path template, such as `stream`. Paths must be target-relative and cannot contain `..`. `governance.root` defaults to `governance` and may be overridden with another safe relative path.

`tasks` is the task-route mapping. Each entry requires non-empty `required_read`, `write_scope`, and `validation` lists. Omit it to use the generated `governance_update` and `role_work` routes.
