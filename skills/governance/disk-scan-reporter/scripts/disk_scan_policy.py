"""Path classification and exclusion policy for the bounded disk scan.

This module intentionally owns decisions about paths. The scan engine only
walks metadata and delegates every scope decision here.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

PROTECTED_NAMES = {
    ".git",
    "$recycle.bin",
    "windows",
    "program files",
    "program files (x86)",
    "system volume information",
}


def expand_path(value: str) -> Path:
    return Path(os.path.abspath(os.path.expandvars(os.path.expanduser(value))))


def normalized_path(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def path_parts_lower(path: Path) -> set[str]:
    return {part.casefold() for part in path.parts}


def is_protected(path: Path) -> bool:
    return bool(path_parts_lower(path) & PROTECTED_NAMES)


def is_link_or_junction(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if is_junction and is_junction():
            return True
        if os.name == "nt":
            attributes = int(getattr(os.lstat(path), "st_file_attributes", 0))
            return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return False
    except OSError:
        return True


def build_exclusions(values: list[str]) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    absolute: set[str] = set()
    for value in values:
        expanded = os.path.expandvars(os.path.expanduser(str(value)))
        candidate = Path(expanded)
        if candidate.is_absolute():
            absolute.add(normalized_path(Path(os.path.abspath(candidate))))
        else:
            names.add(expanded.strip("\\/").casefold())
    return names, absolute


def exclusion_reason(
    path: Path,
    excluded_names: set[str],
    excluded_absolute: set[str],
    *,
    use_legacy_protected_names: bool = True,
) -> str | None:
    if path_parts_lower(path) & excluded_names:
        return "matched excluded directory name"
    current = normalized_path(Path(os.path.abspath(path)))
    for root in excluded_absolute:
        try:
            if os.path.commonpath([current, root]) == root:
                return "matched excluded path"
        except ValueError:
            continue
    if use_legacy_protected_names and is_protected(path):
        return "protected system or source-control path"
    return None


def path_is_within(path: Path, roots: list[Path]) -> bool:
    candidate = Path(os.path.abspath(path))
    for root in roots:
        try:
            candidate.relative_to(Path(os.path.abspath(root)))
            return True
        except ValueError:
            continue
    return False


def inventory_path(path: Path, drives: list[dict[str, object]]) -> str:
    candidate = Path(os.path.abspath(path))
    for drive in drives:
        root = expand_path(str(drive["root"]))
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        label = f"<inventory_{str(drive['label']).upper()}>"
        return label if str(relative) == "." else str(Path(label) / relative)
    return f"<outside_inventory>/{candidate.name}"


def policy_for_inventory_path(path: Path, drive: dict[str, object]) -> str:
    hard = [expand_path(str(value)) for value in drive.get("hard_protected_paths", [])]
    if path_is_within(path, hard):
        return "hard_protected"
    review = [expand_path(str(value)) for value in drive.get("review_only_paths", [])]
    if path_is_within(path, review):
        return "review_only"
    auto = [expand_path(str(value)) for value in drive.get("auto_deep_paths", [])]
    if path_is_within(path, auto):
        return "auto_deep"
    if bool(drive.get("auto_deep_direct_children", False)):
        root = expand_path(str(drive["root"]))
        return "auto_deep" if path.parent == root else "review_only"
    return "review_only"


def audit_policy_for_config(
    config_path: Path, config: dict[str, object]
) -> tuple[Path, dict[str, object]]:
    try:
        from scripts.audit_guard import DEFAULT_POLICY_PATH, load_audit_policy
    except ModuleNotFoundError:
        from audit_guard import DEFAULT_POLICY_PATH, load_audit_policy

    if "audit_policy" not in config:
        return DEFAULT_POLICY_PATH, load_audit_policy(DEFAULT_POLICY_PATH)
    name = str(config["audit_policy"])
    candidate = Path(name)
    if candidate.is_absolute() or candidate.name != name:
        raise ValueError("audit_policy must name a file in the config directory")
    policy_path = Path(os.path.abspath(config_path.parent / candidate))
    if policy_path.parent != Path(os.path.abspath(config_path.parent)):
        raise ValueError("audit_policy must stay in the config directory")
    return policy_path, load_audit_policy(policy_path)


__all__ = [
    "PROTECTED_NAMES",
    "build_exclusions",
    "exclusion_reason",
    "expand_path",
    "is_link_or_junction",
    "is_protected",
    "normalized_path",
    "path_parts_lower",
    "path_is_within",
    "inventory_path",
    "policy_for_inventory_path",
    "audit_policy_for_config",
]
