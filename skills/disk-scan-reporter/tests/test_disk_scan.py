from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.disk_scan import (
    MIB,
    REPORT_SCHEMA_VERSION,
    RootCoverage,
    ScanState,
    allocated_size_bytes,
    build_report,
    classify_file,
    classify_scan_error,
    config_fingerprint,
    load_report,
    markdown_report,
    parse_report_json,
    record_error,
    report_exit_code,
    run_scan,
    scan_root,
)
from scripts.output_paths import default_output_root


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = SKILL_ROOT / "scripts" / "disk_scan.py"
SCHEMA_PATH = SKILL_ROOT / "references" / "report_schema.json"


class DiskScanTests(unittest.TestCase):
    def test_default_output_prefers_environment_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            staging = Path(temp) / "configured"
            output = default_output_root(
                environment={"AI_TOOL_STAGING_DIR": str(staging)},
                manifest_path=Path(temp) / "missing-manifest.json",
                temp_root=Path(temp) / "fallback",
            )
            self.assertEqual(output, staging.resolve() / "disk-scan-reporter")

    def test_default_output_uses_host_manifest_then_system_temp(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "manifest.json"
            staging = root / "host-staging"
            manifest.write_text(
                json.dumps({"runtime_roots": {"staging": str(staging)}}),
                encoding="utf-8",
            )
            self.assertEqual(
                default_output_root(
                    environment={}, manifest_path=manifest, temp_root=root / "fallback"
                ),
                staging.resolve() / "disk-scan-reporter",
            )
            manifest.write_text("{}", encoding="utf-8")
            self.assertEqual(
                default_output_root(
                    environment={}, manifest_path=manifest, temp_root=root / "fallback"
                ),
                (root / "fallback" / "disk-scan-reporter").resolve(),
            )

    def test_cli_without_output_writes_to_environment_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            environment = os.environ.copy()
            environment["AI_TOOL_STAGING_DIR"] = str(root / "staging")
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPT_PATH), "--config", str(root / "missing.json")],
                cwd=root,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            reports = list((root / "staging" / "disk-scan-reporter").glob("*.json"))
            self.assertEqual(len(reports), 1)

    def base_config(self, root: Path) -> dict[str, object]:
        return {
            "scan_paths": [str(root)],
            "exclude_paths": [".git"],
            "large_file_mb": 1,
            "very_large_file_mb": 2,
            "old_file_days": 30,
            "max_depth": 8,
            "follow_symlinks": False,
            "max_report_items": 100,
            "max_diagnostic_items": 100,
            "max_files_per_run": 1000,
            "max_scan_seconds": 60,
            "report_path_mode": "relative",
        }

    def test_large_file_identification(self) -> None:
        path = Path("example.bin")
        category, risk, _ = classify_file(
            path,
            2 * MIB,
            datetime.now(timezone.utc).timestamp(),
            self.base_config(Path(".")),
        )
        self.assertEqual(category, "large_file")
        self.assertEqual(risk, "HIGH")

    def test_log_file_identification(self) -> None:
        category, risk, _ = classify_file(
            Path("service.log"),
            12,
            datetime.now(timezone.utc).timestamp(),
            self.base_config(Path(".")),
        )
        self.assertEqual(category, "log_file")
        self.assertEqual(risk, "MEDIUM")

    def test_old_file_identification(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=90)).timestamp()
        category, risk, _ = classify_file(
            Path("notes.txt"),
            12,
            old,
            self.base_config(Path(".")),
        )
        self.assertEqual(category, "old_file")
        self.assertEqual(risk, "HIGH")

    def test_old_file_can_be_auxiliary_only(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=90)).timestamp()
        config = self.base_config(Path("."))
        config["old_file_is_candidate"] = False
        category, risk, _ = classify_file(Path("notes.txt"), 12, old, config)
        self.assertEqual(category, "unknown")
        self.assertEqual(risk, "HIGH")

    def test_two_stage_plan_reports_lower_bounds_and_path_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            c_root = root / "c"
            d_root = root / "d"
            current_user = c_root / "Users" / "current"
            data = d_root / "data"
            codex_data = d_root / "AI" / "data" / "codex"
            system = d_root / "System Volume Information"
            for path in (current_user, data, codex_data, system):
                path.mkdir(parents=True, exist_ok=True)
            (current_user / "profile.log").write_text("x", encoding="utf-8")
            (data / "data.log").write_text("x", encoding="utf-8")
            (codex_data / "protected.log").write_text("x", encoding="utf-8")
            config = {
                "two_stage_plan": {
                    "max_total_seconds": 60,
                    "deep_max_files_per_target": 100,
                    "deep_max_seconds_per_target": 30,
                    "drives": [
                        {
                            "label": "C",
                            "root": str(c_root),
                            "inventory_max_depth": 4,
                            "inventory_max_files": 100,
                            "inventory_max_seconds": 30,
                            "deep_threshold_gib": 0,
                            "hard_protected_paths": [],
                            "review_only_paths": [],
                            "auto_deep_paths": [str(current_user)],
                            "auto_deep_direct_children": False,
                        },
                        {
                            "label": "D",
                            "root": str(d_root),
                            "inventory_max_depth": 4,
                            "inventory_max_files": 100,
                            "inventory_max_seconds": 30,
                            "deep_threshold_gib": 0,
                            "hard_protected_paths": [str(system)],
                            "review_only_paths": [str(d_root / "AI"), str(codex_data)],
                            "auto_deep_paths": [],
                            "auto_deep_direct_children": True,
                        },
                    ],
                },
                "large_file_mb": 1,
                "very_large_file_mb": 2,
                "old_file_days": 30,
                "max_report_items": 100,
                "max_diagnostic_items": 100,
                "report_path_mode": "relative",
            }
            config_path = root / "plan.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            report = run_scan(config_path, root / "reports")
            self.assertEqual(report["schema_version"], REPORT_SCHEMA_VERSION)
            self.assertEqual(report["stages"]["inventory"]["mode"], "bounded_lower_bound")
            self.assertEqual(report["coverage"]["roots"][0]["planned_root"], "<inventory_C>")
            aggregates = report["stages"]["inventory"]["directory_aggregates"]
            data_row = next(row for row in aggregates if row["path"].endswith("data"))
            codex_row = next(row for row in aggregates if row["path"].endswith("AI\\data\\codex"))
            self.assertTrue(data_row["lower_bound"])
            self.assertTrue(data_row["promoted"])
            self.assertEqual(codex_row["policy"], "review_only")
            self.assertFalse(codex_row["promoted"])
            system_row = next(row for row in aggregates if row["path"].endswith("System Volume Information"))
            self.assertEqual(system_row["policy"], "hard_protected")
            self.assertNotIn(str(root), json.dumps(report))
            self.assertEqual(parse_report_json(json.dumps(report)), report)
            one_byte_gib = 1 / (1024 * MIB)
            for drive in config["two_stage_plan"]["drives"]:
                drive["deep_threshold_gib"] = one_byte_gib
            config_path.write_text(json.dumps(config), encoding="utf-8")
            strict_report = run_scan(config_path, root / "reports")
            self.assertEqual(strict_report["stages"]["deep_scan"]["targets"], [])
            config["report_path_mode"] = "absolute"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "requires report_path_mode 'relative'"):
                run_scan(config_path, root / "reports")

    def test_exclude_paths_take_effect(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            excluded = root / ".git"
            excluded.mkdir()
            (excluded / "large.log").write_bytes(b"x" * 20)
            visible = root / "visible.log"
            visible.write_text("ok", encoding="utf-8")
            state = ScanState()
            scan_root(root, self.base_config(root), state)
            self.assertEqual(state.total_files, 1)
            self.assertEqual(state.items[0]["path"], str(visible))
            self.assertTrue(any(row["path"] == str(excluded) for row in state.skipped))

    def test_json_report_has_required_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "config.json"
            (root / "sample.log").write_text("hello", encoding="utf-8")
            config_path.write_text(json.dumps(self.base_config(root)), encoding="utf-8")
            report = run_scan(config_path, root / "reports")
            for key in ("generated_at", "config_used", "summary", "items", "errors", "skipped"):
                self.assertIn(key, report)
            self.assertIn("top_large_files", report)
            for key in (
                "total_files_scanned",
                "total_dirs_scanned",
                "total_size_mb",
                "permission_errors",
                "skipped_paths",
            ):
                self.assertIn(key, report["summary"])
            self.assertTrue(report["safety"]["read_only"])
            self.assertFalse(report["safety"]["cleanup_performed"])
            self.assertEqual(report["path_reporting"]["mode"], "relative")

    def test_scan_errors_are_classified_without_inflating_permissions(self) -> None:
        self.assertEqual(classify_scan_error(PermissionError()), "permission_denied")
        self.assertEqual(classify_scan_error(FileNotFoundError()), "not_found")
        self.assertEqual(classify_scan_error(InterruptedError()), "interrupted")
        self.assertEqual(classify_scan_error(OSError("metadata")), "metadata_error")
        self.assertEqual(classify_scan_error(RuntimeError("unexpected")), "unknown")

        state = ScanState()
        coverage = RootCoverage(planned_root="fixture")
        record_error(
            state,
            "missing",
            FileNotFoundError("gone"),
            10,
            coverage=coverage,
        )
        self.assertEqual(state.permission_errors, 0)
        self.assertEqual(state.not_found_errors, 1)
        self.assertEqual(coverage.not_found_errors, 1)
        self.assertEqual(state.errors[0]["category"], "not_found")

    def test_allocated_size_uses_block_metadata_when_available(self) -> None:
        metadata = SimpleNamespace(st_blocks=8)
        self.assertEqual(
            allocated_size_bytes(Path("unused"), metadata),
            4096,
        )

    def test_scan_reports_allocated_size_when_platform_supports_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "sample.log").write_bytes(b"x")
            state = ScanState()
            scan_root(root, self.base_config(root), state)
            report = build_report(root / "config.json", self.base_config(root), state)

            self.assertEqual(report["summary"]["allocated_size_files"], 1)
            self.assertEqual(
                report["summary"]["allocated_size_unavailable_files"],
                0,
            )
            self.assertTrue(report["summary"]["allocated_size_complete"])
            self.assertIsInstance(report["summary"]["allocated_size_bytes"], int)

    def test_hardlinks_are_counted_once_for_size_and_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "original.log"
            linked = root / "linked.log"
            original.write_bytes(b"x" * 4096)
            try:
                os.link(original, linked)
            except OSError as exc:
                self.skipTest(f"hardlinks unavailable: {exc}")

            state = ScanState()
            scan_root(root, self.base_config(root), state)

            self.assertEqual(state.total_files, 2)
            self.assertEqual(state.total_logical_bytes, 4096)
            self.assertEqual(state.hardlink_duplicates_skipped, 1)
            self.assertEqual(state.candidate_count, 1)

    def test_json_report_roundtrip_preserves_unicode_and_control_chars(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state = ScanState(
                errors=[
                    {
                        "path": str(root / "磁盘.log"),
                        "category": "unknown",
                        "errno": None,
                        "error": "错误\t详情\n下一行",
                    }
                ],
                error_count=1,
                unknown_errors=1,
            )
            report = build_report(root / "config.json", self.base_config(root), state)
            text = json.dumps(report, ensure_ascii=False)
            self.assertEqual(parse_report_json(text), report)

            report_path = root / "roundtrip.json"
            report_path.write_text(text, encoding="utf-8")
            self.assertEqual(load_report(report_path), report)

    def test_unknown_report_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = build_report(
                root / "config.json",
                self.base_config(root),
                ScanState(),
            )
            report["schema_version"] = "999.0.0"
            with self.assertRaisesRegex(ValueError, "unsupported report schema"):
                parse_report_json(json.dumps(report))

    def test_schema_and_config_fingerprint_contract(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            REPORT_SCHEMA_VERSION,
        )
        self.assertEqual(
            config_fingerprint({"b": 2, "a": "磁盘"}),
            config_fingerprint({"a": "磁盘", "b": 2}),
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = build_report(
                root / "config.json",
                self.base_config(root),
                ScanState(),
            )
            report["config_fingerprint"] = "z" * 64
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                parse_report_json(json.dumps(report))

    def test_root_junction_is_not_resolved_before_link_check(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "target"
            target.mkdir()
            (target / "inside.log").write_text("private", encoding="utf-8")
            junction = root / "junction"
            if os.name == "nt":
                result = subprocess.run(
                    ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    self.skipTest(result.stderr.strip() or result.stdout.strip())
            else:
                os.symlink(target, junction, target_is_directory=True)
            try:
                config_path = root / "config.json"
                config = self.base_config(junction)
                config_path.write_text(json.dumps(config), encoding="utf-8")
                report = run_scan(config_path, root / "reports")
                self.assertEqual(report["summary"]["total_files_scanned"], 0)
                self.assertEqual(report["summary"]["skipped_paths"], 1)
                self.assertEqual(
                    report["coverage"]["status"],
                    "PARTIAL_WITH_EXPLAINED_SKIPS",
                )
                self.assertIn("link or junction not followed", report["skipped"][0]["reason"])
            finally:
                if junction.is_symlink():
                    junction.unlink()
                elif junction.exists():
                    os.rmdir(junction)

    def test_top_large_files_excludes_small_classified_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "small.log").write_text("hello", encoding="utf-8")
            config = self.base_config(root)
            state = ScanState()
            scan_root(root, config, state)
            report = build_report(root / "config.json", config, state)
            self.assertEqual(report["summary"]["candidate_items"], 1)
            self.assertEqual(report["top_large_files"], [])

    def test_diagnostic_records_are_bounded_but_totals_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            excluded_names = []
            for index in range(4):
                name = f"excluded-{index}"
                excluded_names.append(name)
                (root / name).mkdir()
            config = self.base_config(root)
            config["exclude_paths"] = excluded_names
            config["max_diagnostic_items"] = 2
            state = ScanState()
            scan_root(root, config, state)
            report = build_report(root / "config.json", config, state)
            self.assertEqual(report["summary"]["skipped_paths"], 4)
            self.assertEqual(len(report["skipped"]), 2)
            self.assertEqual(report["summary"]["omitted_skipped"], 2)

    def test_relative_path_mode_omits_absolute_root_from_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "private.log").write_text("hello", encoding="utf-8")
            config_path = root / "private-config.json"
            config_path.write_text(json.dumps(self.base_config(root)), encoding="utf-8")
            report = run_scan(config_path, root / "reports")
            serialized = json.dumps(report)
            self.assertNotIn(str(root), serialized)
            self.assertEqual(report["scan_paths"], ["<scan_root_1>"])
            self.assertTrue(report["items"][0]["path"].startswith("<scan_root_1>"))

    def test_relative_path_mode_redacts_paths_inside_error_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.base_config(root)
            state = ScanState(
                errors=[
                    {
                        "path": str(root / "private.log"),
                        "error": f"access denied: {root / 'private.log'}",
                    }
                ],
                error_count=1,
            )
            report = build_report(root / "config.json", config, state)
            serialized = json.dumps(report)
            self.assertNotIn(str(root), serialized)
            self.assertIn("<scan_root_1>", report["errors"][0]["error"])

    def test_relative_path_mode_redacts_snapshot_error_messages(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.base_config(root)
            state = ScanState(
                coverage=[
                    RootCoverage(
                        planned_root=str(root),
                        started=True,
                        status="PARTIAL_PERMISSION_LIMITED",
                        before_snapshot={
                            "available": False,
                            "error": f"access denied: {root}",
                        },
                    )
                ]
            )
            report = build_report(root / "config.json", config, state)
            serialized = json.dumps(report)
            self.assertNotIn(str(root), serialized)
            self.assertIn(
                "<scan_root_1>",
                report["coverage"]["roots"][0]["before_snapshot"]["error"],
            )

    def test_max_depth_stops_before_deeper_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child = root / "child"
            child.mkdir()
            (child / "hidden.log").write_text("hello", encoding="utf-8")
            config = self.base_config(root)
            config["max_depth"] = 1
            state = ScanState()
            scan_root(root, config, state)
            self.assertEqual(state.total_files, 0)
            self.assertEqual(state.skipped_count, 1)

    def test_candidate_limit_preserves_total_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(3):
                (root / f"candidate-{index}.log").write_text("hello", encoding="utf-8")
            config = self.base_config(root)
            config["max_report_items"] = 1
            state = ScanState()
            scan_root(root, config, state)
            report = build_report(root / "config.json", config, state)
            self.assertEqual(report["summary"]["candidate_items"], 3)
            self.assertEqual(report["summary"]["reported_items"], 1)
            self.assertEqual(report["summary"]["omitted_items"], 2)

    def test_markdown_report_renders_limits_and_path_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.base_config(root)
            report = build_report(root / "config.json", config, ScanState())
            markdown = markdown_report(report)
            self.assertIn("Path reporting:", markdown)
            self.assertIn("Error details omitted by limit:", markdown)
            self.assertIn("## Coverage Audit", markdown)
            self.assertIn("## Safety Audit", markdown)
            self.assertIn("## Top Large Files", markdown)

    def test_invalid_config_returns_nonzero_cli_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with tempfile.TemporaryDirectory(
                dir=SKILL_ROOT / "reports",
            ) as output:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT_PATH),
                        "--config",
                        str(root / "missing.json"),
                        "--output",
                        output,
                    ],
                    cwd=SKILL_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(list(Path(output).glob("*.json"))), 1)

    def test_complete_coverage_is_reported_per_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "sample.log").write_text("hello", encoding="utf-8")
            config = self.base_config(root)
            state = ScanState()
            scan_root(root, config, state)
            report = build_report(root / "config.json", config, state)
            self.assertEqual(report["coverage"]["status"], "COMPLETE_WITHIN_CONFIG")
            self.assertEqual(report["coverage"]["roots_completed"], 1)
            self.assertEqual(
                report["coverage"]["roots"][0]["terminal_reason"],
                "completed",
            )

    def test_file_budget_produces_partial_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for index in range(3):
                (root / f"sample-{index}.log").write_text("hello", encoding="utf-8")
            config = self.base_config(root)
            config["max_files_per_run"] = 1
            state = ScanState()
            coverage = scan_root(root, config, state)
            self.assertEqual(coverage.status, "PARTIAL_BUDGET_EXHAUSTED")
            self.assertTrue(coverage.file_budget_hit)
            self.assertFalse(coverage.completed)
            self.assertEqual(state.total_files, 1)

    @patch("scripts.disk_scan.time.monotonic", side_effect=[0.0, 2.0])
    def test_time_budget_produces_partial_coverage(self, _monotonic) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = self.base_config(root)
            state = ScanState()
            coverage = scan_root(root, config, state, deadline=1.0)
            self.assertEqual(coverage.status, "PARTIAL_BUDGET_EXHAUSTED")
            self.assertTrue(coverage.time_budget_hit)

    def test_missing_root_produces_failed_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "missing"
            config = self.base_config(root)
            state = ScanState()
            coverage = scan_root(root, config, state)
            self.assertEqual(coverage.status, "FAILED")
            self.assertEqual(coverage.terminal_reason, "scan_path_missing")

    @patch("scripts.disk_scan.scan_root", side_effect=RuntimeError("boom"))
    def test_unexpected_scan_failure_returns_nonzero_status(self, _scan_root) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "config.json"
            config_path.write_text(json.dumps(self.base_config(root)), encoding="utf-8")
            report = run_scan(config_path, root / "reports")
            self.assertEqual(report["summary"]["unexpected_errors"], 1)
            self.assertEqual(report_exit_code(report), 1)

    def test_scan_never_calls_deletion_apis(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "candidate.tmp").write_text("temporary", encoding="utf-8")
            state = ScanState()
            with (
                patch("os.remove") as remove,
                patch("os.unlink") as unlink,
                patch("os.rmdir") as rmdir,
            ):
                scan_root(root, self.base_config(root), state)
            remove.assert_not_called()
            unlink.assert_not_called()
            rmdir.assert_not_called()
            self.assertTrue((root / "candidate.tmp").exists())


if __name__ == "__main__":
    unittest.main()
