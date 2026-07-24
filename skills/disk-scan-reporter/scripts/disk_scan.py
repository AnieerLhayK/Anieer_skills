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
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.audit_guard import (
        DEFAULT_POLICY_PATH as DEFAULT_AUDIT_POLICY_PATH,
        compare_snapshots,
        ensure_allowed_write_path,
        load_audit_policy,
        run_static_audit,
        shallow_snapshot,
    )
except ModuleNotFoundError:
    from audit_guard import (
        DEFAULT_POLICY_PATH as DEFAULT_AUDIT_POLICY_PATH,
        compare_snapshots,
        ensure_allowed_write_path,
        load_audit_policy,
        run_static_audit,
        shallow_snapshot,
    )


MIB = 1024 * 1024
SKILL_ROOT = Path(__file__).resolve().parents[1]
REPORT_SCHEMA_VERSION = "1.0.0"
TOOL_VERSION = "1.5.1"
TEMP_EXTENSIONS = {".tmp", ".temp"}
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".tar", ".gz"}
CACHE_NAMES = {".cache", "cache"}
BUILD_NAMES = {"build", "dist", "out", "target", ".next"}
DEPENDENCY_NAMES = {"node_modules", ".venv", "venv", "site-packages"}
PROTECTED_NAMES = {
    ".git",
    "$recycle.bin",
    "windows",
    "program files",
    "program files (x86)",
    "system volume information",
}
RISK_ORDER = {"DO_NOT_TOUCH": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
LARGE_CATEGORIES = {"large_file", "very_large_file"}
PATH_MODES = {"relative", "absolute"}
ERROR_CATEGORY_FIELDS = {
    "permission_denied": "permission_errors",
    "not_found": "not_found_errors",
    "interrupted": "interrupted_errors",
    "metadata_error": "metadata_errors",
    "unknown": "unknown_errors",
}
COVERAGE_PRIORITY = {
    "COMPLETE_WITHIN_CONFIG": 0,
    "PARTIAL_WITH_EXPLAINED_SKIPS": 1,
    "PARTIAL_PERMISSION_LIMITED": 2,
    "PARTIAL_BUDGET_EXHAUSTED": 3,
    "FAILED": 4,
}
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


def expand_path(value: str) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(value))
    return Path(os.path.abspath(expanded))


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
            metadata = os.lstat(path)
            attributes = int(getattr(metadata, "st_file_attributes", 0))
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
) -> str | None:
    parts = path_parts_lower(path)
    if parts & excluded_names:
        return "matched excluded directory name"
    current = normalized_path(Path(os.path.abspath(path)))
    for root in excluded_absolute:
        try:
            if os.path.commonpath([current, root]) == root:
                return "matched excluded path"
        except ValueError:
            continue
    if is_protected(path):
        return "protected system or source-control path"
    return None


