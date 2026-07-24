"""Warn about staged paths outside a configured task or role boundary."""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
from pathlib import Path
from typing import Any

import yaml


def normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def as_list(value: Any) -> list[str]:
    return [] if value is None else [str(item) for item in value] if isinstance(value, list) else [str(value)]


def root_from(start: Path) -> Path:
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / ".git").exists() and (candidate / "AGENTS.md").exists():
            return candidate
    raise SystemExit("Run inside a repository containing .git and AGENTS.md.")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid YAML mapping: {path}")
    return data


def under(path: str, scope: str) -> bool:
    path, scope = normalize(path), normalize(scope)
    return not scope or (path.startswith(scope) if scope.endswith("/") else path == scope)


def matches(path: str, rule: str) -> bool:
    path, rule = normalize(path), normalize(rule)
    if not any(token in rule for token in "*?["):
        return under(path, rule)
    return fnmatch.fnmatchcase(path, rule) or fnmatch.fnmatchcase(path, rule.removeprefix("**/"))


def staged_paths(root: Path) -> list[str]:
    result = subprocess.run(["git", "diff", "--cached", "--name-only", "-z"], cwd=root, capture_output=True, check=False)
    if result.returncode:
        raise SystemExit(result.stderr.decode("utf-8", errors="replace"))
    return [normalize(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--staged", action="store_true")
    parser.add_argument("--maintenance-note")
    parser.add_argument("--ai-work")
    args = parser.parse_args()
    root = root_from(Path.cwd())
    registry = load_yaml(root / "PROJECT_CONTEXT/task_registry.yaml")
    config = load_yaml(root / "PROJECT_CONTEXT/roles.yaml")
    roles, tasks = config.get("roles", {}), registry.get("tasks", {})
    if args.role not in roles or args.task not in tasks:
        raise SystemExit("Unknown task or role; inspect configuration.")
    task, paths = tasks[args.task], staged_paths(root)
    role_root = str(roles[args.role].get("path", ""))
    protected_exact = set(as_list(config.get("protected_exact")))
    protected_prefixes = tuple(as_list(config.get("protected_prefixes")))
    warnings = 0
    for path in paths:
        task_ok = any(under(path, scope) for scope in as_list(task.get("write_scope")))
        protected = path in protected_exact or any(path.startswith(prefix) for prefix in protected_prefixes)
        if not task_ok:
            warnings += 1; print(f"[WARNING] {path}: outside task write_scope")
        if role_root and not under(path, role_root) and not (protected and args.maintenance_note):
            warnings += 1; print(f"[WARNING] {path}: outside role area {role_root}")
        if protected and args.role != "maintainer" and not args.maintenance_note:
            warnings += 1; print(f"[WARNING] {path}: shared governance requires maintainer confirmation")
        if any(matches(path, rule) for rule in as_list(registry.get("default_rules", {}).get("default_forbidden")) + as_list(task.get("forbidden"))):
            warnings += 1; print(f"[WARNING] {path}: matches a forbidden route")
        if path.endswith("/.gitignore") and path.startswith("team/"):
            warnings += 1; print(f"[WARNING] {path}: role-local ignore file should remain unstaged")
    if args.ai_work and args.role != "maintainer":
        expected = f"{role_root}AI-records/{args.ai_work}.md"
        if expected not in paths:
            warnings += 1; print(f"[WARNING] AI record not staged: {expected}")
    print("Result: warnings require explanation; this checker never blocks a commit." if warnings else "Result: staged paths match this route.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
