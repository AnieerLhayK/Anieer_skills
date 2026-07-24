# Ownership and permissions

| Area | Owner | Change condition |
| --- | --- | --- |
| Root rules, routing, shared scripts, CI and ignore policy | maintainer | explicit governance task and review |
| `team/<role>/` | named role | task route, provenance and validation |
| Shared facts | named owner | handoff, task board entry or explicit authorization |

Keep each role's writable root in `PROJECT_CONTEXT/roles.yaml`. Add a shared writable path only with an owner and review rule.
