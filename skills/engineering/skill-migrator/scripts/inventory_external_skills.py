#!/usr/bin/env python3
"""Read-only inventory for an external Git skill checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

import yaml


FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
SKILL_NAME = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
LICENSE_NAME = re.compile(r"^(?:license|copying|notice)(?:[._-].*)?$", re.IGNORECASE)
IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


def git(source: Path, *arguments: str) -> tuple[int, str, str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=source,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def walk_files(
    root: Path,
    *,
    max_depth: int,
    errors: list[str],
    warnings: list[str],
) -> Iterator[Path]:
    for current_text, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(current_text)
        depth = len(current.relative_to(root).parts)
        if depth >= max_depth:
            if directory_names:
                warnings.append(
                    f"maximum discovery depth reached at {current.relative_to(root).as_posix()}"
                )
            directory_names[:] = []

        retained: list[str] = []
        for name in directory_names:
            candidate = current / name
            if name in IGNORED_DIRECTORIES:
                continue
            if candidate.is_symlink():
                relative = candidate.relative_to(root).as_posix()
                if within(candidate, root):
                    warnings.append(f"symlinked directory skipped: {relative}")
                else:
                    errors.append(f"symlink escapes source root: {relative}")
                continue
            retained.append(name)
        directory_names[:] = retained

        for name in file_names:
            candidate = current / name
            if candidate.is_symlink():
                relative = candidate.relative_to(root).as_posix()
                if within(candidate, root):
                    warnings.append(f"symlinked file skipped: {relative}")
                else:
                    errors.append(f"symlink escapes source root: {relative}")
                continue
            if candidate.is_file():
                yield candidate


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_skill(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        return None, f"cannot read UTF-8 frontmatter: {exc}"
    match = FRONTMATTER.match(content)
    if not match:
        return None, "SKILL.md must start with YAML frontmatter"
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        return None, f"invalid YAML frontmatter: {exc}"
    if not isinstance(metadata, dict):
        return None, "frontmatter must be a mapping"
    name = metadata.get("name")
    description = metadata.get("description")
    if (
        not isinstance(name, str)
        or not SKILL_NAME.fullmatch(name)
        or "--" in name
    ):
        return None, "frontmatter name must be a lowercase hyphenated skill id"
    if not isinstance(description, str) or not description.strip():
        return None, "frontmatter description must be a non-empty string"
    normalized = json.loads(json.dumps(metadata, ensure_ascii=False, default=str))
    return normalized, None


def inventory(source_value: str | Path, *, max_depth: int = 8) -> dict[str, Any]:
    requested_source = Path(source_value).expanduser().absolute()
    source = requested_source.resolve()
    errors: list[str] = []
    warnings: list[str] = []
    payload: dict[str, Any] = {
        "status": "BLOCKED",
        "source_root": str(source),
        "git": {},
        "licenses": [],
        "candidates": [],
        "errors": errors,
        "warnings": warnings,
    }
    if max_depth < 1:
        errors.append("max_depth must be at least 1")
        return payload
    if not source.is_dir():
        errors.append("source must be an existing directory")
        return payload
    if requested_source.is_symlink():
        errors.append("source root must not be a symlink")
        return payload

    code, git_root_text, detail = git(source, "rev-parse", "--show-toplevel")
    if code:
        errors.append(f"source is not a Git checkout: {detail or git_root_text}")
        return payload
    git_root = Path(git_root_text).resolve()
    if os.path.normcase(str(git_root)) != os.path.normcase(str(source)):
        errors.append("source must be the root of its Git checkout")
        return payload

    code, revision, detail = git(source, "rev-parse", "HEAD")
    if code or not re.fullmatch(r"[0-9a-fA-F]{40}", revision):
        errors.append(f"Git revision is unavailable: {detail or revision}")
    code, branch, _ = git(source, "branch", "--show-current")
    if code:
        branch = ""
    code, remote, _ = git(source, "config", "--get", "remote.origin.url")
    if code or not remote:
        errors.append("origin remote is missing")
    code, dirty_text, detail = git(
        source, "status", "--porcelain=v1", "--untracked-files=all"
    )
    if code:
        errors.append(f"Git status is unavailable: {detail}")
        dirty = True
    else:
        dirty = bool(dirty_text)
        if dirty:
            errors.append("Git checkout is dirty")
    tracking_upstream: str | None = None
    ahead: int | None = None
    behind: int | None = None
    if branch:
        code, upstream_text, _ = git(
            source,
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            "@{upstream}",
        )
        if code or not upstream_text:
            errors.append("branch checkout has no tracking upstream")
        else:
            tracking_upstream = upstream_text
            code, counts, detail = git(
                source, "rev-list", "--left-right", "--count", "HEAD...@{upstream}"
            )
            try:
                ahead, behind = (int(value) for value in counts.split())
            except (TypeError, ValueError):
                errors.append(f"tracking comparison is unavailable: {detail or counts}")
            else:
                if code:
                    errors.append(f"tracking comparison is unavailable: {detail or counts}")
                elif ahead or behind:
                    errors.append(
                        f"checkout differs from tracking upstream: ahead {ahead}, behind {behind}"
                    )
    else:
        warnings.append("detached HEAD has no tracking comparison")
    payload["git"] = {
        "remote": remote,
        "revision": revision,
        "branch": branch or "(detached)",
        "dirty": dirty,
        "tracking_upstream": tracking_upstream,
        "ahead": ahead,
        "behind": behind,
    }

    root_files = [
        item for item in source.iterdir() if item.is_file() and not item.is_symlink()
    ]
    licenses = []
    for path in sorted(root_files, key=lambda item: item.name.casefold()):
        if LICENSE_NAME.fullmatch(path.name):
            licenses.append(
                {
                    "path": path.relative_to(source).as_posix(),
                    "sha256": sha256(path),
                    "bytes": path.stat().st_size,
                }
            )
    payload["licenses"] = licenses
    if not licenses:
        errors.append("no root license or notice file found")

    files = list(
        walk_files(
            source,
            max_depth=max_depth,
            errors=errors,
            warnings=warnings,
        )
    )
    skill_files = sorted(
        (path for path in files if path.name == "SKILL.md"),
        key=lambda item: item.as_posix().casefold(),
    )
    names: dict[str, list[str]] = {}
    candidates: list[dict[str, Any]] = []
    skill_directories = {path.parent for path in skill_files}
    for skill_file in skill_files:
        skill_dir = skill_file.parent
        frontmatter, frontmatter_error = parse_skill(skill_file)
        name = frontmatter.get("name") if frontmatter else None
        description = frontmatter.get("description") if frontmatter else None
        relative_dir = skill_dir.relative_to(source).as_posix()
        nested_skill_directories = {
            directory
            for directory in skill_directories
            if directory != skill_dir and skill_dir in directory.parents
        }
        resources = sorted(
            path.relative_to(skill_dir).as_posix()
            for path in files
            if path != skill_file and skill_dir in path.parents
            and not any(
                path == nested / "SKILL.md" or nested in path.parents
                for nested in nested_skill_directories
            )
        )
        candidate = {
            "path": relative_dir,
            "skill_file": skill_file.relative_to(source).as_posix(),
            "name": name,
            "description": description,
            "frontmatter": frontmatter,
            "resources": resources,
            "frontmatter_valid": frontmatter_error is None,
            "frontmatter_error": frontmatter_error,
        }
        candidates.append(candidate)
        if frontmatter_error:
            errors.append(f"{candidate['skill_file']}: {frontmatter_error}")
        if name:
            names.setdefault(name, []).append(relative_dir)
    payload["candidates"] = candidates
    if not candidates:
        errors.append("no SKILL.md candidates found")
    for name, paths in sorted(names.items()):
        if len(paths) > 1:
            errors.append(f"duplicate skill name '{name}': {', '.join(paths)}")

    payload["errors"] = list(dict.fromkeys(errors))
    payload["warnings"] = list(dict.fromkeys(warnings))
    payload["status"] = "PASS" if not payload["errors"] else "BLOCKED"
    return payload


def render_text(payload: dict[str, Any]) -> str:
    lines = [
        f"Status: {payload['status']}",
        f"Source: {payload['source_root']}",
        f"Revision: {payload.get('git', {}).get('revision', '')}",
        f"Candidates: {len(payload.get('candidates', []))}",
        f"Licenses: {len(payload.get('licenses', []))}",
    ]
    lines.extend(f"ERROR: {item}" for item in payload.get("errors", []))
    lines.extend(f"WARNING: {item}" for item in payload.get("warnings", []))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inventory an exact external Git checkout without modifying it."
    )
    parser.add_argument("--source", required=True)
    parser.add_argument("--format", choices=("json", "text"), default="text")
    parser.add_argument("--max-depth", type=int, default=8)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        payload = inventory(args.source, max_depth=args.max_depth)
    except (OSError, ValueError) as exc:
        payload = {
            "status": "ERROR",
            "source_root": str(Path(args.source).expanduser()),
            "git": {},
            "licenses": [],
            "candidates": [],
            "errors": [str(exc)],
            "warnings": [],
        }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(payload))
    if payload["status"] == "PASS":
        return 0
    return 2 if payload["status"] == "BLOCKED" else 1


if __name__ == "__main__":
    sys.exit(main())
