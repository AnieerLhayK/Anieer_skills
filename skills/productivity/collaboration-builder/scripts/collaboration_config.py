"""Load and validate declarative collaboration layouts."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


ROLE_ID = re.compile(r"^[a-z][a-z0-9-]*$")
LAYOUT_ID = re.compile(r"^[a-z][a-z0-9-]*$")
TASK_ID = re.compile(r"^[a-z][a-z0-9_-]*$")
FEATURE_DEFAULTS = {
    "ai_records": {"enabled": False, "enforcement": "blocking"},
    "work_session_lock": {"enabled": False},
    "git_hooks": {"enabled": False},
}
DEFAULT_TASKS = {
    "governance_update": {
        "required_read": ["AGENTS.md"],
        "write_scope": ["{governance_root}/"],
        "validation": ["git diff --check"],
    },
    "role_work": {
        "required_read": ["AGENTS.md"],
        "write_scope": ["{role_path}/"],
        "validation": ["git diff --check"],
    },
}


class ConfigError(ValueError):
    pass


def yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot load YAML {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must contain a mapping")
    return value


def safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label} must be a non-empty relative path")
    normalized = value.replace("\\", "/").strip("/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ConfigError(f"{label} must be relative: {value!r}")
    if any(part in {"", ".", ".."} for part in normalized.split("/")):
        raise ConfigError(f"{label} escapes the target: {value!r}")
    return normalized


def layout_source(skill_root: Path, layout_id: str) -> dict[str, Any]:
    if layout_id == "custom":
        return {}
    if not LAYOUT_ID.fullmatch(layout_id):
        raise ConfigError("layout must be a lowercase layout ID")
    path = skill_root / "config" / "layouts" / f"{layout_id}.yaml"
    if not path.is_file():
        raise ConfigError(f"unknown layout: {layout_id}")
    layout = yaml_mapping(path)
    if layout.get("id") != layout_id:
        raise ConfigError(f"layout ID mismatch: {path}")
    return layout


def normalize_roles(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError("roles must be a non-empty list")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        role = {"id": item} if isinstance(item, str) else item
        if not isinstance(role, dict) or not isinstance(role.get("id"), str):
            raise ConfigError("each role must be an ID or mapping with id")
        role_id = role["id"]
        if not ROLE_ID.fullmatch(role_id) or role_id == "maintainer" or role_id in seen:
            raise ConfigError(f"invalid or duplicate role ID: {role_id!r}")
        clean = {key: value for key, value in role.items() if isinstance(key, str) and isinstance(value, str)}
        if len(clean) != len(role):
            raise ConfigError(f"role {role_id} values must be strings")
        result.append(clean)
        seen.add(role_id)
    return result


def resolve_role_paths(template: str, variables: dict[str, str], roles: list[dict[str, str]]) -> list[dict[str, str]]:
    template = safe_relative(template, "role_path")
    resolved: list[dict[str, str]] = []
    paths: set[str] = set()
    for role in roles:
        values = {**variables, **role, "role": role["id"]}
        try:
            path = safe_relative(template.format(**values), f"role path for {role['id']}")
        except KeyError as exc:
            raise ConfigError(f"role path requires missing variable: {exc.args[0]}") from exc
        if path in paths:
            raise ConfigError(f"role paths collide: {path}")
        paths.add(path)
        resolved.append({**role, "path": path})
    return resolved


def normalize_tasks(raw: Any) -> dict[str, dict[str, list[str]]]:
    tasks = deepcopy(DEFAULT_TASKS) if raw is None else raw
    if not isinstance(tasks, dict) or not tasks:
        raise ConfigError("tasks must be a non-empty mapping")
    result: dict[str, dict[str, list[str]]] = {}
    for task_id, task in tasks.items():
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id) or not isinstance(task, dict):
            raise ConfigError("each task must have a lowercase ID and mapping")
        values: dict[str, list[str]] = {}
        for field in ("required_read", "write_scope", "validation"):
            items = task.get(field)
            if not isinstance(items, list) or not items or any(not isinstance(item, str) or not item.strip() for item in items):
                raise ConfigError(f"task {task_id} requires non-empty {field}")
            values[field] = list(items)
        result[task_id] = values
    return result


def normalize_config(source: Path, skill_root: Path) -> dict[str, Any]:
    raw = yaml_mapping(source)
    if raw.get("schema_version") != 1:
        raise ConfigError("schema_version must be 1")
    layout_id = raw.get("layout")
    if not isinstance(layout_id, str):
        raise ConfigError("layout is required")
    layout = layout_source(skill_root, layout_id)
    variables = raw.get("variables", {})
    if not isinstance(variables, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in variables.items()):
        raise ConfigError("variables must be a string mapping")
    variables = dict(variables)
    if layout_id == "custom":
        custom = raw.get("custom")
        if not isinstance(custom, dict):
            raise ConfigError("custom layout requires custom mapping")
        template = custom.get("role_path")
        shared_roots = custom.get("shared_roots", [])
    else:
        required = layout.get("required_variables", [])
        if any(name not in variables for name in required):
            missing = ", ".join(name for name in required if name not in variables)
            raise ConfigError(f"layout {layout_id} requires variables: {missing}")
        template = layout.get("role_path")
        shared_roots = layout.get("shared_roots", [])
    if not isinstance(shared_roots, list):
        raise ConfigError("shared_roots must be a list")
    roles = normalize_roles(raw.get("roles"))
    resolved_roles = resolve_role_paths(template, variables, roles)
    governance = raw.get("governance", {})
    if not isinstance(governance, dict):
        raise ConfigError("governance must be a mapping")
    governance = {**governance}
    governance["root"] = safe_relative(governance.get("root", "governance"), "governance.root")
    governance["protected_exact"] = [safe_relative(item, "protected_exact") for item in governance.get("protected_exact", [])]
    governance["protected_prefixes"] = [safe_relative(item, "protected_prefixes") for item in governance.get("protected_prefixes", [])]
    features = deepcopy(FEATURE_DEFAULTS)
    supplied = raw.get("features", {})
    if not isinstance(supplied, dict):
        raise ConfigError("features must be a mapping")
    for name, defaults in FEATURE_DEFAULTS.items():
        value = supplied.get(name, {})
        if isinstance(value, bool):
            value = {"enabled": value}
        if not isinstance(value, dict):
            raise ConfigError(f"features.{name} must be a mapping")
        features[name].update(value)
        if not isinstance(features[name].get("enabled"), bool):
            raise ConfigError(f"features.{name}.enabled must be boolean")
    if features["ai_records"].get("enforcement") not in {"blocking", "advisory"}:
        raise ConfigError("features.ai_records.enforcement must be blocking or advisory")
    shared = [safe_relative(item, "shared_roots") for item in shared_roots]
    return {
        "schema_version": 1,
        "layout": layout_id,
        "variables": variables,
        "roles": roles,
        "resolved_roles": resolved_roles,
        "governance": governance,
        "shared_roots": shared,
        "tasks": normalize_tasks(raw.get("tasks")),
        "features": features,
    }
