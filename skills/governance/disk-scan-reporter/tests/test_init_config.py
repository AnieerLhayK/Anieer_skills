from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import init_config
from scripts.disk_scan_policy import audit_policy_for_config


class InitConfigTests(unittest.TestCase):
    def test_external_write_requires_record_and_lease_before_creating_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scan_target = root / "config" / "scan_config.json"
            policy_target = root / "config" / "audit_policy.json"
            with patch.object(init_config, "default_config_path", return_value=scan_target), \
                    patch.object(init_config, "default_audit_policy_path", return_value=policy_target):
                with self.assertRaisesRegex(ValueError, "--record-id and --lease"):
                    init_config.initialize()
            self.assertFalse(scan_target.exists())
            self.assertFalse(policy_target.exists())

    def test_initialize_copies_templates_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scan_target = root / "config" / "scan_config.json"
            policy_target = root / "config" / "audit_policy.json"
            with patch.object(init_config, "default_config_path", return_value=scan_target), \
                    patch.object(init_config, "default_audit_policy_path", return_value=policy_target), \
                    patch.object(init_config, "require_external_write_authority"):
                kwargs = {"record_id": "TASK-test", "lease": Path("lease.json")}
                self.assertEqual(init_config.initialize(**kwargs), (scan_target, policy_target))
                original_scan = scan_target.read_bytes()
                original_policy = policy_target.read_bytes()
                with self.assertRaises(FileExistsError):
                    init_config.initialize(**kwargs)
                self.assertEqual(scan_target.read_bytes(), original_scan)
                self.assertEqual(policy_target.read_bytes(), original_policy)

    def test_migrate_current_preserves_existing_scan_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_scan = root / "source" / "scan_config.json"
            source_policy = root / "source" / "audit_policy.json"
            scan_target = root / "external" / "config" / "scan_config.json"
            policy_target = root / "external" / "config" / "audit_policy.json"
            source_scan.parent.mkdir()
            config = json.loads(init_config.SCAN_TEMPLATE.read_text(encoding="utf-8"))
            config["two_stage_plan"]["drives"][1]["hard_protected_paths"].append(
                "D:\\AppsData\\archive"
            )
            source_scan.write_text(json.dumps(config), encoding="utf-8")
            source_policy.write_bytes(init_config.POLICY_TEMPLATE.read_bytes())
            original_scan = source_scan.read_bytes()
            original_policy = source_policy.read_bytes()
            with patch.object(init_config, "SOURCE_SCAN_CONFIG", source_scan), \
                    patch.object(init_config, "SOURCE_AUDIT_POLICY", source_policy), \
                    patch.object(init_config, "default_config_path", return_value=scan_target), \
                    patch.object(init_config, "default_audit_policy_path", return_value=policy_target), \
                    patch.object(init_config, "require_external_write_authority"):
                init_config.initialize(
                    migrate_current=True,
                    record_id="TASK-test",
                    lease=Path("lease.json"),
                )
            migrated = json.loads(scan_target.read_text(encoding="utf-8"))
            self.assertIn(
                "D:\\AppsData\\archive",
                migrated["two_stage_plan"]["drives"][1]["hard_protected_paths"],
            )
            self.assertEqual(source_scan.read_bytes(), original_scan)
            self.assertEqual(source_policy.read_bytes(), original_policy)

    def test_sync_audit_policy_requires_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "audit_policy.json"
            policy = json.loads(init_config.POLICY_TEMPLATE.read_text(encoding="utf-8"))
            policy["allowed_write_roots"] = ["reports"]
            target.write_text(json.dumps(policy), encoding="utf-8")
            with patch.object(init_config, "default_audit_policy_path", return_value=target), \
                    patch("builtins.input", return_value="SYNC-AUDIT-POLICY"), \
                    patch.object(init_config, "require_external_write_authority"):
                init_config.sync_audit_policy(record_id="TASK-test", lease=Path("lease.json"))
            self.assertEqual(
                json.loads(target.read_text(encoding="utf-8")),
                json.loads(init_config.POLICY_TEMPLATE.read_text(encoding="utf-8")),
            )
            backups = list(root.glob("audit_policy.backup-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), policy)

    def test_active_audit_policy_must_match_reviewed_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "scan_config.json"
            policy_path = root / "audit_policy.json"
            policy_path.write_bytes(init_config.POLICY_TEMPLATE.read_bytes())
            path, _ = audit_policy_for_config(config_path, {"audit_policy": policy_path.name})
            self.assertEqual(path, policy_path.resolve())

            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["allowed_write_roots"] = ["reports"]
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs from the reviewed template"):
                audit_policy_for_config(config_path, {"audit_policy": policy_path.name})


if __name__ == "__main__":
    unittest.main()
