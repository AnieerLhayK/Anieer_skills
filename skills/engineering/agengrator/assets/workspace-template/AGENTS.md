# Project Agent Rules

Read the project entrypoint, local agent rules, current status, and version-control state before editing. Resolve discoverable facts from the project and ask the user only for decisions that change the result.

Keep reads bounded to the current task. Preserve existing user changes. Present an impact and validation plan before configuration, migration, external-service, deletion, or other high-risk work. Apply only approved scope, validate in proportion to risk, and finish with evidence, limits, and the next condition.

Detailed optional guidance belongs under `shared/`; durable task context belongs under `PROJECT_CONTEXT/`.
