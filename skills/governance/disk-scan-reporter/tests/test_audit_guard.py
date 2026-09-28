from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.audit_guard import (
    compare_snapshots,
    ensure_allowed_write_path,
    load_audit_policy,
    run_static_audit,
    shallow_snapshot,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]


class AuditGuardTests(unittest.TestCase):
    def test_current_production_scripts_pass_static_audit(self) -> None:
        result = run_static_audit(SKILL_ROOT, load_audit_policy())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["findings"], [])

    def test_destructive_api_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "unsafe.py").write_text(
                "import os\nos.remove('example')\n",
                encoding="utf-8",
            )
            policy = load_audit_policy()
            result = run_static_audit(root, policy)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(
                result["findings"][0]["path"],
                str(Path("scripts") / "unsafe.py"),
            )
            self.assertTrue(
                any(item["rule"] == "destructive_api" for item in result["findings"])
            )

    def test_path_unlink_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "unsafe.py").write_text(
                "from pathlib import Path\nPath('example').unlink()\n",
                encoding="utf-8",
            )
            result = run_static_audit(root, load_audit_policy())
            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any(
                    item["rule"] == "destructive_api"
                    and "unlink" in item["message"]
                    for item in result["findings"]
                )
            )

    def test_write_path_must_stay_in_allowed_roots(self) -> None:
        policy = load_audit_policy()
        allowed = ensure_allowed_write_path(
            SKILL_ROOT / "reports" / "example.json",
            SKILL_ROOT,
            policy,
        )
        self.assertTrue(str(allowed).startswith(str(SKILL_ROOT / "reports")))
        with self.assertRaises(PermissionError):
            ensure_allowed_write_path(
                SKILL_ROOT.parent / "outside.json",
                SKILL_ROOT,
                policy,
            )

    def test_write_path_rejects_junction_escape(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows junction behavior")
        with tempfile.TemporaryDirectory() as temp:
            outside = Path(temp) / "outside"
            outside.mkdir()
            link = SKILL_ROOT / "reports" / "audit-junction-test"
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest(result.stderr.strip() or result.stdout.strip())
            try:
                with self.assertRaises(PermissionError):
                    ensure_allowed_write_path(
                        link / "escaped.json",
                        SKILL_ROOT,
                        load_audit_policy(),
                    )
            finally:
                os.rmdir(link)

    def test_shallow_snapshot_detects_direct_child_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            before = shallow_snapshot(root)
            (root / "new.txt").write_text("metadata probe", encoding="utf-8")
            after = shallow_snapshot(root)
            comparison = compare_snapshots(before, after)
            self.assertEqual(comparison["status"], "WARNING")
            self.assertIn("direct_child_count", comparison["changed_fields"])

    def test_policy_is_valid_json(self) -> None:
        path = SKILL_ROOT / "config" / "audit_policy.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("allowed_write_roots", payload)


if __name__ == "__main__":
    unittest.main()
