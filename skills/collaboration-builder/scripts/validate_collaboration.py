"""Read-only validation for a collaboration-builder scaffold."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install PyYAML before validating a collaboration scaffold.") from exc


REQUIRED = (
    "AGENTS.md", "README.md", "COLLABORATION/AGENTS.md", "PROJECT_CONTEXT/roles.yaml",
    "PROJECT_CONTEXT/task_registry.yaml", "scripts/resolve_task_context.py", "scripts/check_change_scope.py",
)


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"Expected a mapping: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    root = args.target.resolve()
    errors = [f"missing {item}" for item in REQUIRED if not (root / item).exists()]
    if errors:
        print("\n".join(f"[ERROR] {item}" for item in errors))
        return 1
    try:
        roles = load_yaml(root / "PROJECT_CONTEXT/roles.yaml").get("roles", {})
        tasks = load_yaml(root / "PROJECT_CONTEXT/task_registry.yaml").get("tasks", {})
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"[ERROR] invalid configuration: {exc}")
        return 1
    if "maintainer" not in roles:
        errors.append("roles.yaml lacks the maintainer role")
    for role, config in roles.items():
        if not isinstance(config, dict) or "path" not in config:
            errors.append(f"role {role} lacks path")
    for task_id, task in tasks.items():
        if not isinstance(task, dict) or not all(key in task for key in ("required_read", "write_scope", "validation")):
            errors.append(f"task {task_id} lacks required_read, write_scope, or validation")
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".yaml", ".yml", ".txt"} and "{{" in path.read_text(encoding="utf-8"):
            errors.append(f"unresolved placeholder in {path.relative_to(root)}")
    if errors:
        print("\n".join(f"[ERROR] {item}" for item in errors))
        return 1
    print(f"[PASS] collaboration scaffold valid: {root}")
    print(f"[PASS] roles={', '.join(sorted(roles))}; tasks={', '.join(sorted(tasks))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
