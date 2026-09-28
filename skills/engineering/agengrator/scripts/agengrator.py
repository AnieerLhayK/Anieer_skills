#!/usr/bin/env python3
"""Plan-gated synchronization for portable Codex handoff bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


SCHEMA_VERSION = "1.0"
MANIFEST_NAME = "agengrator-manifest.json"
GENERATOR_NAME = "agengrator"
DEFAULT_OUTPUT_ROOT = Path(r"${LOCAL_PATH}")
MAX_TEXT_BYTES = 2 * 1024 * 1024

TEXT_SUFFIXES = {
    ".cfg", ".css", ".csv", ".html", ".ini", ".js", ".json", ".jsx",
    ".md", ".ps1", ".py", ".rst", ".sh", ".toml", ".ts", ".tsx",
    ".tsv", ".txt", ".xml", ".yaml", ".yml",
}
TEXT_NAMES = {"LICENSE", "NOTICE", "COPYING", ".gitignore"}
FORBIDDEN_PARTS = {
    ".git", "__pycache__", "cache", "caches", "characters", "corpus",
    "credentials", "private", "reports", "secrets", "session", "sessions",
}
FORBIDDEN_PACKAGE_IDS = {"character-system"}
REQUIRED_PAYLOAD = {
    "START_HERE.md",
    "SECURITY_BOUNDARY.md",
    "plugins/RECOMMENDATIONS.md",
    "workspace-template/AGENTS.md",
}

SECRET_PATTERNS = (
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("OpenAI-style secret", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("Bearer token", re.compile(r"(?i)authorization\s*:\s*bearer\s+\S+")),
    ("assigned secret", re.compile(r"(?i)\b(?:password|passwd|api[_-]?key|secret|token)\s*[:=]\s*['\"]?[^\s'\"<{]{6,}")),
)
LOCAL_PATH_PATTERNS = (
    ("Windows drive path", re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/])")),
    ("UNC path", re.compile(r"(?:^|\s)\\\\[^\s\\]+\\[^\s\\]+")),
    ("Windows profile path", re.compile(r"(?i)%USERPROFILE%|\\Users\\[^\\\s]+")),
    ("Unix home path", re.compile(r"(?:^|[\s`'\"])/(?:home|Users)/[^/\s`'\"]+")),
    ("Unix system path", re.compile(r"(?:^|[\s`'\"])/(?:etc|var|opt)/[^\s`'\"]*")),
)
MARKDOWN_LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


class AgengratorError(RuntimeError):
    """A fail-closed validation or synchronization error."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgengratorError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AgengratorError(f"JSON root must be an object: {path}")
    return value


