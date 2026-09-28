from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.audit_remote import evaluate_tree, fetch_tree, load_contract


class AuditRemoteTests(unittest.TestCase):
    def contract(self) -> dict[str, object]:
        return {
            "required_paths": ["README.md"],
            "required_any": [["pyproject.toml", "package.json"]],
            "forbidden_path_prefixes": ["private/"],
            "recommended_paths": [".github/workflows/ci.yml"],
            "allowed_top_level": ["README.md", "pyproject.toml", ".github"],
            "max_blob_bytes": 100,
        }

    def test_evaluate_tree_reports_a_clean_contract(self) -> None:
        entries = [
            {"type": "blob", "path": "README.md", "size": 10},
            {"type": "blob", "path": "pyproject.toml", "size": 20},
            {"type": "blob", "path": ".github/workflows/ci.yml", "size": 30},
        ]
        report = evaluate_tree(entries, self.contract())
        self.assertEqual("PASS", report["status"])

    def test_evaluate_tree_detects_boundary_and_structure_failures(self) -> None:
        entries = [
            {"type": "blob", "path": "README.md", "size": 101},
            {"type": "blob", "path": "private/data.txt", "size": 1},
            {"type": "blob", "path": "scratch.txt", "size": 1},
        ]
        report = evaluate_tree(entries, self.contract())
        self.assertEqual("FAIL", report["status"])
        self.assertTrue(any("package.json" in error for error in report["errors"]))
        self.assertTrue(any("forbidden path" in error for error in report["errors"]))
        self.assertTrue(any("max_blob_bytes" in error for error in report["errors"]))
        self.assertIn("unexpected top-level path: scratch.txt", report["warnings"])

    def test_load_contract_and_fetch_tree_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            contract_path = Path(temp) / "contract.json"
            contract_path.write_text(json.dumps(self.contract()), encoding="utf-8")
            self.assertEqual(self.contract(), load_contract(contract_path))

        def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(["gh"], 0, '{"tree": [{"type": "blob", "path": "README.md"}]}', "")

        self.assertEqual([{"type": "blob", "path": "README.md"}], fetch_tree("owner/repo", "main", runner))


if __name__ == "__main__":
    unittest.main()
