# Adoption and upgrade notes

For an existing repository, generate the scaffold into an empty sibling directory first. Compare its root `AGENTS.md` and `README.md` with the repository's existing entries, then merge only the collaboration block. Preserve existing release, security and CI requirements when they are stricter.

Add `PyYAML` to the repository's development dependency mechanism before using the route and scope scripts. Add CI only after local route validation is stable; a useful first CI command is:

```text
python -m unittest discover -s scripts/tests -p "test_*.py"
```

The starter is intentionally advisory. If a mature repository needs blocking enforcement, add protected-branch rules or a CI status check after the team has observed and classified its warning patterns. Keep the warning report even after adding enforcement.

Upgrade by changing configuration first, then scripts only when the configuration model cannot express the new rule. Keep a migration note in the target repository when a role ID, work root, or record format changes.
