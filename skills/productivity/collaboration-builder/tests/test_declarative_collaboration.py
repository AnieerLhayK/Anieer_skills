from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import collaboration_config  # noqa: E402


class DeclarativeCollaborationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def config(self, **updates: object) -> Path:
        data: dict[str, object] = {"schema_version": 1, "layout": "isolated-areas", "roles": ["alpha", "beta"]}
        data.update(updates)
        path = self.root / "source.yaml"
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return path

    def run_bootstrap(self, target: Path, source: Path, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCRIPTS / "bootstrap_collaboration.py"), "--target", str(target), "--project-name", "demo", "--config", str(source), *extra], capture_output=True, text=True, check=False)

    def test_all_builtin_layouts_resolve_generic_paths(self) -> None:
        cases = {
            "isolated-areas": ({}, "areas/alpha"),
            "nested-project-cells": ({"workspace": "sample"}, "workspaces/sample/areas/alpha"),
            "shared-core": ({}, "domains/alpha"),
            "delivery-streams": ({}, "streams/build/areas/alpha"),
        }
        for layout, (variables, expected) in cases.items():
            roles = [{"id": "alpha", "stream": "build"}]
            source = self.config(layout=layout, variables=variables, roles=roles)
            config = collaboration_config.normalize_config(source, SKILL_ROOT)
            self.assertEqual(config["resolved_roles"][0]["path"], expected)

    def test_custom_rejects_escape_and_role_collisions(self) -> None:
        source = self.config(layout="custom", custom={"role_path": "../{role}"})
        with self.assertRaisesRegex(collaboration_config.ConfigError, "escapes"):
            collaboration_config.normalize_config(source, SKILL_ROOT)
        source = self.config(layout="custom", custom={"role_path": "areas/fixed"})
        with self.assertRaisesRegex(collaboration_config.ConfigError, "collide"):
            collaboration_config.normalize_config(source, SKILL_ROOT)

    def test_rejects_missing_layout_variables_invalid_roles_and_invalid_routes(self) -> None:
        source = self.config(layout="nested-project-cells")
        with self.assertRaisesRegex(collaboration_config.ConfigError, "requires variables"):
            collaboration_config.normalize_config(source, SKILL_ROOT)
        source = self.config(roles=["not valid"])
        with self.assertRaisesRegex(collaboration_config.ConfigError, "invalid"):
            collaboration_config.normalize_config(source, SKILL_ROOT)
        source = self.config(tasks={"role_work": {"required_read": ["AGENTS.md"], "write_scope": [], "validation": ["git diff --check"]}})
        with self.assertRaisesRegex(collaboration_config.ConfigError, "write_scope"):
            collaboration_config.normalize_config(source, SKILL_ROOT)

    def test_bootstrap_writes_default_governance_and_normalized_config(self) -> None:
        target = self.root / "target"
        result = self.run_bootstrap(target, self.config())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((target / ".collaboration.yaml").is_file())
        self.assertTrue((target / "governance" / "AGENTS.md").is_file())
        self.assertTrue((target / "governance" / "task-routes.md").is_file())
        self.assertTrue((target / "areas" / "alpha" / "AGENTS.md").is_file())
        validated = subprocess.run([sys.executable, str(SCRIPTS / "validate_collaboration.py"), str(target)], capture_output=True, text=True)
        self.assertEqual(validated.returncode, 0, validated.stdout)

    def test_existing_target_dry_run_does_not_write(self) -> None:
        target = self.root / "existing"
        target.mkdir(); (target / "keep.txt").write_text("keep", encoding="utf-8")
        result = self.run_bootstrap(target, self.config(), "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((target / ".collaboration.yaml").exists())
        self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_enabled_features_generate_enforcement_lock_and_safe_hook_installer(self) -> None:
        target = self.root / "target"
        source = self.config(features={"ai_records": {"enabled": True}, "work_session_lock": {"enabled": True}, "git_hooks": {"enabled": True}})
        result = self.run_bootstrap(target, source)
        self.assertEqual(result.returncode, 0, result.stderr)
        subprocess.run(["git", "init", "-q", str(target)], check=True)
        (target / "areas" / "alpha" / "work.md").write_text("work", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=target, check=True)
        check = subprocess.run([sys.executable, "scripts/check_change_scope.py", "--staged"], cwd=target, capture_output=True, text=True)
        self.assertNotEqual(check.returncode, 0)
        lock = [sys.executable, "scripts/work_session.py"]
        expiry = "2999-01-01T00:00:00+00:00"
        self.assertEqual(subprocess.run([*lock, "acquire", "--owner", "one", "--work-item", "item", "--paths", "areas/alpha", "--expires-at", expiry], cwd=target).returncode, 0)
        self.assertNotEqual(subprocess.run([*lock, "acquire", "--owner", "two", "--work-item", "other", "--paths", "areas/alpha/file", "--expires-at", expiry], cwd=target).returncode, 0)
        self.assertEqual(subprocess.run([*lock, "handoff", "--owner", "one", "--work-item", "item", "--to", "two"], cwd=target).returncode, 0)
        self.assertEqual(subprocess.run([*lock, "release", "--owner", "two", "--work-item", "item"], cwd=target).returncode, 0)
        subprocess.run(["git", "config", "--local", "core.hooksPath", "custom-hooks"], cwd=target, check=True)
        install = subprocess.run([sys.executable, "scripts/install_collaboration_hooks.py"], cwd=target, capture_output=True, text=True)
        self.assertNotEqual(install.returncode, 0)

    def test_hooks_are_usable_without_ai_records(self) -> None:
        target = self.root / "hooks-only"
        result = self.run_bootstrap(target, self.config(features={"git_hooks": {"enabled": True}}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((target / "scripts" / "check_change_scope.py").is_file())
        self.assertFalse((target / "areas" / "alpha" / "ai-records").exists())


if __name__ == "__main__":
    unittest.main()