def classify_file(path: Path, size: int, modified: float, config: dict[str, Any]) -> tuple[str, str, str]:
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
        return "very_large_file", candidate_risk(path, suffix), "File exceeds the very-large threshold"
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
    if age_days > old_days:
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
    elif (
        not coverage.started
        and coverage.terminal_reason in {"root_excluded", "root_link_skipped"}
    ):
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
) -> RootCoverage:
    excluded_names, excluded_absolute = build_exclusions(list(config.get("exclude_paths", [])))
    max_depth = max(0, int(config.get("max_depth", 8)))
    follow_links = bool(config.get("follow_symlinks", False))
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
    reason = exclusion_reason(root, excluded_names, excluded_absolute)
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
            if depth >= max_depth:
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
                    excluded = exclusion_reason(path, excluded_names, excluded_absolute)
                    if excluded:
                        record_skipped(
                            state,
                            path,
                            excluded,
                            "DO_NOT_TOUCH" if is_protected(path) else "HIGH",
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


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("configuration must be a JSON object")
    if not isinstance(payload.get("scan_paths"), list) or not payload["scan_paths"]:
        raise ValueError("scan_paths must be a non-empty list")
    if not all(isinstance(value, str) and value.strip() for value in payload["scan_paths"]):
        raise ValueError("scan_paths entries must be non-empty strings")
    path_mode = str(payload.get("report_path_mode", "relative")).casefold()
    if path_mode not in PATH_MODES:
        raise ValueError("report_path_mode must be 'relative' or 'absolute'")
    payload["report_path_mode"] = path_mode
    for key in (
        "max_depth",
        "max_report_items",
        "max_diagnostic_items",
        "max_files_per_run",
    ):
        if int(payload.get(key, 0)) < 0:
            raise ValueError(f"{key} must be zero or greater")
    if float(payload.get("max_scan_seconds", 0)) < 0:
        raise ValueError("max_scan_seconds must be zero or greater")
    return payload


def config_fingerprint(config: dict[str, Any]) -> str:
    serialized = json.dumps(
        config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def validate_report(report: dict[str, Any]) -> None:
    if not isinstance(report, dict):
        raise ValueError("report must be a JSON object")
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise ValueError(
            "unsupported report schema version: "
            f"{report.get('schema_version')!r}"
        )
    for key in ("tool_version", "generated_at", "config_used"):
        if not isinstance(report.get(key), str) or not report[key]:
            raise ValueError(f"report field must be a non-empty string: {key}")
    required_objects = ("path_reporting", "summary", "coverage", "audit", "safety")
    for key in required_objects:
        if not isinstance(report.get(key), dict):
            raise ValueError(f"report field must be an object: {key}")
    required_lists = ("scan_paths", "items", "top_large_files", "errors", "skipped")
    for key in required_lists:
        if not isinstance(report.get(key), list):
            raise ValueError(f"report field must be a list: {key}")
    fingerprint = report.get("config_fingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("config_fingerprint must be a SHA-256 hex string")
    summary = report["summary"]
    for key in (
        "total_files_scanned",
        "total_dirs_scanned",
        "logical_size_bytes",
        "observed_allocated_size_bytes",
        "allocated_size_files",
        "allocated_size_unavailable_files",
        "permission_errors",
        "not_found_errors",
        "interrupted_errors",
        "metadata_errors",
        "unknown_errors",
        "total_errors",
        "hardlink_duplicates_skipped",
    ):
        if not isinstance(summary.get(key), int) or summary[key] < 0:
            raise ValueError(f"summary field must be a non-negative integer: {key}")
    allocated_size = summary.get("allocated_size_bytes")
    if allocated_size is not None and (
        not isinstance(allocated_size, int) or allocated_size < 0
    ):
        raise ValueError("allocated_size_bytes must be null or a non-negative integer")
    if not isinstance(summary.get("allocated_size_complete"), bool):
        raise ValueError("allocated_size_complete must be a boolean")
    for item in report["errors"]:
        if not isinstance(item, dict) or item.get("category") not in ERROR_CATEGORY_FIELDS:
            raise ValueError("error entries must contain a supported category")


def parse_report_json(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    validate_report(payload)
    return payload


def load_report(path: Path) -> dict[str, Any]:
    return parse_report_json(path.read_text(encoding="utf-8-sig"))


def display_path(path: Path | str, roots: list[Path], mode: str) -> str:
    candidate = Path(os.path.abspath(str(path)))
    if mode == "absolute":
        return str(candidate)
    for index, root in enumerate(roots, start=1):
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        label = f"<scan_root_{index}>"
        return label if str(relative) == "." else str(Path(label) / relative)
    return f"<outside_scan_roots>/{candidate.name}"


def display_item(item: dict[str, Any], roots: list[Path], mode: str) -> dict[str, Any]:
    displayed = dict(item)
    displayed["path"] = display_path(item["path"], roots, mode)
    displayed["directory"] = display_path(item["directory"], roots, mode)
    return displayed


def display_message(message: str, roots: list[Path], mode: str) -> str:
    if mode == "absolute":
        return message
    displayed = message
    for index, root in enumerate(roots, start=1):
        displayed = re.sub(
            re.escape(str(root)),
            f"<scan_root_{index}>",
            displayed,
            flags=re.IGNORECASE,
        )
    return displayed


def display_diagnostic(
    item: dict[str, str],
    roots: list[Path],
    mode: str,
) -> dict[str, str]:
    displayed = dict(item)
    displayed["path"] = display_path(item["path"], roots, mode)
    for key in ("error", "reason"):
        if key in displayed:
            displayed[key] = display_message(displayed[key], roots, mode)
    return displayed


def overall_coverage_status(coverage: list[RootCoverage]) -> str:
    if not coverage:
        return "FAILED"
    return max(
        (item.status for item in coverage),
        key=lambda status: COVERAGE_PRIORITY.get(status, 4),
    )


def display_coverage(
    coverage: RootCoverage,
    roots: list[Path],
    mode: str,
) -> dict[str, Any]:
    payload = asdict(coverage)
    payload["planned_root"] = display_path(
        coverage.planned_root,
        roots,
        mode,
    )
    for key in ("before_snapshot", "after_snapshot"):
        snapshot = payload.get(key)
        if snapshot and snapshot.get("error"):
            snapshot["error"] = display_message(snapshot["error"], roots, mode)
    return payload


def build_report(config_path: Path, config: dict[str, Any], state: ScanState) -> dict[str, Any]:
    generated_at = datetime.now().astimezone().isoformat()
    roots = [expand_path(str(value)) for value in config["scan_paths"]]
    path_mode = str(config.get("report_path_mode", "relative")).casefold()
    sorted_items = sorted(
        [display_item(item, roots, path_mode) for item in state.items],
        key=lambda item: (RISK_ORDER.get(item["risk"], 0), item["size_mb"]),
        reverse=True,
    )
    allocated_complete = state.allocated_size_unavailable_files == 0
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "generated_at": generated_at,
        "config_used": display_path(config_path, roots, path_mode),
        "config_fingerprint": config_fingerprint(config),
        "scan_paths": [
            str(root) if path_mode == "absolute" else f"<scan_root_{index}>"
            for index, root in enumerate(roots, start=1)
        ],
        "path_reporting": {
            "mode": path_mode,
            "message": (
                "Paths are relative to numbered scan roots; inspect the local configuration "
                "to map labels to exact locations."
                if path_mode == "relative"
                else "Paths are reported as absolute local filesystem locations."
            ),
        },
        "summary": {
            "total_files_scanned": state.total_files,
            "total_dirs_scanned": state.total_dirs,
            "logical_size_bytes": state.total_logical_bytes,
            "logical_size_mb": round(state.total_logical_bytes / MIB, 3),
            "total_size_mb": round(state.total_logical_bytes / MIB, 3),
            "allocated_size_bytes": (
                state.observed_allocated_bytes if allocated_complete else None
            ),
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
            "reported_items": len(sorted_items),
            "omitted_items": state.omitted_items,
            "omitted_errors": state.omitted_errors,
            "omitted_skipped": state.omitted_skipped,
        },
        "coverage": {
            "status": overall_coverage_status(state.coverage),
            "planned_roots": len(config["scan_paths"]),
            "roots_started": sum(1 for item in state.coverage if item.started),
            "roots_completed": sum(1 for item in state.coverage if item.completed),
            "file_budget": int(config.get("max_files_per_run", 100000)),
            "time_budget_seconds": float(config.get("max_scan_seconds", 120)),
            "roots": [
                display_coverage(item, roots, path_mode)
                for item in state.coverage
            ],
            "definition": (
                "Coverage is evaluated against configured roots and budgets, "
                "not against an entire drive."
            ),
        },
        "audit": state.audit,
        "items": sorted_items,
        "top_large_files": [
            display_item(row[2], roots, path_mode)
            for row in sorted(state.top_large, key=lambda row: row[0], reverse=True)
        ],
        "errors": [
            display_diagnostic(item, roots, path_mode)
            for item in state.errors
        ],
        "skipped": [
            display_diagnostic(item, roots, path_mode)
            for item in state.skipped
        ],
        "safety": {
            "read_only": True,
            "cleanup_performed": False,
            "message": "Manual review only. This report does not authorize or perform cleanup.",
        },
    }


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    coverage = report["coverage"]
    audit = report["audit"]
    items = report["items"]
    top_large = report["top_large_files"]
    high_risk = [item for item in items if item["risk"] == "HIGH"][:100]
    do_not_touch = [item for item in items if item["risk"] == "DO_NOT_TOUCH"][:100]
    skipped_protected = [item for item in report["skipped"] if item["risk"] == "DO_NOT_TOUCH"][:100]

    def item_lines(rows: list[dict[str, Any]]) -> list[str]:
        if not rows:
            return ["- None."]
        return [
            f"- `{row['risk']}` `{row['category']}` {row['size_mb']:.3f} MiB — `{row['path']}` — {row['reason']}"
            for row in rows
        ]

    def simple_lines(rows: list[dict[str, str]], detail_key: str) -> list[str]:
        if not rows:
            return ["- None."]
        return [f"- `{row['path']}` — {row[detail_key]}" for row in rows[:100]]

    coverage_lines = [
        (
            f"- `{row['status']}` `{row['planned_root']}` — "
            f"files `{row['files_scanned']}`, dirs `{row['dirs_scanned']}`, "
            f"terminal reason `{row['terminal_reason']}`"
        )
        for row in coverage["roots"]
    ] or ["- None."]
    audit_findings = audit.get("static", {}).get("findings", [])
    audit_lines = [
        (
            f"- `{row['severity']}` `{row['rule']}` "
            f"`{Path(row['path']).name}:{row['line']}` — {row['message']}"
        )
        for row in audit_findings[:100]
    ] or ["- None."]

    lines = [
        "# Disk Scan Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        f"- Configuration: `{report['config_used']}`",
        "- Safety: read-only metadata scan; no cleanup was performed.",
        f"- Path reporting: {report['path_reporting']['message']}",
        "",
        "## Scan Scope",
        "",
        *[f"- `{path}`" for path in report["scan_paths"]],
        "",
        "## Overall Usage Summary",
        "",
        f"- Files scanned: `{summary['total_files_scanned']}`",
        f"- Directories scanned: `{summary['total_dirs_scanned']}`",
        f"- Logical size observed: `{summary['logical_size_mb']:.3f} MiB`",
        f"- Allocated size complete: `{str(summary['allocated_size_complete']).lower()}`",
        f"- Observed allocated bytes: `{summary['observed_allocated_size_bytes']}`",
        f"- Hardlink duplicates skipped: `{summary['hardlink_duplicates_skipped']}`",
        f"- Candidate items: `{summary['candidate_items']}`",
        f"- Detailed items reported: `{summary['reported_items']}`",
        f"- Candidate items omitted by report limit: `{summary['omitted_items']}`",
        f"- Permission errors: `{summary['permission_errors']}`",
        f"- Not-found errors: `{summary['not_found_errors']}`",
        f"- Interrupted errors: `{summary['interrupted_errors']}`",
        f"- Metadata errors: `{summary['metadata_errors']}`",
        f"- Unknown errors: `{summary['unknown_errors']}`",
        f"- Unexpected scan errors: `{summary['unexpected_errors']}`",
        f"- Skipped paths: `{summary['skipped_paths']}`",
        f"- Error details omitted by limit: `{summary['omitted_errors']}`",
        f"- Skipped-path details omitted by limit: `{summary['omitted_skipped']}`",
        "",
        "## Safety Audit",
        "",
        f"- Static audit: `{audit.get('static', {}).get('status', 'UNKNOWN')}`",
        f"- Production files checked: `{audit.get('static', {}).get('files_checked', 0)}`",
        f"- Cleanup performed: `{str(report['safety']['cleanup_performed']).lower()}`",
        f"- Shallow snapshot warnings: `{audit.get('snapshot_warnings', 0)}`",
        *audit_lines,
        "",
        "## Coverage Audit",
        "",
        f"- Coverage status: `{coverage['status']}`",
        f"- Planned roots: `{coverage['planned_roots']}`",
        f"- Roots started: `{coverage['roots_started']}`",
        f"- Roots completed: `{coverage['roots_completed']}`",
        f"- File budget: `{coverage['file_budget']}`",
        f"- Time budget: `{coverage['time_budget_seconds']}` seconds",
        f"- Definition: {coverage['definition']}",
        *coverage_lines,
        "",
        "## Top Large Files",
        "",
        *item_lines(top_large),
        "",
        "## Manual-Review Candidates",
        "",
        *item_lines(items[:100]),
        "",
        "## High-Risk Items",
        "",
        *item_lines(high_risk),
        "",
        "## DO_NOT_TOUCH Items",
        "",
        *item_lines(do_not_touch),
        *simple_lines(skipped_protected, "reason"),
        "",
        "## Skipped Paths",
        "",
        *simple_lines(report["skipped"], "reason"),
        "",
        "## Permission and Metadata Errors",
        "",
        *simple_lines(report["errors"], "error"),
        "",
        "## Safety Notice",
        "",
        "This report will not and should not automatically clean up any file. "
        "Every candidate requires manual confirmation and independent verification.",
        "",
    ]
    return "\n".join(lines)


def write_reports(
    report: dict[str, Any],
    output: Path,
    *,
    json_only: bool,
    md_only: bool,
    audit_policy: dict[str, Any] | None = None,
) -> list[Path]:
    validate_report(report)
    safe_output = ensure_allowed_write_path(
        output,
        SKILL_ROOT,
        audit_policy or load_audit_policy(),
    )
    safe_output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")
    base = safe_output / f"disk_report_{stamp}"
    written: list[Path] = []
    if not md_only:
        json_path = base.with_suffix(".json")
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(json_path)
    if not json_only:
        md_path = base.with_suffix(".md")
        md_path.write_text(markdown_report(report), encoding="utf-8")
        written.append(md_path)
    return written


def audit_policy_for_config(
    config_path: Path,
    config: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    if "audit_policy" not in config:
        return DEFAULT_AUDIT_POLICY_PATH, load_audit_policy(DEFAULT_AUDIT_POLICY_PATH)
    name = str(config["audit_policy"])
    candidate = Path(name)
    if candidate.is_absolute() or candidate.name != name:
        raise ValueError("audit_policy must name a file in the config directory")
    policy_path = Path(os.path.abspath(config_path.parent / candidate))
    if policy_path.parent != Path(os.path.abspath(config_path.parent)):
        raise ValueError("audit_policy must stay in the config directory")
    return policy_path, load_audit_policy(policy_path)


def run_scan(config_path: Path, output: Path, max_depth: int | None = None) -> dict[str, Any]:
    config = load_config(config_path)
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
    snapshot_name_hash = bool(
        snapshot_config.get("include_direct_child_name_hash", True)
    )
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
        if item.snapshot_comparison
        and item.snapshot_comparison.get("status") == "WARNING"
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
    parser.add_argument("--output", type=Path, default=Path("reports"))
    parser.add_argument("--max-depth", type=int)
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--json-only", action="store_true")
    output_group.add_argument("--md-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exit_code = 0
    try:
        report = run_scan(args.config, args.output, args.max_depth)
    except Exception as exc:
        exit_code = 1
        now = datetime.now().astimezone().isoformat()
        error_text = str(exc)
        for value in (str(args.config), os.path.abspath(args.config)):
            error_text = error_text.replace(value, args.config.name)
        fallback_config: dict[str, Any] = {}
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
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
            args.output,
            json_only=args.json_only,
            md_only=args.md_only,
        )
    except OSError as exc:
        print(f"ERROR: unable to write report output: {exc}")
        return 1
    for path in written:
        print(path)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
