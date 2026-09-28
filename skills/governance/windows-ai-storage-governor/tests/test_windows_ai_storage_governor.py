from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(POWERSHELL, "PowerShell is required")
class WindowsAiStorageGovernorTests(unittest.TestCase):
    def run_script(self, name: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPTS / name), *arguments],
            cwd=Path(tempfile.gettempdir()),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_audit_classifies_only_supplied_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "tool-cache"
            candidate.mkdir()
            result = self.run_script("audit-environment.ps1", "-Paths", str(candidate))
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(len(report["findings"]), 1)
            self.assertEqual(report["findings"][0]["classification"], "cache")
            self.assertEqual(report["findings"][0]["disposition"], "migrate-candidate")

    def test_unknown_candidate_is_blocked_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "mystery"
            candidate.mkdir()
            marker = candidate / "keep.txt"
            marker.write_text("unchanged", encoding="utf-8")
            audit_path = root / "audit.json"
            plan_path = root / "plan.json"
            audit = self.run_script(
                "audit-environment.ps1", "-Paths", str(candidate), "-OutputPath", str(audit_path)
            )
            self.assertEqual(audit.returncode, 0, audit.stderr)
            plan = self.run_script(
                "build-migration-plan.ps1",
                "-AuditPath", str(audit_path),
                "-TargetRoot", str(root / "target"),
                "-OutputPath", str(plan_path),
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)
            payload = json.loads(plan.stdout)
            self.assertEqual(payload["status"], "WARNING")
            self.assertEqual(payload["actions"][0]["operation"], "blocked")
            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")
            self.assertFalse((root / "target").exists())

    def test_verify_reports_preserve_action_as_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "tool-config"
            candidate.mkdir()
            audit_path = root / "audit.json"
            plan_path = root / "plan.json"
            audit = self.run_script(
                "audit-environment.ps1", "-Paths", str(candidate), "-OutputPath", str(audit_path)
            )
            self.assertEqual(audit.returncode, 0, audit.stderr)
            plan = self.run_script(
                "build-migration-plan.ps1",
                "-AuditPath", str(audit_path),
                "-TargetRoot", str(root / "target"),
                "-OutputPath", str(plan_path),
            )
            self.assertEqual(plan.returncode, 0, plan.stderr)
            verification = self.run_script("validate-migration.ps1", "-PlanPath", str(plan_path))
            self.assertEqual(verification.returncode, 0, verification.stderr)
            payload = json.loads(verification.stdout)
            self.assertEqual(payload["status"], "PASS")
            self.assertEqual(payload["results"][0]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
