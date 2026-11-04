from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.disk_scan import run_scan, parse_report_json, markdown_report
from scripts import disk_scan_engine


class ManualDeepScanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.drive = self.root / "drive"
        self.target = self.drive / "application-cache"
        self.target.mkdir(parents=True)
        self.protected = self.drive / "protected"
        self.protected.mkdir()
        self.config = {
            "two_stage_plan": {
                "max_total_seconds": 60, "deep_max_files_per_target": 1,
                "deep_max_seconds_per_target": 1,
                "drives": [{"label": "D", "root": str(self.drive),
                            "inventory_max_depth": 2, "inventory_max_files": 100,
                            "inventory_max_seconds": 10, "deep_threshold_gib": 8,
                            "review_only_paths": [str(self.target)],
                            "hard_protected_paths": [str(self.protected)],
                            "auto_deep_direct_children": True}],
            },
            "manual_deep_scan": {"max_total_seconds": 900, "max_total_files": 500000},
            "large_file_mb": 1, "very_large_file_mb": 4,
            "report_path_mode": "relative",
        }
        self.config_path = self.root / "config.json"

    def run_manual(self, targets=None):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        return run_scan(self.config_path, self.root / "reports",
                        deep_scan=targets or [self.target])

    def test_explicit_request_bypasses_threshold_review_and_per_target_limit(self):
        for index in range(3):
            (self.target / str(index)).write_text("unchanged")
        report = self.run_manual()
        self.assertEqual(report["run_mode"], "manual_deep")
        self.assertEqual(report["stages"]["inventory"]["mode"], "not_run")
        self.assertEqual(report["summary"]["total_files_scanned"], 3)
        self.assertEqual(report["coverage"]["status"], "COMPLETE_WITHIN_CONFIG")
        self.assertEqual(parse_report_json(json.dumps(report)), report)
        self.assertIn("manual_deep", markdown_report(report))
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertTrue(all((self.target / str(index)).read_text() == "unchanged" for index in range(3)))
        automatic = run_scan(self.config_path, self.root / "reports")
        self.assertEqual(automatic["stages"]["deep_scan"]["targets"], [])

    def test_shared_file_budget_applies_across_roots(self):
        other = self.drive / "other-cache"
        other.mkdir()
        for folder in (self.target, other):
            for index in range(2):
                (folder / str(index)).write_text("x")
        self.config["manual_deep_scan"]["max_total_files"] = 3
        report = self.run_manual([self.target, other])
        self.assertEqual(report["summary"]["total_files_scanned"], 3)
        self.assertEqual(report["coverage"]["status"], "PARTIAL_BUDGET_EXHAUSTED")
        self.assertEqual(len(report["coverage"]["roots"]), 2)

    def test_duplicates_and_nested_targets_are_scanned_once(self):
        child = self.target / "child"
        child.mkdir()
        (child / "file").write_text("x")
        report = self.run_manual([child, self.target, self.target])
        self.assertEqual(len(report["scan_paths"]), 1)
        self.assertEqual(report["summary"]["total_files_scanned"], 1)

    def test_protected_drive_relative_and_outside_roots_rejected_before_scan(self):
        for target in (self.drive, self.protected, self.protected / "child",
                       self.root / "outside", Path("relative")):
            with self.subTest(target=target), patch.object(disk_scan_engine, "scan_root") as scan:
                with self.assertRaises(ValueError):
                    self.run_manual([target])
                scan.assert_not_called()

    def test_missing_root_reported_and_source_child_skipped(self):
        missing = self.drive / "missing"
        report = self.run_manual([missing])
        self.assertEqual(report["coverage"]["status"], "FAILED")
        repository = self.target / "repository"
        (repository / ".git").mkdir(parents=True)
        (repository / "source.txt").write_text("private")
        (self.target / "cache.bin").write_text("x")
        report = self.run_manual()
        self.assertEqual(report["summary"]["total_files_scanned"], 1)
        self.assertEqual(report["coverage"]["status"], "PARTIAL_WITH_EXPLAINED_SKIPS")

    def test_time_budget_shared_and_no_restart(self):
        self.config["manual_deep_scan"]["max_total_seconds"] = 0.001
        with patch.object(disk_scan_engine.time, "monotonic", side_effect=[0, 1, 1, 1, 1]):
            report = self.run_manual()
        self.assertEqual(report["coverage"]["status"], "PARTIAL_BUDGET_EXHAUSTED")

    def test_invalid_budget_and_max_depth_rejected(self):
        for value in (0, -1, float("inf"), True):
            self.config["manual_deep_scan"]["max_total_seconds"] = value
            with self.assertRaises(ValueError):
                self.run_manual()
        self.config["manual_deep_scan"]["max_total_seconds"] = 900
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")
        with self.assertRaises(ValueError):
            run_scan(self.config_path, self.root / "reports", 3, deep_scan=[self.target])