def _is_linklike(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise AgengratorError(f"cannot inspect path {path}: {exc}") from exc
    attrs = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _require_plain_directory(path: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_dir():
        raise AgengratorError(f"{label} is not a directory: {path}")
    cursor = path.absolute()
    while True:
        if cursor.exists() and _is_linklike(cursor):
            raise AgengratorError(f"{label} crosses a link or reparse point: {cursor}")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    return resolved


def _require_plain_file(path: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise AgengratorError(f"{label} is not a file: {path}")
    cursor = path.absolute()
    while True:
        if cursor.exists() and _is_linklike(cursor):
            raise AgengratorError(f"{label} crosses a link or reparse point: {cursor}")
        if cursor.parent == cursor:
            break
        cursor = cursor.parent
    return resolved


def normalize_relative(value: str) -> str:
    if "\\" in value:
        raise AgengratorError(f"relative path must use forward slashes: {value}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise AgengratorError(f"invalid relative path: {value}")
    normalized = pure.as_posix()
    if normalized == MANIFEST_NAME:
        raise AgengratorError(f"payload must not provide reserved file: {MANIFEST_NAME}")
    return normalized


def normalize_target_root(value: str) -> str:
    if value == "":
        return ""
    return normalize_relative(value)


def _is_forbidden_relative(path: Path) -> bool:
    return any(part.lower() in FORBIDDEN_PARTS for part in path.parts)


def _validate_metadata_text(label: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgengratorError(f"selection {label} must be non-empty text")
    text = value.strip()
    scan_text(text, f"selection {label}")
    return text


def scan_text(text: str, label: str) -> None:
    for name, pattern in SECRET_PATTERNS + LOCAL_PATH_PATTERNS:
        if pattern.search(text):
            raise AgengratorError(f"{label} contains blocked {name}")


def read_portable_text(path: Path, *, root: Path) -> tuple[bytes, str]:
    if _is_linklike(path):
        raise AgengratorError(f"payload contains a link or reparse point: {path}")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AgengratorError(f"payload path escapes its root: {path}") from exc
    if path.name not in TEXT_NAMES and path.suffix.lower() not in TEXT_SUFFIXES:
        raise AgengratorError(f"unsupported non-text file: {path}")
    data = path.read_bytes()
    if len(data) > MAX_TEXT_BYTES:
        raise AgengratorError(f"text file exceeds {MAX_TEXT_BYTES} bytes: {path}")
    if b"\x00" in data:
        raise AgengratorError(f"NUL byte found in text file: {path}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgengratorError(f"file is not UTF-8 text: {path}") from exc
    scan_text(text, str(path))
    return data, text


def _safe_candidate(path: Path, root: Path) -> bool:
    try:
        relative = path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        return False
    return not _is_forbidden_relative(relative) and not _is_linklike(path)


def inventory_candidates(workspace_root: Path, skill_roots: Iterable[Path]) -> dict[str, Any]:
    workspace = _require_plain_directory(workspace_root, "workspace root")
    candidates: list[dict[str, Any]] = []
    seen: set[Path] = set()
    manifest_path = workspace / "workspace_manifest.yaml"
    if manifest_path.is_file():
        manifest = load_json(manifest_path)
        for item in manifest.get("skills", []):
            if not isinstance(item, dict) or item.get("package_id") in FORBIDDEN_PACKAGE_IDS:
                continue
            skill_id = str(item.get("id", ""))
            source_value = str(item.get("source_path", ""))
            if not skill_id or not source_value:
                continue
            source = workspace / source_value
            if not source.is_dir() or not (source / "SKILL.md").is_file() or not _safe_candidate(source, workspace):
                continue
            resolved = source.resolve()
            seen.add(resolved)
            candidates.append({
                "id": skill_id,
                "kind": "skill",
                "source_path": str(resolved),
                "source_id": f"workspace:{skill_id}",
                "registered": True,
                "default_selected": False,
            })
    for root_value in skill_roots:
        root = _require_plain_directory(root_value, "skill root")
        possible = [root] if (root / "SKILL.md").is_file() else [item for item in root.iterdir() if item.is_dir()]
        for source in possible:
            if not (source / "SKILL.md").is_file() or not _safe_candidate(source, root):
                continue
            resolved = source.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append({
                "id": source.name,
                "kind": "skill",
                "source_path": str(resolved),
                "source_id": f"explicit:{source.name}",
                "registered": False,
                "default_selected": False,
            })
    candidates.sort(key=lambda item: (item["kind"], item["id"], item["source_path"]))
    return {"status": "PASS", "schema_version": SCHEMA_VERSION, "candidates": candidates}


def normalize_selection(selection: dict[str, Any]) -> dict[str, Any]:
    if selection.get("schema_version") != SCHEMA_VERSION:
        raise AgengratorError(f"selection schema_version must be {SCHEMA_VERSION}")
    bundle_id = selection.get("bundle_id")
    if not isinstance(bundle_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", bundle_id):
        raise AgengratorError("bundle_id must use lowercase letters, digits, and hyphens")
    payload_value = selection.get("payload_root")
    raw_sources = selection.get("payload_sources")
    raw_files = selection.get("payload_files", [])
    if payload_value is not None and raw_sources:
        raise AgengratorError("use payload_root or payload_sources, not both")
    if payload_value is None and raw_sources is None:
        raise AgengratorError("selection must provide payload_root or payload_sources")
    payload_root: Path | None = None
    sources: list[dict[str, str]] = []
    files: list[dict[str, str]] = []
    replacements: dict[str, list[dict[str, str]]] = {}
    if payload_value is not None:
        if not isinstance(payload_value, str) or not Path(payload_value).is_absolute():
            raise AgengratorError("payload_root must be an absolute path")
        payload_root = _require_plain_directory(Path(payload_value), "payload root")
        if raw_files:
            raise AgengratorError("payload_files requires payload_sources mode")
    else:
        if not isinstance(raw_sources, list) or not raw_sources:
            raise AgengratorError("payload_sources must be a non-empty list")
        if not isinstance(raw_files, list):
            raise AgengratorError("payload_files must be a list")
        for index, raw_source in enumerate(raw_sources):
            if not isinstance(raw_source, dict):
                raise AgengratorError("each payload source must be an object")
            source_value = raw_source.get("source_root")
            target_value = raw_source.get("target_root", "")
            if not isinstance(source_value, str) or not Path(source_value).is_absolute():
                raise AgengratorError(f"payload source {index} source_root must be an absolute path")
            if not isinstance(target_value, str):
                raise AgengratorError(f"payload source {index} target_root must be text")
            sources.append({
                "source_root": str(_require_plain_directory(Path(source_value), f"payload source {index}")),
                "target_root": normalize_target_root(target_value),
            })
        for index, raw_file in enumerate(raw_files):
            if not isinstance(raw_file, dict):
                raise AgengratorError("each payload file must be an object")
            source_value = raw_file.get("source_file")
            target_value = raw_file.get("target_path")
            if not isinstance(source_value, str) or not Path(source_value).is_absolute():
                raise AgengratorError(f"payload file {index} source_file must be an absolute path")
            if not isinstance(target_value, str):
                raise AgengratorError(f"payload file {index} target_path must be text")
            files.append({
                "source_file": str(_require_plain_file(Path(source_value), f"payload file {index}")),
                "target_path": normalize_relative(target_value),
            })
        raw_replacements = selection.get("text_replacements", {})
        if not isinstance(raw_replacements, dict):
            raise AgengratorError("text_replacements must be an object")
        for raw_path, raw_rules in raw_replacements.items():
            target_path = normalize_relative(str(raw_path))
            if not isinstance(raw_rules, list) or not raw_rules:
                raise AgengratorError(f"text replacements for {target_path} must be a non-empty list")
            rules: list[dict[str, str]] = []
            for raw_rule in raw_rules:
                if not isinstance(raw_rule, dict):
                    raise AgengratorError(f"replacement rule for {target_path} must be an object")
                old = raw_rule.get("old")
                new = raw_rule.get("new")
                if not isinstance(old, str) or not old or not isinstance(new, str):
                    raise AgengratorError(f"replacement rule for {target_path} needs non-empty old and text new")
                scan_text(new, f"replacement output for {target_path}")
                rules.append({"old": old, "new": new})
            replacements[target_path] = rules
    raw_items = selection.get("selections")
    if not isinstance(raw_items, list) or not raw_items:
        raise AgengratorError("selections must be a non-empty list")
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise AgengratorError("each selection must be an object")
        item_id = _validate_metadata_text("id", raw.get("id"))
        kind = _validate_metadata_text("kind", raw.get("kind"))
        mode = _validate_metadata_text("export_mode", raw.get("export_mode"))
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", item_id):
            raise AgengratorError(f"invalid selection id: {item_id}")
        if kind not in {"plugin", "rule", "skill", "workflow", "workspace-template"}:
            raise AgengratorError(f"unsupported selection kind: {kind}")
        if mode not in {"exact", "adapted"}:
            raise AgengratorError(f"unsupported export_mode: {mode}")
        key = (kind, item_id)
        if key in seen:
            raise AgengratorError(f"duplicate selection: {kind}/{item_id}")
        seen.add(key)
        items.append({
            "id": item_id,
            "kind": kind,
            "export_mode": mode,
            "source_id": _validate_metadata_text("source_id", raw.get("source_id")),
            "license": _validate_metadata_text("license", raw.get("license")),
            "attribution": _validate_metadata_text("attribution", raw.get("attribution")),
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle_id": bundle_id,
        "payload_root": str(payload_root) if payload_root else None,
        "payload_sources": sources,
        "payload_files": files,
        "text_replacements": replacements,
        "selections": sorted(items, key=lambda item: (item["kind"], item["id"])),
    }


def load_selection(path: Path) -> dict[str, Any]:
    return normalize_selection(load_json(path))


def collect_payload(payload_root: Path) -> dict[str, dict[str, Any]]:
    root = _require_plain_directory(payload_root, "payload root")
    files: dict[str, dict[str, Any]] = {}
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in list(directories):
            directory = current_path / name
            relative = directory.relative_to(root)
            if _is_linklike(directory) or _is_forbidden_relative(relative):
                raise AgengratorError(f"payload contains forbidden directory: {relative.as_posix()}")
        for name in filenames:
            path = current_path / name
            relative_path = path.relative_to(root)
            if _is_forbidden_relative(relative_path):
                raise AgengratorError(f"payload contains forbidden path: {relative_path.as_posix()}")
            relative = normalize_relative(relative_path.as_posix())
            data, _ = read_portable_text(path, root=root)
            files[relative] = {"source_path": str(path.resolve()), "sha256": sha256_bytes(data), "size": len(data)}
    missing = sorted(REQUIRED_PAYLOAD - set(files))
    if missing:
        raise AgengratorError(f"payload is missing required files: {', '.join(missing)}")
    start_text = (root / "START_HERE.md").read_text(encoding="utf-8")
    if "Wait for the user's explicit approval" not in start_text or "read-only" not in start_text:
        raise AgengratorError("START_HERE.md does not preserve the receiver review gate")
    return dict(sorted(files.items()))


def _transformed_bytes(source: Path, root: Path, rules: list[dict[str, str]]) -> bytes:
    if not rules:
        data, _ = read_portable_text(source, root=root)
        return data
    if _is_linklike(source):
        raise AgengratorError(f"payload contains a link or reparse point: {source}")
    resolved = source.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AgengratorError(f"payload path escapes its root: {source}") from exc
    if source.name not in TEXT_NAMES and source.suffix.lower() not in TEXT_SUFFIXES:
        raise AgengratorError(f"unsupported non-text file: {source}")
    data = source.read_bytes()
    if len(data) > MAX_TEXT_BYTES or b"\x00" in data:
        raise AgengratorError(f"adaptation source is not supported UTF-8 text: {source}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AgengratorError(f"file is not UTF-8 text: {source}") from exc
    for rule in rules:
        count = text.count(rule["old"])
        if count != 1:
            raise AgengratorError(
                f"replacement for {source} expected one exact match but found {count}"
            )
        text = text.replace(rule["old"], rule["new"], 1)
    scan_text(text, str(source))
    return text.encode("utf-8")


def collect_selection_payload(selection: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if selection["payload_root"]:
        return collect_payload(Path(selection["payload_root"]))
    files: dict[str, dict[str, Any]] = {}
    replacements = selection["text_replacements"]

    def add_file(source: Path, root: Path, relative: str) -> None:
        if relative in files:
            raise AgengratorError(f"multiple payload sources target the same path: {relative}")
        rules = replacements.get(relative, [])
        data = _transformed_bytes(source, root, rules)
        files[relative] = {
            "source_path": str(source.resolve()),
            "source_root": str(root.resolve()),
            "text_replacements": rules,
            "sha256": sha256_bytes(data),
            "size": len(data),
        }

    for source_spec in selection["payload_sources"]:
        root = Path(source_spec["source_root"])
        target_root = source_spec["target_root"]
        for current, directories, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            for name in list(directories):
                directory = current_path / name
                source_relative = directory.relative_to(root)
                if _is_linklike(directory) or _is_forbidden_relative(source_relative):
                    raise AgengratorError(f"payload source contains forbidden directory: {source_relative.as_posix()}")
            for name in filenames:
                source = current_path / name
                source_relative = source.relative_to(root)
                if _is_forbidden_relative(source_relative):
                    raise AgengratorError(f"payload source contains forbidden path: {source_relative.as_posix()}")
                relative = source_relative.as_posix()
                if target_root:
                    relative = f"{target_root}/{relative}"
                add_file(source, root, normalize_relative(relative))
    for file_spec in selection["payload_files"]:
        source = Path(file_spec["source_file"])
        add_file(source, source.parent, file_spec["target_path"])
    unused = sorted(set(replacements) - set(files))
    if unused:
        raise AgengratorError("text replacements target missing payload files: " + ", ".join(unused))
    missing = sorted(REQUIRED_PAYLOAD - set(files))
    if missing:
        raise AgengratorError(f"payload is missing required files: {', '.join(missing)}")
    start_data = _planned_file_bytes(files["START_HERE.md"])
    start_text = start_data.decode("utf-8")
    if "Wait for the user's explicit approval" not in start_text or "read-only" not in start_text:
        raise AgengratorError("START_HERE.md does not preserve the receiver review gate")
    return dict(sorted(files.items()))


def _load_previous_manifest(output_root: Path) -> tuple[dict[str, str], dict[str, Any] | None]:
    manifest_path = output_root / MANIFEST_NAME
    if not manifest_path.exists():
        return {}, None
    if _is_linklike(manifest_path):
        raise AgengratorError("existing bundle manifest is a link or reparse point")
    manifest = load_json(manifest_path)
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("generator") != GENERATOR_NAME:
        raise AgengratorError("existing bundle manifest is not a supported Agengrator manifest")
    raw_files = manifest.get("managed_files")
    if not isinstance(raw_files, dict):
        raise AgengratorError("existing manifest managed_files must be an object")
    files: dict[str, str] = {}
    for relative, digest in raw_files.items():
        normalized = normalize_relative(str(relative))
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise AgengratorError(f"invalid managed hash for {relative}")
        files[normalized] = digest
    return files, manifest


def build_plan_from_selection(selection: dict[str, Any], output_root: Path) -> dict[str, Any]:
    output = output_root.resolve(strict=False)
    source_roots = ([Path(selection["payload_root"])] if selection["payload_root"] else
                    [Path(item["source_root"]) for item in selection["payload_sources"]])
    for source_root in source_roots:
        if output == source_root or output in source_root.parents or source_root in output.parents:
            raise AgengratorError("payload sources and output_root must be separate trees")
    files = collect_selection_payload(selection)
    previous, _ = _load_previous_manifest(output)
    creates: list[str] = []
    updates: list[str] = []
    unchanged: list[str] = []
    deletions: list[str] = []
    collisions: list[str] = []
    prior_hashes: dict[str, str] = {}

    for relative, metadata in files.items():
        target = output / Path(relative)
        if target.exists():
            if _is_linklike(target) or not target.is_file():
                collisions.append(relative)
                continue
            current_hash = sha256_file(target)
            if relative not in previous:
                collisions.append(relative)
                continue
            if current_hash != previous[relative]:
                raise AgengratorError(f"managed file drifted since the previous manifest: {relative}")
            prior_hashes[relative] = current_hash
            if current_hash == metadata["sha256"]:
                unchanged.append(relative)
            else:
                updates.append(relative)
        else:
            if relative in previous:
                raise AgengratorError(f"managed file is missing from the current bundle: {relative}")
            creates.append(relative)

    for relative, digest in previous.items():
        if relative in files:
            continue
        target = output / Path(relative)
        if not target.is_file() or _is_linklike(target) or sha256_file(target) != digest:
            raise AgengratorError(f"managed file cannot be safely deleted because it drifted or is missing: {relative}")
        prior_hashes[relative] = digest
        deletions.append(relative)

    if collisions:
        raise AgengratorError("unknown items occupy planned managed paths: " + ", ".join(sorted(collisions)))

    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "bundle_id": selection["bundle_id"],
        "generator": GENERATOR_NAME,
        "selection_spec": selection,
        "output_root": str(output),
        "selections": selection["selections"],
        "files": files,
        "prior_hashes": dict(sorted(prior_hashes.items())),
        "actions": {
            "create": sorted(creates),
            "update": sorted(updates),
            "unchanged": sorted(unchanged),
            "delete": sorted(deletions),
        },
    }
    plan_hash = sha256_bytes(canonical_json(body))
    deletion_hash = sha256_bytes(canonical_json(sorted(deletions))) if deletions else None
    return {**body, "plan_sha256": plan_hash, "deletions_sha256": deletion_hash}


def build_plan(selection_path: Path, output_root: Path) -> dict[str, Any]:
    return build_plan_from_selection(load_selection(selection_path), output_root)


def _plan_body(plan: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in plan.items() if key not in {"plan_sha256", "deletions_sha256"}}


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.agengrator-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _manifest_bytes(plan: dict[str, Any]) -> bytes:
    managed = {relative: metadata["sha256"] for relative, metadata in sorted(plan["files"].items())}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "bundle_id": plan["bundle_id"],
        "generator": GENERATOR_NAME,
        "selections": plan["selections"],
        "managed_files": managed,
    }
    data = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    scan_text(data.decode("utf-8"), MANIFEST_NAME)
    return data


def _verify_plan_inputs(plan: dict[str, Any]) -> None:
    files = plan.get("files")
    if not isinstance(files, dict):
        raise AgengratorError("plan files must be an object")
    for relative, metadata in files.items():
        normalize_relative(relative)
        try:
            data = _planned_file_bytes(metadata)
        except (OSError, KeyError) as exc:
            raise AgengratorError(f"planned payload source is unavailable: {relative}") from exc
        if sha256_bytes(data) != metadata.get("sha256"):
            raise AgengratorError(f"planned payload changed after approval: {relative}")


def _planned_file_bytes(metadata: dict[str, Any]) -> bytes:
    source = Path(str(metadata.get("source_path", "")))
    root = Path(str(metadata.get("source_root", source.parent)))
    if not source.is_file() or _is_linklike(source):
        raise AgengratorError(f"planned payload source is missing or linked: {source}")
    rules = metadata.get("text_replacements", [])
    if not isinstance(rules, list):
        raise AgengratorError(f"planned transformations are invalid: {source}")
    return _transformed_bytes(source, root, rules)


def apply_plan_data(plan: dict[str, Any], approved_plan_hash: str, approved_deletions_hash: str | None = None) -> dict[str, Any]:
    actual_hash = sha256_bytes(canonical_json(_plan_body(plan)))
    if actual_hash != plan.get("plan_sha256") or approved_plan_hash != actual_hash:
        raise AgengratorError("approved plan SHA-256 does not match the exact plan")
    deletions = list(plan.get("actions", {}).get("delete", []))
    expected_deletion_hash = plan.get("deletions_sha256")
    if deletions and (not approved_deletions_hash or approved_deletions_hash != expected_deletion_hash):
        raise AgengratorError("proposed deletions require their separately approved SHA-256")
    _verify_plan_inputs(plan)
    output = Path(str(plan["output_root"]))
    raw_selection = plan.get("selection_spec")
    if not isinstance(raw_selection, dict):
        raise AgengratorError("plan selection_spec must be an object")
    current_plan = build_plan_from_selection(normalize_selection(raw_selection), output)
    if current_plan.get("plan_sha256") != actual_hash:
        raise AgengratorError("bundle or payload changed after the plan was approved")

    output.parent.mkdir(parents=True, exist_ok=True)
    output_existed = output.exists()
    output.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=".agengrator-backup-", dir=str(output.parent)))
    old_manifest = output / MANIFEST_NAME
    old_manifest_present = old_manifest.is_file()
    created: list[Path] = []
    backed_up: list[str] = []
    try:
        if old_manifest_present:
            shutil.copy2(old_manifest, backup / MANIFEST_NAME)
        for relative in sorted(set(plan["actions"]["update"] + deletions)):
            source = output / Path(relative)
            destination = backup / Path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            backed_up.append(relative)
        for relative in plan["actions"]["create"] + plan["actions"]["update"]:
            target = output / Path(relative)
            if relative in plan["actions"]["create"]:
                created.append(target)
            data = _planned_file_bytes(plan["files"][relative])
            _atomic_write(target, data)
        for relative in deletions:
            (output / Path(relative)).unlink()
        _atomic_write(old_manifest, _manifest_bytes(plan))
        validation = validate_bundle(output)
        if validation["status"] != "PASS":
            raise AgengratorError("post-apply validation did not pass")
    except Exception:
        for target in reversed(created):
            if target.is_file():
                target.unlink()
        for relative in backed_up:
            backup_file = backup / Path(relative)
            _atomic_write(output / Path(relative), backup_file.read_bytes())
        if old_manifest_present:
            _atomic_write(old_manifest, (backup / MANIFEST_NAME).read_bytes())
        elif old_manifest.exists():
            old_manifest.unlink()
        for directory in sorted((path for path in output.rglob("*") if path.is_dir()), key=lambda p: len(p.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        if not output_existed:
            try:
                output.rmdir()
            except OSError:
                pass
        raise
    finally:
        shutil.rmtree(backup, ignore_errors=True)
    return {
        "status": "PASS",
        "output_root": str(output),
        "plan_sha256": actual_hash,
        "created": len(plan["actions"]["create"]),
        "updated": len(plan["actions"]["update"]),
        "deleted": len(deletions),
        "managed_files": len(plan["files"]),
    }


def apply_plan(plan_path: Path, approved_plan_hash: str, approved_deletions_hash: str | None = None) -> dict[str, Any]:
    return apply_plan_data(load_json(plan_path), approved_plan_hash, approved_deletions_hash)


def validate_bundle(output_root: Path) -> dict[str, Any]:
    output = _require_plain_directory(output_root, "output root")
    managed, manifest = _load_previous_manifest(output)
    if manifest is None:
        raise AgengratorError(f"bundle manifest is missing: {MANIFEST_NAME}")
    manifest_text = (output / MANIFEST_NAME).read_text(encoding="utf-8")
    scan_text(manifest_text, MANIFEST_NAME)
    missing_required = sorted(REQUIRED_PAYLOAD - set(managed))
    if missing_required:
        raise AgengratorError("manifest omits required files: " + ", ".join(missing_required))
    for relative, expected in managed.items():
        path = output / Path(relative)
        if not path.is_file():
            raise AgengratorError(f"managed file is missing: {relative}")
        data, _ = read_portable_text(path, root=output)
        if sha256_bytes(data) != expected:
            raise AgengratorError(f"managed file hash mismatch: {relative}")
    for relative in managed:
        if not relative.lower().endswith(".md"):
            continue
        source = output / Path(relative)
        text = source.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK_PATTERN.findall(text):
            target = raw_target.strip().strip("<>").split(maxsplit=1)[0]
            if not target or "{" in target or "}" in target or target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target_path = target.split("#", 1)[0].replace("/", os.sep)
            if target_path and not (source.parent / target_path).exists():
                raise AgengratorError(f"broken relative Markdown link in {relative}: {target}")
    start_text = (output / "START_HERE.md").read_text(encoding="utf-8")
    if "Wait for the user's explicit approval" not in start_text or "read-only" not in start_text:
        raise AgengratorError("receiver review gate is missing")
    return {
        "status": "PASS",
        "output_root": str(output),
        "bundle_id": manifest.get("bundle_id"),
        "managed_files": len(managed),
        "selections": len(manifest.get("selections", [])),
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="list bounded migration candidates")
    inventory.add_argument("--workspace-root", type=Path, required=True)
    inventory.add_argument("--skill-root", type=Path, action="append", default=[])

    plan = subparsers.add_parser("plan", help="compute a no-write synchronization plan")
    selection_input = plan.add_mutually_exclusive_group(required=True)
    selection_input.add_argument("--selection", type=Path)
    selection_input.add_argument("--selection-stdin", action="store_true")
    plan.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    plan.add_argument("--plan-file", type=Path)

    apply = subparsers.add_parser("apply", help="apply an exactly approved plan")
    plan_input = apply.add_mutually_exclusive_group(required=True)
    plan_input.add_argument("--plan", type=Path)
    plan_input.add_argument("--plan-stdin", action="store_true")
    apply.add_argument("--approve-plan-sha256", required=True)
    apply.add_argument("--approve-deletions-sha256")

    validate = subparsers.add_parser("validate", help="validate a generated bundle")
    validate.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inventory":
            result = inventory_candidates(args.workspace_root, args.skill_root)
        elif args.command == "plan":
            if args.selection_stdin:
                try:
                    raw_selection = json.loads(sys.stdin.read())
                except json.JSONDecodeError as exc:
                    raise AgengratorError(f"cannot read selection JSON from stdin: {exc}") from exc
                if not isinstance(raw_selection, dict):
                    raise AgengratorError("selection JSON root must be an object")
                result = build_plan_from_selection(normalize_selection(raw_selection), args.output_root)
            else:
                result = build_plan(args.selection, args.output_root)
            if args.plan_file:
                plan_file = args.plan_file.resolve(strict=False)
                output = args.output_root.resolve(strict=False)
                if plan_file == output or output in plan_file.parents:
                    raise AgengratorError("plan_file must be outside output_root")
                _write_json(plan_file, result)
        elif args.command == "apply":
            if args.plan_stdin:
                try:
                    raw_plan = json.loads(sys.stdin.read())
                except json.JSONDecodeError as exc:
                    raise AgengratorError(f"cannot read plan JSON from stdin: {exc}") from exc
                if not isinstance(raw_plan, dict):
                    raise AgengratorError("plan JSON root must be an object")
                result = apply_plan_data(raw_plan, args.approve_plan_sha256, args.approve_deletions_sha256)
            else:
                result = apply_plan(args.plan, args.approve_plan_sha256, args.approve_deletions_sha256)
        else:
            result = validate_bundle(args.output_root)
    except AgengratorError as exc:
        print(json.dumps({"status": "ERROR", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
