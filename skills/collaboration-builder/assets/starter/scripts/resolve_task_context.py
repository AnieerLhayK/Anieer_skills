"""Print a read-only task route from PROJECT_CONTEXT/task_registry.yaml."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


REGISTRY = Path("PROJECT_CONTEXT/task_registry.yaml")


def as_list(value: Any) -> list[str]:
    return [] if value is None else [str(item) for item in value] if isinstance(value, list) else [str(value)]


def root_from(start: Path) -> Path:
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / ".git").exists() and (candidate / "AGENTS.md").exists():
            return candidate
    raise SystemExit("Run inside a repository containing .git and AGENTS.md.")


def load(root: Path) -> dict[str, Any]:
    with (root / REGISTRY).open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data.get("tasks"), dict):
        raise SystemExit(f"Invalid task registry: {root / REGISTRY}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id", nargs="?")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    root = root_from(Path.cwd())
    registry = load(root)
    tasks = registry["tasks"]
    if args.list:
        for task_id in sorted(tasks):
            print(task_id)
        return 0
    if not args.task_id or args.task_id not in tasks:
        raise SystemExit(f"Choose one task: {', '.join(sorted(tasks))}")
    task = tasks[args.task_id]
    route = {
        "task_id": args.task_id,
        "first_steps": as_list(registry.get("default_rules", {}).get("first_steps")),
        "required_read": as_list(task.get("required_read")),
        "write_scope": as_list(task.get("write_scope")),
        "forbidden": [*as_list(registry.get("default_rules", {}).get("default_forbidden")), *as_list(task.get("forbidden"))],
        "validation": as_list(task.get("validation")),
    }
    if args.format == "json":
        print(json.dumps(route, ensure_ascii=False, indent=2))
        return 0
    for title, values in route.items():
        print(f"{title}:")
        for value in values if isinstance(values, list) else [values]:
            print(f"  - {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
