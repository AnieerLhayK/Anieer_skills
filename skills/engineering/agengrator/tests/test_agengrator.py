from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "agengrator.py"
SPEC = importlib.util.spec_from_file_location("agengrator_module", MODULE_PATH)
assert SPEC and SPEC.loader
agengrator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agengrator)


class AgengratorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.payload = self.root / "payload"
        self.output = self.root / "bundle"
        self.selection_path = self.root / "selection.json"
        self.plan_path = self.root / "plan.json"
        self._write_minimal_payload()
        self._write_selection()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, relative: str, content: str) -> None:
        path = self.payload / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _write_minimal_payload(self) -> None:
        self._write(
            "START_HERE.md",
            "# Receiver\n\nWait for the user's explicit approval. Remain read-only until approval.\n",
        )
        self._write("SECURITY_BOUNDARY.md", "# Security\n\nPortable text only.\n")
        self._write("plugins/RECOMMENDATIONS.md", "# Plugins\n\nReview before connecting.\n")
        self._write("workspace-template/AGENTS.md", "# Rules\n\nPlan, approve, validate.\n")
        self._write("skills/research/SKILL.md", "---\nname: research\ndescription: Verify facts.\n---\n")

    def _write_selection(self, *, license_value: str = "MIT") -> None:
        value = {
            "schema_version": "1.0",
            "bundle_id": "migra-codex",
            "payload_root": str(self.payload.resolve()),
            "selections": [
                {
                    "id": "research",
                    "kind": "skill",
                    "export_mode": "exact",
                    "source_id": "workspace:research",
                    "license": license_value,
                    "attribution": "Required notice retained",
                }
            ],
        }
        self.selection_path.write_text(json.dumps(value), encoding="utf-8")

    def _plan(self) -> dict:
        plan = agengrator.build_plan(self.selection_path, self.output)
        self.plan_path.write_text(json.dumps(plan), encoding="utf-8")
        return plan

    def _apply(self, plan: dict, *, approve_deletions: bool = False) -> dict:
        return agengrator.apply_plan(
            self.plan_path,
            plan["plan_sha256"],
            plan["deletions_sha256"] if approve_deletions else None,
        )

    def test_plan_is_read_only_for_output_root(self) -> None:
        plan = self._plan()
        self.assertFalse(self.output.exists())
        self.assertIn("START_HERE.md", plan["actions"]["create"])
        self.assertIsNone(plan["deletions_sha256"])

    def test_plan_can_build_virtual_payload_without_staging_writes(self) -> None:
        assets = self.root / "assets"
        skill = self.root / "source-skill"
        assets.mkdir()
        skill.mkdir()
        (assets / "START_HERE.md").write_text(
            "Wait for the user's explicit approval. Remain read-only until approval.\n",
            encoding="utf-8",
        )
        (assets / "SECURITY_BOUNDARY.md").write_text("Portable text.\n", encoding="utf-8")
        (assets / "plugins").mkdir()
        (assets / "plugins/RECOMMENDATIONS.md").write_text("Review.\n", encoding="utf-8")
        (assets / "workspace-template").mkdir()
        (assets / "workspace-template/AGENTS.md").write_text("Approve writes.\n", encoding="utf-8")
        (skill / "SKILL.md").write_text("Use C:\\private\\staging.\n", encoding="utf-8")
        virtual_selection = {
            "schema_version": "1.0",
            "bundle_id": "migra-codex",
            "payload_sources": [
                {"source_root": str(assets), "target_root": ""},
                {"source_root": str(skill), "target_root": "skills/research"},
            ],
            "text_replacements": {
                "skills/research/SKILL.md": [
                    {"old": "C:\\private\\staging", "new": "a receiver-configured staging directory"}
                ]
            },
            "selections": [
                {
                    "id": "research",
                    "kind": "skill",
                    "export_mode": "adapted",
                    "source_id": "workspace:research",
                    "license": "MIT",
                    "attribution": "Required notice retained",
                }
            ],
        }
        self.selection_path.write_text(json.dumps(virtual_selection), encoding="utf-8")
        plan = self._plan()
        self.assertFalse(self.output.exists())
        self.assertEqual(
            agengrator._planned_file_bytes(plan["files"]["skills/research/SKILL.md"]).decode("utf-8").strip(),
            "Use a receiver-configured staging directory.",
        )

    def test_apply_requires_exact_plan_hash(self) -> None:
        self._plan()
        with self.assertRaisesRegex(agengrator.AgengratorError, "approved plan SHA-256"):
            agengrator.apply_plan(self.plan_path, "0" * 64)
        self.assertFalse(self.output.exists())

    def test_apply_then_validate_preserves_unknown_files(self) -> None:
        first = self._plan()
        self._apply(first)
        unknown = self.output / "personal-note.md"
        unknown.write_text("receiver-owned\n", encoding="utf-8")
        self._write("skills/research/SKILL.md", "---\nname: research\ndescription: Verify primary facts.\n---\n")
        second = self._plan()
        self._apply(second)
        self.assertEqual(unknown.read_text(encoding="utf-8"), "receiver-owned\n")
        self.assertEqual(agengrator.validate_bundle(self.output)["status"], "PASS")

    def test_unknown_collision_blocks_plan(self) -> None:
        (self.output / "skills/research").mkdir(parents=True)
        (self.output / "skills/research/SKILL.md").write_text("unknown\n", encoding="utf-8")
        with self.assertRaisesRegex(agengrator.AgengratorError, "unknown items"):
            self._plan()

    def test_managed_drift_blocks_plan(self) -> None:
        first = self._plan()
        self._apply(first)
        (self.output / "skills/research/SKILL.md").write_text("manual edit\n", encoding="utf-8")
        with self.assertRaisesRegex(agengrator.AgengratorError, "drifted"):
            self._plan()

    def test_deletion_needs_separate_approval_hash(self) -> None:
        self._write("skills/obsolete/SKILL.md", "---\nname: obsolete\ndescription: Old.\n---\n")
        first = self._plan()
        self._apply(first)
        (self.payload / "skills/obsolete/SKILL.md").unlink()
        (self.payload / "skills/obsolete").rmdir()
        second = self._plan()
        self.assertIn("skills/obsolete/SKILL.md", second["actions"]["delete"])
        with self.assertRaisesRegex(agengrator.AgengratorError, "separately approved"):
            self._apply(second)
        self._apply(second, approve_deletions=True)
        self.assertFalse((self.output / "skills/obsolete/SKILL.md").exists())

    def test_sensitive_value_and_absolute_path_are_fail_closed(self) -> None:
        self._write("skills/research/secret.txt", "token=abcdefghijklmnopqrstuvwxyz\n")
        with self.assertRaisesRegex(agengrator.AgengratorError, "assigned secret"):
            self._plan()
        (self.payload / "skills/research/secret.txt").write_text("source at C:\\private\\file\n", encoding="utf-8")
        with self.assertRaisesRegex(agengrator.AgengratorError, "Windows drive path"):
            self._plan()

    def test_non_text_file_and_missing_license_are_fail_closed(self) -> None:
        binary = self.payload / "skills/research/logo.png"
        binary.write_bytes(b"\x89PNG\r\n")
        with self.assertRaisesRegex(agengrator.AgengratorError, "unsupported non-text"):
            self._plan()
        binary.unlink()
        self._write_selection(license_value="")
        with self.assertRaisesRegex(agengrator.AgengratorError, "license must be non-empty"):
            self._plan()

    def test_validate_rejects_broken_relative_markdown_link(self) -> None:
        first = self._plan()
        self._apply(first)
        self._write("START_HERE.md", "Wait for the user's explicit approval. Remain read-only. [Missing](missing.md)\n")
        second = self._plan()
        with self.assertRaisesRegex(agengrator.AgengratorError, "broken relative Markdown link"):
            self._apply(second)

    def test_apply_rolls_back_after_mid_write_failure(self) -> None:
        first = self._plan()
        self._apply(first)
        before_manifest = (self.output / agengrator.MANIFEST_NAME).read_bytes()
        before_skill = (self.output / "skills/research/SKILL.md").read_bytes()
        self._write("skills/research/SKILL.md", "---\nname: research\ndescription: Changed.\n---\n")
        self._write("skills/new-skill/SKILL.md", "---\nname: new-skill\ndescription: New.\n---\n")
        second = self._plan()
        original = agengrator._atomic_write
        calls = {"count": 0}

        def fail_once(path: Path, data: bytes) -> None:
            calls["count"] += 1
            if calls["count"] == 2:
                raise OSError("injected write failure")
            original(path, data)

        with mock.patch.object(agengrator, "_atomic_write", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "injected write failure"):
                self._apply(second)
        self.assertEqual((self.output / agengrator.MANIFEST_NAME).read_bytes(), before_manifest)
        self.assertEqual((self.output / "skills/research/SKILL.md").read_bytes(), before_skill)
        self.assertFalse((self.output / "skills/new-skill/SKILL.md").exists())

    def test_inventory_is_bounded_and_excludes_character_package(self) -> None:
        workspace = self.root / "workspace"
        safe = workspace / "skills/safe"
        character = workspace / "packages/character-system/runtime/characters/demo"
        safe.mkdir(parents=True)
        character.mkdir(parents=True)
        (safe / "SKILL.md").write_text("---\nname: safe\ndescription: Safe.\n---\n", encoding="utf-8")
        (character / "SKILL.md").write_text("---\nname: demo\ndescription: Demo.\n---\n", encoding="utf-8")
        manifest = {
            "skills": [
                {"id": "safe", "source_path": "skills/safe"},
                {"id": "demo", "package_id": "character-system", "source_path": "packages/character-system/runtime/characters/demo"},
            ]
        }
        (workspace / "workspace_manifest.yaml").write_text(json.dumps(manifest), encoding="utf-8")
        result = agengrator.inventory_candidates(workspace, [])
        self.assertEqual([item["id"] for item in result["candidates"]], ["safe"])
        self.assertFalse(result["candidates"][0]["default_selected"])


if __name__ == "__main__":
    unittest.main()
