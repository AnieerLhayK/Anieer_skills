"""Report construction, rendering, and bounded-output serialization."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from scripts.audit_guard import ensure_allowed_write_path, load_audit_policy
    from scripts.disk_scan_policy import expand_path
    from scripts.disk_scan_schema import (
        LEGACY_REPORT_SCHEMA_VERSION,
        REPORT_SCHEMA_VERSION,
        config_fingerprint,
        validate_report,
    )
except ModuleNotFoundError:
    from audit_guard import ensure_allowed_write_path, load_audit_policy
    from disk_scan_policy import expand_path
    from disk_scan_schema import (
        LEGACY_REPORT_SCHEMA_VERSION,
        REPORT_SCHEMA_VERSION,
        config_fingerprint,
        validate_report,
    )

MIB = 1024 * 1024
TOOL_VERSION = "2.0.0"
RISK_ORDER = {"DO_NOT_TOUCH": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
COVERAGE_PRIORITY = {
    "COMPLETE_WITHIN_CONFIG": 0,
    "PARTIAL_WITH_EXPLAINED_SKIPS": 1,
    "PARTIAL_PERMISSION_LIMITED": 2,
    "PARTIAL_BUDGET_EXHAUSTED": 3,
    "FAILED": 4,
}
SKILL_ROOT = Path(__file__).resolve().parents[1]


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
    for index, root in enumerate(roots, start=1):
        message = re.sub(re.escape(str(root)), f"<scan_root_{index}>", message, flags=re.IGNORECASE)
    return message


def display_diagnostic(item: dict[str, str], roots: list[Path], mode: str) -> dict[str, str]:
    displayed = dict(item)
    displayed["path"] = display_path(item["path"], roots, mode)
    for key in ("error", "reason"):
        if key in displayed:
            displayed[key] = display_message(displayed[key], roots, mode)
    return displayed


def overall_coverage_status(coverage: list[Any]) -> str:
    if not coverage:
        return "FAILED"
    return max(
        (item.status for item in coverage), key=lambda status: COVERAGE_PRIORITY.get(status, 4)
    )


def display_coverage(coverage: Any, roots: list[Path], mode: str) -> dict[str, Any]:
    payload = asdict(coverage)
    payload["planned_root"] = display_path(coverage.planned_root, roots, mode)
    for key in ("before_snapshot", "after_snapshot"):
        snapshot = payload.get(key)
        if snapshot and snapshot.get("error"):
            snapshot["error"] = display_message(snapshot["error"], roots, mode)
    return payload


def build_report(config_path: Path, config: dict[str, Any], state: Any) -> dict[str, Any]:
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
        "schema_version": LEGACY_REPORT_SCHEMA_VERSION,
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
            "message": "Paths are relative to numbered scan roots; inspect the local configuration to map labels to exact locations."
            if path_mode == "relative"
            else "Paths are reported as absolute local filesystem locations.",
        },
        "summary": {
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
            "roots": [display_coverage(item, roots, path_mode) for item in state.coverage],
            "definition": "Coverage is evaluated against configured roots and budgets, not against an entire drive.",
        },
        "audit": state.audit,
        "items": sorted_items,
        "top_large_files": [
            display_item(row[2], roots, path_mode)
            for row in sorted(state.top_large, key=lambda row: row[0], reverse=True)
        ],
        "errors": [display_diagnostic(item, roots, path_mode) for item in state.errors],
        "skipped": [display_diagnostic(item, roots, path_mode) for item in state.skipped],
        "safety": {
            "read_only": True,
            "cleanup_performed": False,
            "message": "Manual review only. This report does not authorize or perform cleanup.",
        },
    }


def markdown_two_stage_report(report: dict[str, Any]) -> str:
    inventory, deep_scan = report["stages"]["inventory"], report["stages"]["deep_scan"]
    aggregates, targets = inventory["directory_aggregates"], deep_scan["targets"]
    lines = [
        "# Disk Scan Report",
        "",
        f"- Generated at: `{report['generated_at']}`",
        "- Safety: read-only metadata scan; no cleanup was performed.",
        "- Inventory totals are observed lower bounds, not complete directory sizes.",
        "",
        "## Inventory",
        "",
        *(
            [
                f"- `{row['drive']}` `{row['path']}` — `{row['policy']}`, observed `{row['observed_logical_mb']:.3f}` MiB, promoted `{str(row['promoted']).lower()}`"
                for row in aggregates[:100]
            ]
            or ["- None."]
        ),
        "",
        "## Deep Scan Coverage",
        "",
        *(
            [
                f"- `{row['path']}` — `{row['status']}`, files `{row['files_scanned']}`, terminal reason `{row['terminal_reason']}`"
                for row in targets
            ]
            or ["- No directory qualified for automatic deep scan."]
        ),
        "",
        "## Manual-Review Candidates",
        "",
        *(
            [
                f"- `{row['risk']}` `{row['category']}` `{row['size_mb']:.3f}` MiB — `{row['path']}`"
                for row in report["items"][:100]
            ]
            or ["- None."]
        ),
        "",
        "## Coverage",
        "",
        f"- Status: `{report['coverage']['status']}`",
        f"- Total run budget: `{deep_scan['max_total_seconds']}` seconds",
        "- A budget or depth stop is partial coverage, never permission to broaden scope.",
        "",
        "## Safety Notice",
        "",
        "This report does not authorize cleanup. Every item requires manual confirmation.",
        "",
    ]
    return "\n".join(lines)


def markdown_report(report: dict[str, Any]) -> str:
    if report.get("schema_version") == REPORT_SCHEMA_VERSION:
        return markdown_two_stage_report(report)
    summary, coverage, audit, items, top_large = (
        report["summary"],
        report["coverage"],
        report["audit"],
        report["items"],
        report["top_large_files"],
    )

    def item_lines(rows: list[dict[str, Any]]) -> list[str]:
        return [
            f"- `{row['risk']}` `{row['category']}` {row['size_mb']:.3f} MiB — `{row['path']}` — {row['reason']}"
            for row in rows
        ] or ["- None."]

    def simple_lines(rows: list[dict[str, str]], key: str) -> list[str]:
        return [f"- `{row['path']}` — {row[key]}" for row in rows[:100]] or ["- None."]

    coverage_lines = [
        f"- `{row['status']}` `{row['planned_root']}` — files `{row['files_scanned']}`, dirs `{row['dirs_scanned']}`, terminal reason `{row['terminal_reason']}`"
        for row in coverage["roots"]
    ] or ["- None."]
    audit_lines = [
        f"- `{row['severity']}` `{row['rule']}` `{Path(row['path']).name}:{row['line']}` — {row['message']}"
        for row in audit.get("static", {}).get("findings", [])[:100]
    ] or ["- None."]
    high_risk = [item for item in items if item["risk"] == "HIGH"][:100]
    do_not_touch = [item for item in items if item["risk"] == "DO_NOT_TOUCH"][:100]
    skipped_protected = [item for item in report["skipped"] if item["risk"] == "DO_NOT_TOUCH"][:100]
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
        "This report will not and should not automatically clean up any file. Every candidate requires manual confirmation and independent verification.",
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
    additional_write_roots: tuple[Path, ...] = (),
) -> list[Path]:
    validate_report(report)
    safe_output = ensure_allowed_write_path(
        output, SKILL_ROOT, audit_policy or load_audit_policy(), additional_write_roots
    )
    safe_output.mkdir(parents=True, exist_ok=True)
    base = safe_output / f"disk_report_{datetime.now().astimezone().strftime('%Y-%m-%d_%H%M%S')}"
    written: list[Path] = []
    if not md_only:
        json_path = base.with_suffix(".json")
        json_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        written.append(json_path)
    if not json_only:
        md_path = base.with_suffix(".md")
        md_path.write_text(markdown_report(report), encoding="utf-8")
        written.append(md_path)
    return written


__all__ = [
    "build_report",
    "display_coverage",
    "display_diagnostic",
    "display_item",
    "display_message",
    "display_path",
    "markdown_report",
    "markdown_two_stage_report",
    "overall_coverage_status",
    "write_reports",
]
