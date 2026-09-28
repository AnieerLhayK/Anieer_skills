from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "inventory_external_skills.py"
SPEC = importlib.util.spec_from_file_location("inventory_external_skills", SCRIPT)
assert SPEC and SPEC.loader
inventory_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory_module)


class InventoryExternalSkillsTests(unittest.TestCase):
    def git(self, root: Path, *arguments: str) -> str:
        result = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout.strip()

    def initialize(self, root: Path) -> None:
        self.git(root, "init")
        self.git(root, "config", "user.email", "test@example.com")
        self.git(root, "config", "user.name", "Test")
        self.git(root, "remote", "add", "origin", "https://example.com/skills.git")

    def skill(self, root: Path, relative: str, name: str = "demo") -> Path:
        directory = root / relative
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "SKILL.md"
        path.write_text(
            f"---\nname: {name}\ndescription: Demo external skill.\n---\n\nRun it.\n",
            encoding="utf-8",
        )
        return path

    def commit(self, root: Path) -> str:
        self.git(root, "add", ".")
        self.git(root, "commit", "-m", "fixture")
        revision = self.git(root, "rev-parse", "HEAD")
        branch = self.git(root, "branch", "--show-current")
        self.git(root, "update-ref", f"refs/remotes/origin/{branch}", revision)
        self.git(root, "branch", "--set-upstream-to", f"origin/{branch}")
        return revision

    def complete_repo(self, root: Path) -> str:
        self.initialize(root)
        (root / "LICENSE").write_text("MIT fixture\n", encoding="utf-8")
        self.skill(root, "engineering/demo")
        guide = root / "engineering" / "demo" / "references" / "guide.md"
        guide.parent.mkdir(parents=True)
        guide.write_text("guide\n", encoding="utf-8")
        return self.commit(root)

    def test_clean_checkout_reports_revision_license_candidate_and_resources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            revision = self.complete_repo(root)
            before = {
                path.relative_to(root).as_posix(): (path.stat().st_mtime_ns, path.read_bytes())
                for path in root.rglob("*")
                if path.is_file() and ".git" not in path.parts
            }
            payload = inventory_module.inventory(root)
            after = {
                path.relative_to(root).as_posix(): (path.stat().st_mtime_ns, path.read_bytes())
                for path in root.rglob("*")
                if path.is_file() and ".git" not in path.parts
            }
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["git"]["revision"], revision)
        self.assertEqual(payload["git"]["remote"], "https://example.com/skills.git")
        self.assertEqual(payload["git"]["ahead"], 0)
        self.assertEqual(payload["git"]["behind"], 0)
        self.assertEqual(payload["licenses"][0]["path"], "LICENSE")
        self.assertEqual(payload["candidates"][0]["name"], "demo")
        self.assertEqual(payload["candidates"][0]["frontmatter"]["name"], "demo")
        self.assertIn("references/guide.md", payload["candidates"][0]["resources"])
        self.assertEqual(after, before)

    def test_dirty_checkout_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.complete_repo(root)
            (root / "untracked.txt").write_text("dirty\n", encoding="utf-8")
            payload = inventory_module.inventory(root)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertIn("Git checkout is dirty", payload["errors"])

    def test_ahead_and_behind_tracking_states_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = self.complete_repo(root)
            (root / "ahead.txt").write_text("ahead\n", encoding="utf-8")
            self.git(root, "add", "ahead.txt")
            self.git(root, "commit", "-m", "ahead")
            ahead_payload = inventory_module.inventory(root)
            ahead_revision = self.git(root, "rev-parse", "HEAD")
            branch = self.git(root, "branch", "--show-current")
            self.git(root, "reset", "--hard", base)
            self.git(root, "update-ref", f"refs/remotes/origin/{branch}", ahead_revision)
            behind_payload = inventory_module.inventory(root)
        self.assertEqual(ahead_payload["git"]["ahead"], 1)
        self.assertEqual(ahead_payload["git"]["behind"], 0)
        self.assertEqual(behind_payload["git"]["ahead"], 0)
        self.assertEqual(behind_payload["git"]["behind"], 1)
        self.assertTrue(
            any("differs from tracking upstream" in item for item in ahead_payload["errors"])
        )
        self.assertTrue(
            any("differs from tracking upstream" in item for item in behind_payload["errors"])
        )

    def test_non_git_directory_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = inventory_module.inventory(directory)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertTrue(any("not a Git checkout" in item for item in payload["errors"]))

    def test_missing_license_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.initialize(root)
            self.skill(root, "demo")
            self.commit(root)
            payload = inventory_module.inventory(root)
        self.assertIn("no root license or notice file found", payload["errors"])

    def test_duplicate_names_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.initialize(root)
            (root / "LICENSE").write_text("MIT fixture\n", encoding="utf-8")
            self.skill(root, "one", name="duplicate")
            self.skill(root, "two", name="duplicate")
            self.commit(root)
            payload = inventory_module.inventory(root)
        self.assertTrue(any("duplicate skill name" in item for item in payload["errors"]))

    def test_nested_candidate_is_not_a_parent_candidate_resource(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.initialize(root)
            (root / "LICENSE").write_text("MIT fixture\n", encoding="utf-8")
            self.skill(root, "parent", name="parent")
            self.skill(root, "parent/children/child", name="child")
            child_resource = root / "parent" / "children" / "child" / "guide.md"
            child_resource.write_text("child\n", encoding="utf-8")
            self.commit(root)
            payload = inventory_module.inventory(root)
        by_name = {candidate["name"]: candidate for candidate in payload["candidates"]}
        self.assertNotIn(
            "children/child/SKILL.md", by_name["parent"]["resources"]
        )
        self.assertNotIn("children/child/guide.md", by_name["parent"]["resources"])
        self.assertIn("guide.md", by_name["child"]["resources"])

    def test_invalid_frontmatter_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.initialize(root)
            (root / "LICENSE").write_text("MIT fixture\n", encoding="utf-8")
            skill = root / "broken" / "SKILL.md"
            skill.parent.mkdir()
            skill.write_text("---\nname: [broken\n---\n", encoding="utf-8")
            self.commit(root)
            payload = inventory_module.inventory(root)
        self.assertFalse(payload["candidates"][0]["frontmatter_valid"])
        self.assertTrue(any("invalid YAML" in item for item in payload["errors"]))

    def test_checkout_without_candidates_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.initialize(root)
            (root / "LICENSE").write_text("MIT fixture\n", encoding="utf-8")
            self.commit(root)
            payload = inventory_module.inventory(root)
        self.assertIn("no SKILL.md candidates found", payload["errors"])

    def test_symlink_escape_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            self.complete_repo(root)
            outside_file = Path(outside) / "secret.txt"
            outside_file.write_text("secret\n", encoding="utf-8")
            link = root / "escape.txt"
            try:
                os.symlink(outside_file, link)
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            payload = inventory_module.inventory(root)
        self.assertTrue(any("symlink escapes source root" in item for item in payload["errors"]))


if __name__ == "__main__":
    unittest.main()
