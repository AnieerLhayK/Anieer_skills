from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "build_portable_package.py"
SPEC = importlib.util.spec_from_file_location("showcase_builder", MODULE_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class ShowcaseBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.output = self.root / "output"
        self.source.mkdir()
        (self.source / "notes.md").write_text("Evidence summary.", encoding="utf-8")
        (self.source / "raw").mkdir()
        (self.source / "raw" / "measurements.csv").write_text("x,y\n1,2\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def complete_content(self) -> Path:
        content = self.root / "content"
        for index, relative in enumerate(builder.CONTENT_FILES, start=1):
            path = content / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"# Reviewed section {index}\n\nThis is complete, source-backed package content for section {index}.\n",
                encoding="utf-8",
            )
        return content

    def test_preview_is_read_only_and_excludes_raw_material(self) -> None:
        before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        details = builder.preview(self.source.resolve(), [], set())
        after = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
        self.assertEqual(before, after)
        self.assertEqual([item["source_relative_path"] for item in details["accepted"]], ["notes.md"])
        self.assertEqual(details["excluded"][0]["risks"], ["raw-sensitive-material"])

    def test_build_requires_explicit_confirmation(self) -> None:
        details = builder.preview(self.source.resolve(), [], set())
        with self.assertRaises(builder.PackageError):
            builder.build(self.source.resolve(), self.output.resolve(), "review-pack", details, confirmed=False)
        self.assertFalse(self.output.exists())

    def test_approved_exception_builds_manifest_without_source_mutation(self) -> None:
        source_hash = hashlib.sha256((self.source / "raw" / "measurements.csv").read_bytes()).hexdigest()
        details = builder.preview(self.source.resolve(), [], {"raw/measurements.csv"})
        destination = builder.build(self.source.resolve(), self.output.resolve(), "review-pack", details, confirmed=True)
        self.assertEqual(source_hash, hashlib.sha256((self.source / "raw" / "measurements.csv").read_bytes()).hexdigest())
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["approved_exceptions"], ["raw/measurements.csv"])
        self.assertTrue((destination / "materials" / "raw" / "measurements.csv").is_file())
        self.assertTrue(all(not Path(item["source_relative_path"]).is_absolute() for item in manifest["files"]))

    def test_rejects_unsafe_package_name_and_overwrite(self) -> None:
        with self.assertRaises(builder.PackageError):
            builder.validate_roots(self.source, self.output, "../escape")
        details = builder.preview(self.source.resolve(), [], set())
        builder.build(self.source.resolve(), self.output.resolve(), "review-pack", details, confirmed=True)
        with self.assertRaises(builder.PackageError):
            builder.build(self.source.resolve(), self.output.resolve(), "review-pack", details, confirmed=True)

    def test_detects_personal_data_and_absolute_paths(self) -> None:
        (self.source / "contacts.md").write_text("mail person@example.com at C:\\Users\\name", encoding="utf-8")
        details = builder.preview(self.source.resolve(), ["contacts.md"], set())
        self.assertEqual(details["accepted"], [])
        self.assertEqual(set(details["excluded"][0]["risks"]), {"personal-data", "absolute-local-path"})

    def test_hashed_plan_builds_complete_manifest_and_verifies(self) -> None:
        plan = builder.create_plan(
            self.source,
            self.complete_content(),
            self.output,
            "review-pack",
            ["notes.md"],
            set(),
        )
        plan_path = self.root / "plan.json"
        builder.write_json_atomic(plan_path, plan)
        destination = builder.build_from_plan(plan_path, plan["plan_sha256"])
        manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
        managed = {item["package_relative_path"] for item in manifest["managed_files"]}
        self.assertEqual(manifest["plan_sha256"], plan["plan_sha256"])
        self.assertTrue(set(builder.CONTENT_FILES).issubset(managed))
        self.assertIn("materials/notes.md", managed)
        self.assertEqual(builder.verify_package(destination)["status"], "PASS")

    def test_build_rejects_wrong_approval_and_input_drift(self) -> None:
        plan = builder.create_plan(
            self.source,
            self.complete_content(),
            self.output,
            "review-pack",
            ["notes.md"],
            set(),
        )
        plan_path = self.root / "plan.json"
        builder.write_json_atomic(plan_path, plan)
        with self.assertRaises(builder.PackageError):
            builder.build_from_plan(plan_path, "0" * 64)
        (self.source / "notes.md").write_text("Changed after approval.", encoding="utf-8")
        with self.assertRaises(builder.PackageError):
            builder.build_from_plan(plan_path, plan["plan_sha256"])
        self.assertFalse((self.output / "review-pack").exists())

    def test_plan_rejects_placeholder_content(self) -> None:
        content = self.complete_content()
        (content / "README.md").write_text(
            "Describe the goal, audience, scope, and navigation.", encoding="utf-8"
        )
        with self.assertRaises(builder.PackageError):
            builder.create_plan(self.source, content, self.output, "review-pack", [], set())

    def test_plan_rejects_absolute_paths_in_content_and_output_inside_source(self) -> None:
        content = self.complete_content()
        (content / "README.md").write_text(
            "# Reviewed\n\nEvidence was read from C:\\Users\\name\\private.txt.\n",
            encoding="utf-8",
        )
        with self.assertRaises(builder.PackageError):
            builder.create_plan(self.source, content, self.output, "review-pack", [], set())
        with self.assertRaises(builder.PackageError):
            builder.validate_roots(self.source, self.source / "exports", "review-pack")

    def test_verify_detects_unexpected_and_modified_files(self) -> None:
        plan = builder.create_plan(
            self.source,
            self.complete_content(),
            self.output,
            "review-pack",
            ["notes.md"],
            set(),
        )
        plan_path = self.root / "plan.json"
        builder.write_json_atomic(plan_path, plan)
        destination = builder.build_from_plan(plan_path, plan["plan_sha256"])
        (destination / "unexpected.txt").write_text("surprise", encoding="utf-8")
        (destination / "README.md").write_text("tampered", encoding="utf-8")
        verification = builder.verify_package(destination)
        self.assertEqual(verification["status"], "ERROR")
        self.assertTrue(any("unexpected file" in item for item in verification["problems"]))
        self.assertTrue(any("hash or size mismatch" in item for item in verification["problems"]))

    def test_verify_rejects_manifest_that_omits_required_content(self) -> None:
        package = self.root / "incomplete-package"
        package.mkdir()
        (package / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": builder.WORKFLOW_SCHEMA_VERSION,
                    "package_name": "incomplete-package",
                    "plan_sha256": "0" * 64,
                    "managed_files": [],
                }
            ),
            encoding="utf-8",
        )
        verification = builder.verify_package(package)
        self.assertEqual(verification["status"], "ERROR")
        self.assertTrue(
            any("required content is not managed" in item for item in verification["problems"])
        )

    def test_risk_exception_is_bound_into_plan_hash(self) -> None:
        plan = builder.create_plan(
            self.source,
            self.complete_content(),
            self.output,
            "review-pack",
            ["raw/measurements.csv"],
            {"raw/measurements.csv"},
        )
        self.assertEqual(plan["materials"]["approved_exceptions"], ["raw/measurements.csv"])
        altered = dict(plan)
        altered["allowed_risks"] = []
        with self.assertRaises(builder.PackageError):
            builder.validate_plan(altered, plan["plan_sha256"])

    def test_copy_time_drift_rejects_content_and_material_without_publishing(self) -> None:
        content = self.complete_content()
        for changed in (content / "README.md", self.source / "notes.md"):
            with self.subTest(changed=changed):
                plan = builder.create_plan(self.source, content, self.output, "review-pack", ["notes.md"], set())
                plan_path = self.root / "plan.json"
                builder.write_json_atomic(plan_path, plan)
                original_copy = builder.shutil.copy2

                def racing_copy(source, target):
                    if Path(source) == changed:
                        changed.write_text("Changed between validation and copy.", encoding="utf-8")
                    return original_copy(source, target)

                with patch.object(builder.shutil, "copy2", side_effect=racing_copy):
                    with self.assertRaisesRegex(builder.PackageError, "changed during copy"):
                        builder.build_from_plan(plan_path, plan["plan_sha256"])
                self.assertEqual(list(self.output.iterdir()), [])

    def test_verify_rejects_missing_or_invalid_plan_digest_and_record_types(self) -> None:
        plan = builder.create_plan(self.source, self.complete_content(), self.output, "review-pack", ["notes.md"], set())
        plan_path = self.root / "plan.json"
        builder.write_json_atomic(plan_path, plan)
        destination = builder.build_from_plan(plan_path, plan["plan_sha256"])
        path = destination / "manifest.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        for value in (None, "", "not-a-digest", 123):
            manifest = dict(original)
            if value is None:
                manifest.pop("plan_sha256")
            else:
                manifest["plan_sha256"] = value
            path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(builder.verify_package(destination)["status"], "ERROR")
        original["managed_files"].append(None)
        path.write_text(json.dumps(original), encoding="utf-8")
        self.assertEqual(builder.verify_package(destination)["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
