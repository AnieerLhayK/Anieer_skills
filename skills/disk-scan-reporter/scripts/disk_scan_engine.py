#!/usr/bin/env python3
"""Generate bounded, read-only disk usage reports from filesystem metadata."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import heapq
import json
import os
import re
import stat
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

try:
    from scripts.audit_guard import (
        DEFAULT_POLICY_PATH as DEFAULT_AUDIT_POLICY_PATH,
        compare_snapshots,
        ensure_allowed_write_path,
        load_audit_policy,
        run_static_audit,
        shallow_snapshot,
    )
    from scripts.output_paths import default_output_root
except ModuleNotFoundError:
    from audit_guard import (
        DEFAULT_POLICY_PATH as DEFAULT_AUDIT_POLICY_PATH,
        compare_snapshots,
        ensure_allowed_write_path,
        load_audit_policy,
        run_static_audit,
        shallow_snapshot,
    )
    from output_paths import default_output_root


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMP_EXTENSIONS = {".tmp", ".temp"}
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".tar", ".gz"}
CACHE_NAMES = {".cache", "cache"}
BUILD_NAMES = {"build", "dist", "out", "target", ".next"}
DEPENDENCY_NAMES = {"node_modules", ".venv", "venv", "site-packages"}
LARGE_CATEGORIES = {"large_file", "very_large_file"}

# Stable names re-exported by the historical ``disk_scan`` entrypoint.
__all__ = [
    "MIB",
    "REPORT_SCHEMA_VERSION",
    "LEGACY_REPORT_SCHEMA_VERSION",
    "TOOL_VERSION",
    "RootCoverage",
    "ScanState",
    "expand_path",
    "normalized_path",
    "path_parts_lower",
    "is_protected",
    "is_link_or_junction",
    "build_exclusions",
    "exclusion_reason",
    "classify_file",
    "candidate_risk",
    "allocated_size_bytes",
    "file_identity",
    "make_item",
    "keep_candidate",
    "classify_scan_error",
    "record_error",
    "record_coverage_skip",
    "record_skipped",
    "budget_state",
    "finalize_coverage",
    "scan_root",
    "load_config",
    "config_fingerprint",
    "validate_report",
    "parse_report_json",
    "load_report",
    "display_path",
    "display_item",
    "display_message",
    "display_diagnostic",
    "overall_coverage_status",
    "display_coverage",
    "build_report",
    "markdown_two_stage_report",
    "markdown_report",
    "write_reports",
    "audit_policy_for_config",
    "path_is_within",
    "inventory_path",
    "display_stage_coverage",
    "policy_for_inventory_path",
    "state_summary",
    "merge_states",
    "deadline_with_cap",
    "run_two_stage_scan",
    "run_scan",
    "report_exit_code",
    "parse_args",
    "main",
]
if os.name == "nt":

    class _FileStandardInfo(ctypes.Structure):
        _fields_ = [
            ("allocation_size", ctypes.c_longlong),
            ("end_of_file", ctypes.c_longlong),
            ("number_of_links", ctypes.c_ulong),
            ("delete_pending", ctypes.c_ubyte),
            ("directory", ctypes.c_ubyte),
        ]

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CREATE_FILE = _KERNEL32.CreateFileW
    _CREATE_FILE.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_void_p,
    ]
    _CREATE_FILE.restype = ctypes.c_void_p
    _GET_FILE_INFORMATION_BY_HANDLE_EX = _KERNEL32.GetFileInformationByHandleEx
    _GET_FILE_INFORMATION_BY_HANDLE_EX.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_ulong,
    ]
    _GET_FILE_INFORMATION_BY_HANDLE_EX.restype = ctypes.c_int
    _CLOSE_HANDLE = _KERNEL32.CloseHandle
    _CLOSE_HANDLE.argtypes = [ctypes.c_void_p]
    _CLOSE_HANDLE.restype = ctypes.c_int
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
else:
    _CREATE_FILE = None


@dataclass
class RootCoverage:
    planned_root: str
    started: bool = False
    completed: bool = False
    files_scanned: int = 0
    dirs_scanned: int = 0
    skipped_by_depth: int = 0
    skipped_by_exclusion: int = 0
    skipped_links: int = 0
    skipped_duplicates: int = 0
    skipped_unsupported: int = 0
    permission_errors: int = 0
    not_found_errors: int = 0
    interrupted_errors: int = 0
    metadata_errors: int = 0
    unknown_errors: int = 0
    hardlink_duplicates_skipped: int = 0
    file_budget_hit: bool = False
    time_budget_hit: bool = False
    terminal_reason: str = "not_started"
    status: str = "FAILED"
    before_snapshot: dict[str, Any] | None = None
    after_snapshot: dict[str, Any] | None = None
    snapshot_comparison: dict[str, Any] | None = None


@dataclass
class ScanState:
    total_files: int = 0
    total_dirs: int = 0
    total_logical_bytes: int = 0
    observed_allocated_bytes: int = 0
    allocated_size_files: int = 0
    allocated_size_unavailable_files: int = 0
    hardlink_duplicates_skipped: int = 0
    candidate_count: int = 0
    omitted_items: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    top_large: list[tuple[int, int, dict[str, Any]]] = field(default_factory=list)
    sequence: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    error_count: int = 0
    permission_errors: int = 0
    not_found_errors: int = 0
    interrupted_errors: int = 0
    metadata_errors: int = 0
    unknown_errors: int = 0
    skipped_count: int = 0
    omitted_errors: int = 0
    omitted_skipped: int = 0
    unexpected_errors: int = 0
    visited_dirs: set[tuple[int, int]] = field(default_factory=set)
    seen_file_ids: set[tuple[int, int]] = field(default_factory=set)
    coverage: list[RootCoverage] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)


def classify_file(
    path: Path, size: int, modified: float, config: dict[str, Any]
) -> tuple[str, str, str]:
    parts = path_parts_lower(path)
    suffix = path.suffix.casefold()
    age_days = max(0.0, (datetime.now(timezone.utc).timestamp() - modified) / 86400)
    large_bytes = float(config["large_file_mb"]) * MIB
    very_large_bytes = float(config["very_large_file_mb"]) * MIB
    old_days = float(config["old_file_days"])

    if parts & PROTECTED_NAMES:
        return "unknown", "DO_NOT_TOUCH", "Protected system or source-control path"
    if parts & DEPENDENCY_NAMES:
        return "dependency_dir", "HIGH", "File is inside a dependency directory"
    if size > very_large_bytes:
        return (
            "very_large_file",
            candidate_risk(path, suffix),
            "File exceeds the very-large threshold",
        )
    if size > large_bytes:
        return "large_file", candidate_risk(path, suffix), "File exceeds the large-file threshold"
    if suffix in TEMP_EXTENSIONS:
        risk = "LOW" if "temp" in parts and age_days > old_days else "MEDIUM"
        return "temp_file", risk, "Temporary-file extension"
    if suffix == ".log":
        return "log_file", "MEDIUM", "Log-file extension"
    if suffix in ARCHIVE_EXTENSIONS:
        return "archive_file", candidate_risk(path, suffix), "Archive-file extension"
    if parts & CACHE_NAMES:
        return "cache_dir", "MEDIUM", "File is inside a cache directory"
    if parts & BUILD_NAMES:
        return "build_artifact", "MEDIUM", "File is inside a build-output directory"
    if bool(config.get("old_file_is_candidate", True)) and age_days > old_days:
        return "old_file", "HIGH", f"File has not been modified for more than {old_days:g} days"
    return "unknown", "HIGH", "No safe cleanup classification can be inferred"


def candidate_risk(path: Path, suffix: str) -> str:
    parts = path_parts_lower(path)
    if "downloads" in parts and suffix in ARCHIVE_EXTENSIONS:
        return "MEDIUM"
    return "HIGH"


def allocated_size_bytes(path: Path, metadata: os.stat_result) -> int | None:
    blocks = getattr(metadata, "st_blocks", None)
    if isinstance(blocks, int) and blocks >= 0:
        return blocks * 512
    if _CREATE_FILE is not None:
        handle = _CREATE_FILE(
            str(path),
            0x80,
            0x7,
            None,
            3,
            0,
            None,
        )
        if handle == _INVALID_HANDLE_VALUE:
            return None
        try:
            information = _FileStandardInfo()
            success = _GET_FILE_INFORMATION_BY_HANDLE_EX(
                handle,
                1,
                ctypes.byref(information),
                ctypes.sizeof(information),
            )
            return information.allocation_size if success else None
        finally:
            _CLOSE_HANDLE(handle)
    return None


def file_identity(metadata: os.stat_result) -> tuple[int, int] | None:
    if int(getattr(metadata, "st_nlink", 1)) <= 1:
        return None
    device = int(getattr(metadata, "st_dev", 0))
    inode = int(getattr(metadata, "st_ino", 0))
    if not device and not inode:
        return None
    return device, inode


def make_item(
    path: Path,
    logical_size: int,
    allocated_size: int | None,
    modified: float,
    category: str,
    risk: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_mb": round(logical_size / MIB, 3),
        "logical_size_bytes": logical_size,
        "allocated_size_bytes": allocated_size,
        "size_basis": "logical",
        "last_modified": datetime.fromtimestamp(modified, timezone.utc).astimezone().isoformat(),
        "extension": path.suffix.casefold(),
        "directory": str(path.parent),
        "category": category,
        "risk": risk,
        "suggestion": "manual_review",
        "reason": reason,
    }


def keep_candidate(state: ScanState, item: dict[str, Any], max_items: int) -> None:
    state.candidate_count += 1
    state.sequence += 1
    size_bytes = int(item["logical_size_bytes"])
    ranked = (size_bytes, state.sequence, item)
    if item["category"] in LARGE_CATEGORIES:
        if len(state.top_large) < 20:
            heapq.heappush(state.top_large, ranked)
        elif size_bytes > state.top_large[0][0]:
            heapq.heapreplace(state.top_large, ranked)
    if len(state.items) < max_items:
        state.items.append(item)
    else:
        state.omitted_items += 1


def classify_scan_error(error: BaseException | str) -> str:
    if isinstance(error, PermissionError) or getattr(error, "errno", None) in {
        errno.EACCES,
        errno.EPERM,
    }:
        return "permission_denied"
    if isinstance(error, FileNotFoundError) or getattr(error, "errno", None) == errno.ENOENT:
        return "not_found"
    if isinstance(error, InterruptedError) or getattr(error, "errno", None) == errno.EINTR:
        return "interrupted"
    if isinstance(error, OSError):
        return "metadata_error"
    return "unknown"


def record_error(
    state: ScanState,
    path: Path | str,
    error: BaseException | str,
    max_items: int,
    *,
    coverage: RootCoverage | None = None,
    category: str | None = None,
) -> None:
    error_category = category or classify_scan_error(error)
    field_name = ERROR_CATEGORY_FIELDS.get(error_category, "unknown_errors")
    state.error_count += 1
    setattr(state, field_name, getattr(state, field_name) + 1)
    if coverage is not None:
        setattr(coverage, field_name, getattr(coverage, field_name) + 1)
    if len(state.errors) < max_items:
        state.errors.append(
            {
                "path": str(path),
                "category": error_category,
                "errno": getattr(error, "errno", None),
                "error": str(error),
            }
        )
    else:
        state.omitted_errors += 1


def record_coverage_skip(coverage: RootCoverage | None, category: str) -> None:
    if coverage is None:
        return
    field_name = {
        "depth": "skipped_by_depth",
        "exclusion": "skipped_by_exclusion",
        "link": "skipped_links",
        "duplicate": "skipped_duplicates",
        "unsupported": "skipped_unsupported",
    }.get(category)
    if field_name:
        setattr(coverage, field_name, getattr(coverage, field_name) + 1)


def record_skipped(
    state: ScanState,
    path: Path,
    reason: str,
    risk: str = "HIGH",
    max_items: int = 1000,
    *,
    coverage: RootCoverage | None = None,
    category: str = "exclusion",
) -> None:
    state.skipped_count += 1
    record_coverage_skip(coverage, category)
    if len(state.skipped) < max_items:
        state.skipped.append({"path": str(path), "reason": reason, "risk": risk})
    else:
        state.omitted_skipped += 1


def budget_state(
    config: dict[str, Any],
    state: ScanState,
    deadline: float | None,
) -> str | None:
    max_files = max(0, int(config.get("max_files_per_run", 100000)))
    if max_files and state.total_files >= max_files:
        return "file"
    if deadline is not None and time.monotonic() >= deadline:
        return "time"
    return None


def finalize_coverage(
    coverage: RootCoverage,
    *,
    snapshot_enabled: bool,
    snapshot_name_hash: bool,
    root: Path,
) -> RootCoverage:
    if snapshot_enabled and coverage.started:
        coverage.after_snapshot = shallow_snapshot(
            root,
            include_name_hash=snapshot_name_hash,
        )
        coverage.snapshot_comparison = compare_snapshots(
            coverage.before_snapshot,
            coverage.after_snapshot,
        )
    if coverage.file_budget_hit or coverage.time_budget_hit:
        coverage.status = "PARTIAL_BUDGET_EXHAUSTED"
    elif coverage.permission_errors:
        coverage.status = "PARTIAL_PERMISSION_LIMITED"
    elif any(
        (
            coverage.not_found_errors,
            coverage.interrupted_errors,
            coverage.metadata_errors,
            coverage.unknown_errors,
        )
    ):
        coverage.status = "PARTIAL_WITH_EXPLAINED_SKIPS"
    elif not coverage.started and coverage.terminal_reason in {
        "root_excluded",
        "root_link_skipped",
    }:
        coverage.status = "PARTIAL_WITH_EXPLAINED_SKIPS"
    elif not coverage.started:
        coverage.status = "FAILED"
    elif any(
        (
            coverage.skipped_by_depth,
            coverage.skipped_by_exclusion,
            coverage.skipped_links,
            coverage.skipped_duplicates,
            coverage.skipped_unsupported,
        )
    ):
        coverage.status = "PARTIAL_WITH_EXPLAINED_SKIPS"
    else:
        coverage.status = "COMPLETE_WITHIN_CONFIG"
    return coverage


def scan_root(
    root: Path,
    config: dict[str, Any],
    state: ScanState,
    *,
    deadline: float | None = None,
    snapshot_enabled: bool = False,
    snapshot_name_hash: bool = True,
    rollups: dict[str, dict[str, Any]] | None = None,
    rollup_paths: list[Path] | None = None,
    direct_root_rollup: dict[str, Any] | None = None,
) -> RootCoverage:
    excluded_names, excluded_absolute = build_exclusions(list(config.get("exclude_paths", [])))
    hard_protected_absolute = {
        normalized_path(expand_path(value)) for value in config.get("hard_protected_paths", [])
    }
    max_depth_raw = config.get("max_depth", 8)
    max_depth = None if max_depth_raw is None else max(0, int(max_depth_raw))
    follow_links = bool(config.get("follow_symlinks", False))
    use_legacy_protected_names = bool(config.get("legacy_protected_names", True))
    max_items = max(0, int(config.get("max_report_items", 5000)))
    max_diagnostics = max(0, int(config.get("max_diagnostic_items", 1000)))
    coverage = RootCoverage(planned_root=str(root))
    state.coverage.append(coverage)

    initial_budget = budget_state(config, state, deadline)
    if initial_budget:
        coverage.file_budget_hit = initial_budget == "file"
        coverage.time_budget_hit = initial_budget == "time"
        coverage.terminal_reason = f"{initial_budget}_budget_exhausted_before_root"
        return finalize_coverage(
            coverage,
            snapshot_enabled=snapshot_enabled,
            snapshot_name_hash=snapshot_name_hash,
            root=root,
        )

    if not root.exists():
        record_skipped(
            state,
            root,
            "scan path does not exist",
            max_items=max_diagnostics,
            coverage=coverage,
        )
        coverage.terminal_reason = "scan_path_missing"
        return finalize_coverage(
            coverage,
            snapshot_enabled=snapshot_enabled,
            snapshot_name_hash=snapshot_name_hash,
            root=root,
        )
    if not root.is_dir():
        record_skipped(
            state,
            root,
            "scan path is not a directory",
            max_items=max_diagnostics,
            coverage=coverage,
        )
        coverage.terminal_reason = "scan_path_not_directory"
        return finalize_coverage(
            coverage,
            snapshot_enabled=snapshot_enabled,
            snapshot_name_hash=snapshot_name_hash,
            root=root,
        )
    reason = exclusion_reason(
        root,
        excluded_names,
        excluded_absolute,
        use_legacy_protected_names=use_legacy_protected_names,
    )
    if reason:
        record_skipped(
            state,
            root,
            reason,
            "DO_NOT_TOUCH" if is_protected(root) else "HIGH",
            max_diagnostics,
            coverage=coverage,
        )
        coverage.terminal_reason = "root_excluded"
        return finalize_coverage(
            coverage,
            snapshot_enabled=snapshot_enabled,
            snapshot_name_hash=snapshot_name_hash,
            root=root,
        )
    if is_link_or_junction(root) and not follow_links:
        record_skipped(
            state,
            root,
            "directory link or junction not followed",
            max_items=max_diagnostics,
            coverage=coverage,
            category="link",
        )
        coverage.terminal_reason = "root_link_skipped"
        return finalize_coverage(
            coverage,
            snapshot_enabled=snapshot_enabled,
            snapshot_name_hash=snapshot_name_hash,
            root=root,
        )

    coverage.started = True
    coverage.terminal_reason = "scanning"
    if snapshot_enabled:
        coverage.before_snapshot = shallow_snapshot(
            root,
            include_name_hash=snapshot_name_hash,
        )

    stack: list[tuple[Path, int]] = [(root, 0)]
    budget_exhausted = False
    while stack:
        current, depth = stack.pop()
        current_budget = budget_state(config, state, deadline)
        if current_budget:
            coverage.file_budget_hit = current_budget == "file"
            coverage.time_budget_hit = current_budget == "time"
            coverage.terminal_reason = f"{current_budget}_budget_exhausted"
            budget_exhausted = True
            break
        if is_link_or_junction(current) and not follow_links:
            record_skipped(
                state,
                current,
                "directory link or junction not followed",
                max_items=max_diagnostics,
                coverage=coverage,
                category="link",
            )
            continue
        try:
            identity_stat = current.stat()
            identity = (identity_stat.st_dev, identity_stat.st_ino)
            if identity in state.visited_dirs:
                record_skipped(
                    state,
                    current,
                    "directory cycle or duplicate target detected",
                    max_items=max_diagnostics,
                    coverage=coverage,
                    category="duplicate",
                )
                continue
            state.visited_dirs.add(identity)
            state.total_dirs += 1
            coverage.dirs_scanned += 1
            if max_depth is not None and depth >= max_depth:
                record_skipped(
                    state,
                    current,
                    f"maximum depth {max_depth} reached",
                    max_items=max_diagnostics,
                    coverage=coverage,
                    category="depth",
                )
                continue
            with os.scandir(current) as entries:
                for entry in entries:
                    current_budget = budget_state(config, state, deadline)
                    if current_budget:
                        coverage.file_budget_hit = current_budget == "file"
                        coverage.time_budget_hit = current_budget == "time"
                        coverage.terminal_reason = f"{current_budget}_budget_exhausted"
                        budget_exhausted = True
                        break
                    path = Path(entry.path)
                    excluded = exclusion_reason(
                        path,
                        excluded_names,
                        excluded_absolute,
                        use_legacy_protected_names=use_legacy_protected_names,
                    )
                    if excluded:
                        hard_protected = normalized_path(path) in hard_protected_absolute
                        record_skipped(
                            state,
                            path,
                            excluded,
                            "DO_NOT_TOUCH" if hard_protected or is_protected(path) else "HIGH",
                            max_diagnostics,
                            coverage=coverage,
                            category="exclusion",
                        )
                        continue
                    try:
                        if entry.is_symlink() and not follow_links:
                            record_skipped(
                                state,
                                path,
                                "symbolic link not followed",
                                max_items=max_diagnostics,
                                coverage=coverage,
                                category="link",
                            )
                            continue
                        if entry.is_dir(follow_symlinks=follow_links):
                            stack.append((path, depth + 1))
                            continue
                        if not entry.is_file(follow_symlinks=follow_links):
                            record_skipped(
                                state,
                                path,
                                "unsupported filesystem entry type",
                                max_items=max_diagnostics,
                                coverage=coverage,
                                category="unsupported",
                            )
                            continue
                        metadata = (
                            os.stat(path, follow_symlinks=follow_links)
                            if os.name == "nt"
                            else entry.stat(follow_symlinks=follow_links)
                        )
                        state.total_files += 1
                        coverage.files_scanned += 1
                        identity = file_identity(metadata)
                        if identity is not None and identity in state.seen_file_ids:
                            state.hardlink_duplicates_skipped += 1
                            coverage.hardlink_duplicates_skipped += 1
                            continue
                        if identity is not None:
                            state.seen_file_ids.add(identity)
                        logical_size = metadata.st_size
                        allocated_size = allocated_size_bytes(path, metadata)
                        state.total_logical_bytes += logical_size
                        if allocated_size is None:
                            state.allocated_size_unavailable_files += 1
                        else:
                            state.observed_allocated_bytes += allocated_size
                            state.allocated_size_files += 1
                        if direct_root_rollup is not None and path.parent == root:
                            direct_root_rollup["observed_logical_bytes"] += logical_size
                            direct_root_rollup["observed_files"] += 1
                            if allocated_size is None:
                                direct_root_rollup["allocated_size_complete"] = False
                            else:
                                direct_root_rollup["observed_allocated_bytes"] += allocated_size
                        if rollups is not None and rollup_paths:
                            for rollup_root in rollup_paths:
                                try:
                                    path.relative_to(rollup_root)
                                except ValueError:
                                    continue
                                key = normalized_path(rollup_root)
                                bucket = rollups.setdefault(
                                    key,
                                    {
                                        "path": str(rollup_root),
                                        "observed_logical_bytes": 0,
                                        "observed_allocated_bytes": 0,
                                        "observed_files": 0,
                                        "allocated_size_complete": True,
                                    },
                                )
                                bucket["observed_logical_bytes"] += logical_size
                                bucket["observed_files"] += 1
                                if allocated_size is None:
                                    bucket["allocated_size_complete"] = False
                                else:
                                    bucket["observed_allocated_bytes"] += allocated_size
                        category, risk, item_reason = classify_file(
                            path,
                            logical_size,
                            metadata.st_mtime,
                            config,
                        )
                        if category != "unknown":
                            keep_candidate(
                                state,
                                make_item(
                                    path,
                                    logical_size,
                                    allocated_size,
                                    metadata.st_mtime,
                                    category,
                                    risk,
                                    item_reason,
                                ),
                                max_items,
                            )
                    except (OSError, PermissionError) as exc:
                        record_error(
                            state,
                            path,
                            exc,
                            max_diagnostics,
                            coverage=coverage,
                        )
                if budget_exhausted:
                    break
        except (OSError, PermissionError) as exc:
            record_error(
                state,
                current,
                exc,
                max_diagnostics,
                coverage=coverage,
            )
    if not budget_exhausted:
        coverage.completed = True
        coverage.terminal_reason = "completed"
    return finalize_coverage(
        coverage,
        snapshot_enabled=snapshot_enabled,
        snapshot_name_hash=snapshot_name_hash,
        root=root,
    )


def display_stage_coverage(
    coverage: RootCoverage,
    actual_roots: list[Path],
    labels: list[str],
    index: int,
) -> dict[str, Any]:
    payload = asdict(coverage)
    payload["planned_root"] = labels[index]
    for key in ("before_snapshot", "after_snapshot"):
        snapshot = payload.get(key)
        if snapshot and snapshot.get("error"):
            message = snapshot["error"]
            for root, label in zip(actual_roots, labels):
                message = re.sub(re.escape(str(root)), label, message, flags=re.IGNORECASE)
            snapshot["error"] = message
    return payload


def state_summary(state: ScanState) -> dict[str, Any]:
    allocated_complete = state.allocated_size_unavailable_files == 0
    return {
        "total_files_scanned": state.total_files,
        "total_dirs_scanned": state.total_dirs,
        "logical_size_bytes": state.total_logical_bytes,
        "logical_size_mb": round(state.total_logical_bytes / MIB, 3),
        "total_size_mb": round(state.total_logical_bytes / MIB, 3),
        "allocated_size_bytes": state.observed_allocated_bytes if allocated_complete else None,
        "observed_allocated_size_bytes": state.observed_allocated_bytes,
        "allocated_size_files": state.allocated_size_files,
        "allocated_size_unavailable_files": state.allocated_size_unavailable_files,
        "allocated_size_complete": allocated_complete,
        "hardlink_duplicates_skipped": state.hardlink_duplicates_skipped,
        "permission_errors": state.permission_errors,
        "not_found_errors": state.not_found_errors,
        "interrupted_errors": state.interrupted_errors,
        "metadata_errors": state.metadata_errors,
        "unknown_errors": state.unknown_errors,
        "total_errors": state.error_count,
        "unexpected_errors": state.unexpected_errors,
        "skipped_paths": state.skipped_count,
        "candidate_items": state.candidate_count,
        "reported_items": len(state.items),
        "omitted_items": state.omitted_items,
        "omitted_errors": state.omitted_errors,
        "omitted_skipped": state.omitted_skipped,
    }


def merge_states(states: list[ScanState]) -> ScanState:
    merged = ScanState()
    for state in states:
        for key in (
            "total_files",
            "total_dirs",
            "total_logical_bytes",
            "observed_allocated_bytes",
            "allocated_size_files",
            "allocated_size_unavailable_files",
            "hardlink_duplicates_skipped",
            "candidate_count",
            "omitted_items",
            "error_count",
            "permission_errors",
            "not_found_errors",
            "interrupted_errors",
            "metadata_errors",
            "unknown_errors",
            "skipped_count",
            "omitted_errors",
            "omitted_skipped",
            "unexpected_errors",
        ):
            setattr(merged, key, getattr(merged, key) + getattr(state, key))
        merged.items.extend(state.items)
        merged.top_large.extend(state.top_large)
        merged.errors.extend(state.errors)
        merged.skipped.extend(state.skipped)
        merged.coverage.extend(state.coverage)
    return merged


def deadline_with_cap(global_deadline: float | None, seconds: float) -> float | None:
    local = time.monotonic() + seconds if seconds else None
    if global_deadline is None:
        return local
    if local is None:
        return global_deadline
    return min(global_deadline, local)


def run_two_stage_scan(
    config_path: Path,
    config: dict[str, Any],
    audit_policy: dict[str, Any],
) -> dict[str, Any]:
    plan = dict(config["two_stage_plan"])
    drives = list(plan["drives"])
    total_seconds = float(plan.get("max_total_seconds", 900))
    global_deadline = time.monotonic() + total_seconds if total_seconds else None
    static_audit = run_static_audit(SKILL_ROOT, audit_policy)
    if static_audit["status"] == "FAIL":
        raise RuntimeError("safety audit failed; scan was not started")
    snapshot = audit_policy.get("snapshot", {})
    snapshot_enabled = bool(snapshot.get("enabled", True))
    snapshot_name_hash = bool(snapshot.get("include_direct_child_name_hash", True))
    inventory_rows: list[dict[str, Any]] = []
    inventory_coverages: list[RootCoverage] = []
    selected: list[dict[str, Any]] = []
    for drive in drives:
        root = expand_path(str(drive["root"]))
        state = ScanState()
        rollups: dict[str, dict[str, Any]] = {}
        root_files = {
            "observed_logical_bytes": 0,
            "observed_allocated_bytes": 0,
            "observed_files": 0,
            "allocated_size_complete": True,
        }
        child_paths: list[Path] = []
        try:
            with os.scandir(root) as entries:
                child_paths = [
                    Path(entry.path) for entry in entries if entry.is_dir(follow_symlinks=False)
                ]
        except (OSError, PermissionError):
            child_paths = []
        rollup_paths = list(child_paths)
        known_rollups = {normalized_path(item) for item in rollup_paths}
        for value in list(drive.get("auto_deep_paths", [])) + list(
            drive.get("review_only_paths", [])
        ):
            candidate = expand_path(value)
            if normalized_path(candidate) not in known_rollups:
                rollup_paths.append(candidate)
                known_rollups.add(normalized_path(candidate))
        stage_config = {
            "exclude_paths": list(drive.get("hard_protected_paths", [])) + [".git"],
            "hard_protected_paths": list(drive.get("hard_protected_paths", [])),
            "legacy_protected_names": False,
            "follow_symlinks": False,
            "max_depth": int(drive["inventory_max_depth"]),
            "max_files_per_run": int(drive["inventory_max_files"]),
            "max_scan_seconds": float(drive["inventory_max_seconds"]),
            "max_report_items": int(config.get("max_report_items", 5000)),
            "max_diagnostic_items": int(config.get("max_diagnostic_items", 1000)),
            "large_file_mb": int(config["large_file_mb"]),
            "very_large_file_mb": int(config["very_large_file_mb"]),
            "old_file_days": int(config.get("old_file_days", 30)),
            "old_file_is_candidate": False,
        }
        coverage = scan_root(
            root,
            stage_config,
            state,
            deadline=deadline_with_cap(global_deadline, float(drive["inventory_max_seconds"])),
            snapshot_enabled=snapshot_enabled,
            snapshot_name_hash=snapshot_name_hash,
            rollups=rollups,
            rollup_paths=rollup_paths,
            direct_root_rollup=root_files,
        )
        inventory_coverages.append(coverage)
        inventory_rows.append(
            {
                "drive": str(drive["label"]).upper(),
                "path": inventory_path(root, drives),
                "policy": "review_only",
                "observed_logical_bytes": int(root_files["observed_logical_bytes"]),
                "observed_logical_mb": round(int(root_files["observed_logical_bytes"]) / MIB, 3),
                "observed_files": int(root_files["observed_files"]),
                "lower_bound": True,
                "allocated_size_complete": bool(root_files["allocated_size_complete"]),
                "deep_threshold_bytes": 0,
                "promoted": False,
                "promotion_reason": "drive-root files are inventory-only",
            }
        )
        all_paths = {normalized_path(item): item for item in child_paths}
        all_paths.update({normalized_path(item): item for item in rollup_paths})
        threshold = int(float(drive["deep_threshold_gib"]) * 1024 * MIB)
        for item_path in all_paths.values():
            key = normalized_path(item_path)
            observed = rollups.get(key, {})
            policy = policy_for_inventory_path(item_path, drive)
            observed_bytes = int(observed.get("observed_logical_bytes", 0))
            promoted = policy == "auto_deep" and observed_bytes > threshold
            reason = (
                "observed lower bound strictly exceeds the drive threshold"
                if promoted
                else (
                    "not eligible for automatic deep scan by path policy"
                    if policy != "auto_deep"
                    else "observed lower bound does not exceed the drive threshold"
                )
            )
            row = {
                "drive": str(drive["label"]).upper(),
                "path": inventory_path(item_path, drives),
                "policy": policy,
                "observed_logical_bytes": observed_bytes,
                "observed_logical_mb": round(observed_bytes / MIB, 3),
                "observed_files": int(observed.get("observed_files", 0)),
                "lower_bound": True,
                "allocated_size_complete": bool(observed.get("allocated_size_complete", True)),
                "deep_threshold_bytes": threshold,
                "promoted": promoted,
                "promotion_reason": reason,
            }
            inventory_rows.append(row)
            if promoted:
                selected.append({"root": item_path, "inventory": row})
    selected.sort(key=lambda item: len(item["root"].parts))
    deep_targets: list[dict[str, Any]] = []
    for candidate in selected:
        if any(path_is_within(candidate["root"], [item["root"]]) for item in deep_targets):
            candidate["inventory"]["promoted"] = False
            candidate["inventory"]["promotion_reason"] = "covered by a shallower promoted target"
            continue
        deep_targets.append(candidate)
    deep_states: list[ScanState] = []
    deep_target_rows: list[dict[str, Any]] = []
    for target in deep_targets:
        root = target["root"]
        drive = next(
            item for item in drives if path_is_within(root, [expand_path(str(item["root"]))])
        )
        state = ScanState()
        deep_config = {
            "exclude_paths": list(drive.get("hard_protected_paths", [])) + [".git"],
            "hard_protected_paths": list(drive.get("hard_protected_paths", [])),
            "legacy_protected_names": False,
            "follow_symlinks": False,
            "max_depth": None,
            "max_files_per_run": int(plan["deep_max_files_per_target"]),
            "max_scan_seconds": float(plan["deep_max_seconds_per_target"]),
            "max_report_items": int(config.get("max_report_items", 5000)),
            "max_diagnostic_items": int(config.get("max_diagnostic_items", 1000)),
            "large_file_mb": int(config["large_file_mb"]),
            "very_large_file_mb": int(config["very_large_file_mb"]),
            "old_file_days": int(config.get("old_file_days", 30)),
            "old_file_is_candidate": False,
        }
        coverage = scan_root(
            root,
            deep_config,
            state,
            deadline=deadline_with_cap(global_deadline, float(plan["deep_max_seconds_per_target"])),
            snapshot_enabled=snapshot_enabled,
            snapshot_name_hash=snapshot_name_hash,
        )
        deep_states.append(state)
        deep_target_rows.append(
            {
                "path": inventory_path(root, drives),
                "status": coverage.status,
                "terminal_reason": coverage.terminal_reason,
                "files_scanned": coverage.files_scanned,
                "dirs_scanned": coverage.dirs_scanned,
                "file_budget_hit": coverage.file_budget_hit,
                "time_budget_hit": coverage.time_budget_hit,
            }
        )
    deep_state = merge_states(deep_states)
    deep_roots = [item["root"] for item in deep_targets]
    displayed_items = sorted(
        [display_item(item, deep_roots, "relative") for item in deep_state.items],
        key=lambda item: (RISK_ORDER.get(item["risk"], 0), item["size_mb"]),
        reverse=True,
    )
    combined_coverage = inventory_coverages + deep_state.coverage
    inventory_roots = [expand_path(str(item["root"])) for item in drives]
    coverage_roots = inventory_roots + deep_roots
    coverage_labels = [f"<inventory_{str(item['label']).upper()}>" for item in drives] + [
        f"<scan_root_{index}>" for index, _ in enumerate(deep_roots, start=1)
    ]
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "config_used": config_path.name,
        "config_fingerprint": config_fingerprint(config),
        "scan_paths": [f"<scan_root_{index}>" for index, _ in enumerate(deep_roots, start=1)],
        "path_reporting": {
            "mode": "relative",
            "message": "Inventory paths use drive labels; deep-scan paths are relative to numbered promoted roots.",
        },
        "summary": state_summary(deep_state),
        "coverage": {
            "status": overall_coverage_status(combined_coverage),
            "planned_roots": len(combined_coverage),
            "roots_started": sum(item.started for item in combined_coverage),
            "roots_completed": sum(item.completed for item in combined_coverage),
            "file_budget": int(plan["deep_max_files_per_target"]),
            "time_budget_seconds": float(plan["max_total_seconds"]),
            "roots": [
                display_stage_coverage(item, coverage_roots, coverage_labels, index)
                for index, item in enumerate(combined_coverage)
            ],
            "definition": "Coverage is evaluated separately for inventory drives and promoted deep-scan roots.",
        },
        "stages": {
            "inventory": {
                "mode": "bounded_lower_bound",
                "description": "Observed directory bytes are lower bounds because configured depth and budgets can stop traversal.",
                "drives": [
                    {
                        "label": str(item["label"]).upper(),
                        "root": inventory_path(expand_path(str(item["root"])), drives),
                        "max_depth": int(item["inventory_max_depth"]),
                        "max_files": int(item["inventory_max_files"]),
                        "max_seconds": float(item["inventory_max_seconds"]),
                        "deep_threshold_bytes": int(float(item["deep_threshold_gib"]) * 1024 * MIB),
                    }
                    for item in drives
                ],
                "directory_aggregates": sorted(
                    inventory_rows, key=lambda item: item["observed_logical_bytes"], reverse=True
                ),
            },
            "deep_scan": {
                "mode": "full_recursion_with_budget",
                "max_files_per_target": int(plan["deep_max_files_per_target"]),
                "max_seconds_per_target": float(plan["deep_max_seconds_per_target"]),
                "max_total_seconds": total_seconds,
                "targets": deep_target_rows,
            },
        },
        "audit": {
            "static": static_audit,
            "snapshot_warnings": sum(
                1
                for item in combined_coverage
                if item.snapshot_comparison and item.snapshot_comparison.get("status") == "WARNING"
            ),
            "limitations": "The scan reads metadata only and cannot prove arbitrary file content was untouched.",
        },
        "items": displayed_items,
        "top_large_files": [
            display_item(row[2], deep_roots, "relative")
            for row in sorted(deep_state.top_large, key=lambda row: row[0], reverse=True)
        ],
        "errors": [display_diagnostic(item, deep_roots, "relative") for item in deep_state.errors],
        "skipped": [
            display_diagnostic(item, deep_roots, "relative") for item in deep_state.skipped
        ],
        "safety": {
            "read_only": True,
            "cleanup_performed": False,
            "message": "Manual review only. This report does not authorize or perform cleanup.",
        },
    }


def run_scan(config_path: Path, output: Path, max_depth: int | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    if "two_stage_plan" in config:
        _, audit_policy = audit_policy_for_config(config_path, config)
        return run_two_stage_scan(Path(os.path.abspath(config_path)), config, audit_policy)
    if max_depth is not None:
        config["max_depth"] = max_depth
    _, audit_policy = audit_policy_for_config(config_path, config)
    state = ScanState()
    static_audit = run_static_audit(SKILL_ROOT, audit_policy)
    state.audit = {
        "static": static_audit,
        "snapshot_warnings": 0,
        "limitations": (
            "Static checks and shallow snapshots can detect configured hazards "
            "and obvious changes but cannot prove that arbitrary file content "
            "was untouched."
        ),
    }
    if static_audit["status"] == "FAIL":
        raise RuntimeError("safety audit failed; scan was not started")
    max_diagnostics = max(0, int(config.get("max_diagnostic_items", 1000)))
    max_seconds = float(config.get("max_scan_seconds", 120))
    deadline = time.monotonic() + max_seconds if max_seconds else None
    snapshot_config = audit_policy.get("snapshot", {})
    snapshot_enabled = bool(snapshot_config.get("enabled", True))
    snapshot_name_hash = bool(snapshot_config.get("include_direct_child_name_hash", True))
    for value in config["scan_paths"]:
        root = expand_path(str(value))
        coverage_count = len(state.coverage)
        try:
            scan_root(
                root,
                config,
                state,
                deadline=deadline,
                snapshot_enabled=snapshot_enabled,
                snapshot_name_hash=snapshot_name_hash,
            )
        except Exception as exc:  # Keep later roots reportable after an unexpected root failure.
            state.unexpected_errors += 1
            record_error(
                state,
                root,
                exc,
                max_diagnostics,
                category="unknown",
            )
            if len(state.coverage) == coverage_count:
                state.coverage.append(
                    RootCoverage(
                        planned_root=str(root),
                        terminal_reason="unexpected_scan_error",
                        status="FAILED",
                    )
                )
            else:
                state.coverage[-1].completed = False
                state.coverage[-1].terminal_reason = "unexpected_scan_error"
                state.coverage[-1].status = "FAILED"
    state.audit["snapshot_warnings"] = sum(
        1
        for item in state.coverage
        if item.snapshot_comparison and item.snapshot_comparison.get("status") == "WARNING"
    )
    return build_report(Path(os.path.abspath(config_path)), config, state)


def report_exit_code(report: dict[str, Any]) -> int:
    if int(report.get("summary", {}).get("unexpected_errors", 0)):
        return 1
    if report.get("coverage", {}).get("status") == "FAILED":
        return 1
    if report.get("audit", {}).get("static", {}).get("status") == "FAIL":
        return 1
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-depth", type=int)
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--json-only", action="store_true")
    output_group.add_argument("--md-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output or default_output_root()
    default_write_roots = (output,) if args.output is None else ()
    exit_code = 0
    try:
        report = run_scan(args.config, output, args.max_depth)
    except Exception as exc:
        exit_code = 1
        now = datetime.now().astimezone().isoformat()
        error_text = str(exc)
        for value in (str(args.config), os.path.abspath(args.config)):
            error_text = error_text.replace(value, args.config.name)
        fallback_config: dict[str, Any] = {}
        report = {
            "schema_version": LEGACY_REPORT_SCHEMA_VERSION,
            "tool_version": TOOL_VERSION,
            "generated_at": now,
            "config_used": args.config.name,
            "config_fingerprint": config_fingerprint(fallback_config),
            "scan_paths": [],
            "path_reporting": {
                "mode": "relative",
                "message": "No scan paths were loaded because configuration failed.",
            },
            "summary": {
                "total_files_scanned": 0,
                "total_dirs_scanned": 0,
                "logical_size_bytes": 0,
                "logical_size_mb": 0.0,
                "total_size_mb": 0.0,
                "allocated_size_bytes": 0,
                "observed_allocated_size_bytes": 0,
                "allocated_size_files": 0,
                "allocated_size_unavailable_files": 0,
                "allocated_size_complete": True,
                "hardlink_duplicates_skipped": 0,
                "permission_errors": 0,
                "not_found_errors": 0,
                "interrupted_errors": 0,
                "metadata_errors": 0,
                "unknown_errors": 1,
                "total_errors": 1,
                "unexpected_errors": 1,
                "skipped_paths": 0,
                "candidate_items": 0,
                "reported_items": 0,
                "omitted_items": 0,
                "omitted_errors": 0,
                "omitted_skipped": 0,
            },
            "coverage": {
                "status": "FAILED",
                "planned_roots": 0,
                "roots_started": 0,
                "roots_completed": 0,
                "file_budget": 0,
                "time_budget_seconds": 0,
                "roots": [],
                "definition": (
                    "Coverage could not be evaluated because configuration or "
                    "the safety audit failed."
                ),
            },
            "audit": {
                "static": {
                    "status": "UNKNOWN",
                    "files_checked": 0,
                    "findings": [],
                },
                "snapshot_warnings": 0,
                "limitations": (
                    "The scan did not start, so runtime safety evidence is unavailable."
                ),
            },
            "items": [],
            "top_large_files": [],
            "errors": [
                {
                    "path": args.config.name,
                    "category": "unknown",
                    "errno": getattr(exc, "errno", None),
                    "error": error_text,
                }
            ],
            "skipped": [],
            "safety": {
                "read_only": True,
                "cleanup_performed": False,
                "message": "Manual review only. This report does not authorize or perform cleanup.",
            },
        }
    else:
        exit_code = report_exit_code(report)
    try:
        written = write_reports(
            report,
            output,
            json_only=args.json_only,
            md_only=args.md_only,
            additional_write_roots=default_write_roots,
        )
    except OSError as exc:
        print(f"ERROR: unable to write report output: {exc}")
        return 1
    for path in written:
        print(path)
    return exit_code


# Responsibility-owned implementations are bound after the legacy definitions
# above so established imports from this module keep their identity while all
# production calls use the dedicated schema, policy, and rendering modules.
try:
    from scripts.disk_scan_policy import (
        PROTECTED_NAMES,
        audit_policy_for_config,
        build_exclusions,
        exclusion_reason,
        expand_path,
        inventory_path,
        is_link_or_junction,
        is_protected,
        normalized_path,
        path_is_within,
        path_parts_lower,
        policy_for_inventory_path,
    )
    from scripts.disk_scan_schema import (
        ERROR_CATEGORY_FIELDS,
        LEGACY_REPORT_SCHEMA_VERSION,
        REPORT_SCHEMA_VERSION,
        config_fingerprint,
        load_config,
        load_report,
        parse_report_json,
        validate_report,
    )
    from scripts.disk_scan_rendering import (
        COVERAGE_PRIORITY,
        MIB,
        RISK_ORDER,
        TOOL_VERSION,
        build_report,
        display_coverage,
        display_diagnostic,
        display_item,
        display_message,
        display_path,
        markdown_report,
        markdown_two_stage_report,
        overall_coverage_status,
        write_reports,
    )
except ModuleNotFoundError:
    from disk_scan_policy import (
        PROTECTED_NAMES,
        audit_policy_for_config,
        build_exclusions,
        exclusion_reason,
        expand_path,
        inventory_path,
        is_link_or_junction,
        is_protected,
        normalized_path,
        path_is_within,
        path_parts_lower,
        policy_for_inventory_path,
    )
    from disk_scan_schema import (
        ERROR_CATEGORY_FIELDS,
        LEGACY_REPORT_SCHEMA_VERSION,
        REPORT_SCHEMA_VERSION,
        config_fingerprint,
        load_config,
        load_report,
        parse_report_json,
        validate_report,
    )
    from disk_scan_rendering import (
        COVERAGE_PRIORITY,
        MIB,
        RISK_ORDER,
        TOOL_VERSION,
        build_report,
        display_coverage,
        display_diagnostic,
        display_item,
        display_message,
        display_path,
        markdown_report,
        markdown_two_stage_report,
        overall_coverage_status,
        write_reports,
    )


if __name__ == "__main__":
    raise SystemExit(main())
