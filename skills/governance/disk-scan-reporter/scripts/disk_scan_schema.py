"""Configuration and persisted report-schema compatibility helpers."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

REPORT_SCHEMA_VERSION = "2.0.0"
LEGACY_REPORT_SCHEMA_VERSION = "1.0.0"
PATH_MODES = {"relative", "absolute"}
ERROR_CATEGORY_FIELDS = {
    "permission_denied": "permission_errors",
    "not_found": "not_found_errors",
    "interrupted": "interrupted_errors",
    "metadata_error": "metadata_errors",
    "unknown": "unknown_errors",
}


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("configuration must be a JSON object")
    has_legacy_paths = isinstance(payload.get("scan_paths"), list) and bool(payload["scan_paths"])
    has_plan = isinstance(payload.get("two_stage_plan"), dict)
    if not has_legacy_paths and not has_plan:
        raise ValueError("scan_paths or two_stage_plan must be configured")
    if has_legacy_paths and not all(
        isinstance(value, str) and value.strip() for value in payload["scan_paths"]
    ):
        raise ValueError("scan_paths entries must be non-empty strings")
    if has_plan:
        plan = payload["two_stage_plan"]
        drives = plan.get("drives")
        if not isinstance(drives, list) or not drives:
            raise ValueError("two_stage_plan.drives must be a non-empty list")
        for drive in drives:
            if not isinstance(drive, dict) or not isinstance(drive.get("root"), str):
                raise ValueError("each two_stage_plan drive requires a root")
            for key in (
                "inventory_max_depth",
                "inventory_max_files",
                "inventory_max_seconds",
                "deep_threshold_gib",
            ):
                if key not in drive or float(drive[key]) < 0:
                    raise ValueError(f"two_stage_plan drive requires non-negative {key}")
        for key in (
            "max_total_seconds",
            "deep_max_files_per_target",
            "deep_max_seconds_per_target",
        ):
            if key not in plan or float(plan[key]) < 0:
                raise ValueError(f"two_stage_plan requires non-negative {key}")
    path_mode = str(payload.get("report_path_mode", "relative")).casefold()
    if path_mode not in PATH_MODES:
        raise ValueError("report_path_mode must be 'relative' or 'absolute'")
    if has_plan and path_mode != "relative":
        raise ValueError("two_stage_plan requires report_path_mode 'relative'")
    payload["report_path_mode"] = path_mode
    for key in ("max_depth", "max_report_items", "max_diagnostic_items", "max_files_per_run"):
        if payload.get(key) is not None and int(payload.get(key, 0)) < 0:
            raise ValueError(f"{key} must be zero or greater")
    if float(payload.get("max_scan_seconds", 0)) < 0:
        raise ValueError("max_scan_seconds must be zero or greater")
    return payload


def config_fingerprint(config: dict[str, Any]) -> str:
    serialized = json.dumps(
        config, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def validate_report(report: dict[str, Any]) -> None:
    if not isinstance(report, dict):
        raise ValueError("report must be a JSON object")
    if report.get("schema_version") not in {LEGACY_REPORT_SCHEMA_VERSION, REPORT_SCHEMA_VERSION}:
        raise ValueError(f"unsupported report schema version: {report.get('schema_version')!r}")
    for key in ("tool_version", "generated_at", "config_used"):
        if not isinstance(report.get(key), str) or not report[key]:
            raise ValueError(f"report field must be a non-empty string: {key}")
    for key in ("path_reporting", "summary", "coverage", "audit", "safety"):
        if not isinstance(report.get(key), dict):
            raise ValueError(f"report field must be an object: {key}")
    for key in ("scan_paths", "items", "top_large_files", "errors", "skipped"):
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
    if allocated_size is not None and (not isinstance(allocated_size, int) or allocated_size < 0):
        raise ValueError("allocated_size_bytes must be null or a non-negative integer")
    if not isinstance(summary.get("allocated_size_complete"), bool):
        raise ValueError("allocated_size_complete must be a boolean")
    for item in report["errors"]:
        if not isinstance(item, dict) or item.get("category") not in ERROR_CATEGORY_FIELDS:
            raise ValueError("error entries must contain a supported category")
    if report.get("schema_version") == REPORT_SCHEMA_VERSION:
        stages = report.get("stages")
        if not isinstance(stages, dict):
            raise ValueError("schema 2.0 reports must contain stage details")
        inventory, deep_scan = stages.get("inventory"), stages.get("deep_scan")
        if not isinstance(inventory, dict) or not isinstance(deep_scan, dict):
            raise ValueError("schema 2.0 reports must contain inventory and deep_scan stages")
        if (
            not isinstance(inventory.get("drives"), list)
            or not isinstance(inventory.get("directory_aggregates"), list)
            or not isinstance(deep_scan.get("targets"), list)
        ):
            raise ValueError("schema 2.0 report stages are malformed")


def parse_report_json(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    validate_report(payload)
    return payload


def load_report(path: Path) -> dict[str, Any]:
    return parse_report_json(path.read_text(encoding="utf-8-sig"))


__all__ = [
    "ERROR_CATEGORY_FIELDS",
    "LEGACY_REPORT_SCHEMA_VERSION",
    "PATH_MODES",
    "REPORT_SCHEMA_VERSION",
    "config_fingerprint",
    "load_config",
    "load_report",
    "parse_report_json",
    "validate_report",
]
