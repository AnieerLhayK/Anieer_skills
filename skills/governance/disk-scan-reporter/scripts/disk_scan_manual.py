"""Explicit, metadata-only deep scans with one shared budget."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable

try:
    from scripts.disk_scan_policy import (
        build_exclusions, exclusion_reason, expand_path, inventory_path,
        is_link_or_junction, normalized_path, path_is_within,
    )
except ModuleNotFoundError:
    from disk_scan_policy import (
        build_exclusions, exclusion_reason, expand_path, inventory_path,
        is_link_or_junction, normalized_path, path_is_within,
    )


def manual_scope(config: dict[str, Any], values: list[Path]) -> tuple[list[Path], list[str]]:
    """Validate all requested roots before traversal; never resolve through links."""
    plan = config.get("two_stage_plan")
    if not plan:
        raise ValueError("--deep-scan requires a configured two_stage_plan")
    drives = plan["drives"]
    exclusions = [".git", *config.get("manual_deep_scan", {}).get("excluded_paths", [])]
    for drive in drives:
        exclusions.extend(drive.get("hard_protected_paths", []))
    names, absolute = build_exclusions(exclusions)
    roots: list[Path] = []
    for value in values:
        if not Path(value).is_absolute():
            raise ValueError("--deep-scan requires absolute directory paths")
        root = expand_path(str(value))
        drive_roots = [expand_path(drive["root"]) for drive in drives]
        if root in drive_roots or not path_is_within(root, drive_roots):
            raise ValueError("manual target must be below a configured drive root")
        if exclusion_reason(root, names, absolute, use_legacy_protected_names=False):
            raise ValueError("manual target is protected or excluded")
        # An ordinary-looking child can still traverse a junction in an ancestor.
        for part in [*reversed(root.parents), root]:
            if (part.exists() or part.is_symlink()) and is_link_or_junction(part):
                raise ValueError("manual target has a link or reparse-point ancestor")
        if all(normalized_path(root) != normalized_path(other) for other in roots):
            roots.append(root)
    roots.sort(key=lambda item: len(item.parts))
    selected: list[Path] = []
    for root in roots:
        if not path_is_within(root, selected):
            selected.append(root)
    return selected, exclusions


def run_manual_scan(
    config_path: Path, config: dict[str, Any], audit_policy: dict[str, Any],
    values: list[Path], engine: Any, scan: Callable[..., Any],
) -> dict[str, Any]:
    roots, exclusions = manual_scope(config, values)
    static = engine.run_static_audit(engine.SKILL_ROOT, audit_policy)
    if static["status"] == "FAIL":
        raise RuntimeError("safety audit failed; scan was not started")
    budget = config.get("manual_deep_scan", {})
    seconds = float(budget.get("max_total_seconds", 900))
    files = int(budget.get("max_total_files", 500000))
    effective = {
        **config, "scan_paths": [str(root) for root in roots],
        "exclude_paths": exclusions, "hard_protected_paths": exclusions,
        "legacy_protected_names": False, "follow_symlinks": False,
        "skip_repository_roots": True,
        "max_depth": None, "max_files_per_run": files, "max_scan_seconds": seconds,
        "old_file_is_candidate": False, "report_path_mode": "relative",
        "old_file_days": int(config.get("old_file_days", 30)),
    }
    state = engine.ScanState()
    state.audit = {"static": static, "snapshot_warnings": 0}
    deadline = time.monotonic() + seconds
    snapshot = audit_policy.get("snapshot", {})
    for root in roots:
        scan(
            root, effective, state, deadline=deadline,
            snapshot_enabled=bool(snapshot.get("enabled", True)),
            snapshot_name_hash=bool(snapshot.get("include_direct_child_name_hash", True)),
        )
    state.audit["snapshot_warnings"] = sum(
        row.snapshot_comparison is not None and row.snapshot_comparison.get("status") == "WARNING"
        for row in state.coverage
    )
    report = engine.build_report(config_path, effective, state)
    report.update({
        "schema_version": engine.REPORT_SCHEMA_VERSION,
        "config_used": config_path.name,
        "run_mode": "manual_deep",
        "path_reporting": {
            "mode": "relative",
            "message": "Numbered scan roots correspond in order to the drive-relative request.targets list.",
        },
        "request": {
            "targets": [inventory_path(root, config["two_stage_plan"]["drives"]) for root in roots],
            "reason": "explicit user request; automatic thresholds and review_only do not apply",
            "max_total_seconds": seconds, "max_total_files": files,
        },
        "stages": {
            "inventory": {"mode": "not_run", "drives": [], "directory_aggregates": []},
            "deep_scan": {
                "mode": "manual_shared_budget", "max_total_seconds": seconds,
                "max_total_files": files,
                "targets": [{
                    "path": f"<scan_root_{index}>", "selection_reason": "user_requested",
                    "status": row.status, "terminal_reason": row.terminal_reason,
                    "files_scanned": row.files_scanned, "dirs_scanned": row.dirs_scanned,
                    "file_budget_hit": row.file_budget_hit, "time_budget_hit": row.time_budget_hit,
                } for index, row in enumerate(state.coverage, start=1)],
            },
        },
    })
    return report
