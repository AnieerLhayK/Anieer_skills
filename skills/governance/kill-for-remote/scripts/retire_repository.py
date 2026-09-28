#!/usr/bin/env python3
"""Audit and apply the narrow local-checkout retirement contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


class RetirementError(RuntimeError):
    def __init__(self, code: str, *, details: dict[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.details = details or {}


RESOURCE_SIZE_THRESHOLD = 1024**3
RESOURCE_DIRECTORY_SIGNALS = {
    "artifact", "artifacts", "checkpoint", "checkpoints", "data", "dataset",
    "datasets", "model", "models", "weight", "weights",
}
RESOURCE_SUFFIX_SIGNALS = {
    ".7z", ".bin", ".ckpt", ".csv", ".gguf", ".gz", ".h5", ".hdf5",
    ".jsonl", ".npy", ".npz", ".onnx", ".parquet", ".pt", ".pth",
    ".safetensors", ".tar", ".zip",
}


def canonical_path(value: str | Path, *, strict: bool = False) -> Path:
    path = Path(value).expanduser()
    return path.resolve(strict=strict)


def same_path(left: str | Path, right: str | Path) -> bool:
    return os.path.normcase(str(canonical_path(left))) == os.path.normcase(str(canonical_path(right)))


def is_reparse_point(path: Path) -> bool:
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        raise RetirementError("git_command_failed")
    return completed.stdout.strip()


def git_ignored_paths(repo: Path) -> list[Path]:
    completed = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--ignored", "--exclude-standard", "--others", "-z"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        raise RetirementError("ignored_inventory_unavailable")
    return [Path(value) for value in completed.stdout.split("\0") if value]


def git_path_is_ignored(repo: Path, relative_path: Path) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo), "check-ignore", "--quiet", "--", relative_path.as_posix()],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode == 0:
        return True
    if completed.returncode == 1:
        return False
    raise RetirementError("ignored_inventory_unavailable")


def git_succeeds(repo: Path, *args: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], check=False, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )
    return completed.returncode == 0


def remote_contains_local_ref(repo: Path, local_sha: str, remote_shas: dict[str, str]) -> bool:
    available = False
    for remote_sha in set(remote_shas.values()):
        if not git_succeeds(repo, "cat-file", "-e", f"{remote_sha}^{{commit}}"):
            continue
        available = True
        if git_succeeds(repo, "merge-base", "--is-ancestor", local_sha, remote_sha):
            return True
    if not available:
        raise RetirementError("remote_commit_unavailable_locally")
    return False


def github_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RetirementError("github_https_required")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise RetirementError("github_repository_invalid")
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise RetirementError("github_repository_invalid")
    return f"https://github.com/{owner}/{repo}"


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RetirementError("registry_unreadable") from error
    if not isinstance(data, dict):
        raise RetirementError("registry_invalid")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def repository_record(registry: dict[str, Any], repository_id: str) -> dict[str, Any]:
    repositories = registry.get("repositories")
    if not isinstance(repositories, dict) or repository_id not in repositories:
        raise RetirementError("repository_not_registered")
    record = repositories[repository_id]
    if not isinstance(record, dict):
        raise RetirementError("repository_record_invalid")
    required = {"github_url", "default_branch", "original_local_path", "status", "restore", "verification"}
    if not required.issubset(record):
        raise RetirementError("repository_record_invalid")
    if record.get("status") not in {"pending_retirement", "remote_only", "local_directory_retired"}:
        raise RetirementError("repository_record_invalid")
    github_url(str(record["github_url"]))
    receipt = record.get("resource_receipt")
    if receipt is not None:
        if not isinstance(receipt, list):
            raise RetirementError("repository_record_invalid")
        for item in receipt:
            if not isinstance(item, dict) or item.get("action") not in {"recycle", "preserve"}:
                raise RetirementError("repository_record_invalid")
            required_receipt = {"relative_path", "action", "file_count", "total_bytes"}
            if not required_receipt.issubset(item) or not isinstance(item["relative_path"], str):
                raise RetirementError("repository_record_invalid")
            if any(not isinstance(item[key], int) or isinstance(item[key], bool) for key in ("file_count", "total_bytes")):
                raise RetirementError("repository_record_invalid")
            if item["file_count"] < 1 or item["total_bytes"] < 0:
                raise RetirementError("repository_record_invalid")
            if item["action"] == "preserve":
                expected_keys = required_receipt | {"destination_path", "file_manifest_sha256", "completed_at"}
                digest = item.get("file_manifest_sha256")
                if set(item) != expected_keys or not isinstance(item.get("destination_path"), str) or not isinstance(item.get("completed_at"), str):
                    raise RetirementError("repository_record_invalid")
                if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                    raise RetirementError("repository_record_invalid")
            elif set(item) != required_receipt:
                raise RetirementError("repository_record_invalid")
    local_receipt = record.get("local_directory_receipt")
    if local_receipt is not None:
        required_local = {"retained_paths", "file_count", "file_manifest_sha256", "recreated_at"}
        if not isinstance(local_receipt, dict) or set(local_receipt) != required_local:
            raise RetirementError("repository_record_invalid")
        paths = local_receipt["retained_paths"]
        digest = local_receipt["file_manifest_sha256"]
        if not isinstance(paths, list) or len(paths) != len(set(paths)) or any(not isinstance(path, str) or not path for path in paths):
            raise RetirementError("repository_record_invalid")
        if not isinstance(local_receipt["file_count"], int) or isinstance(local_receipt["file_count"], bool) or local_receipt["file_count"] < 0:
            raise RetirementError("repository_record_invalid")
        if local_receipt["file_count"] != len(paths) or not isinstance(local_receipt["recreated_at"], str):
            raise RetirementError("repository_record_invalid")
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise RetirementError("repository_record_invalid")
    return record


def remote_refs(repo: Path) -> tuple[str, str, dict[str, str], dict[str, str]]:
    head_lines = git(repo, "ls-remote", "--symref", "origin", "HEAD").splitlines()
    default_branch = ""
    default_sha = ""
    for line in head_lines:
        if line.startswith("ref: refs/heads/") and line.endswith("\tHEAD"):
            default_branch = line.split("\t", 1)[0].removeprefix("ref: refs/heads/")
        elif line.endswith("\tHEAD"):
            default_sha = line.split("\t", 1)[0]
    if not default_branch or not default_sha:
        raise RetirementError("remote_default_branch_unavailable")
    heads: dict[str, str] = {}
    tags: dict[str, str] = {}
    for line in git(repo, "ls-remote", "--heads", "--tags", "origin").splitlines():
        if "\t" not in line:
            continue
        sha, ref = line.split("\t", 1)
        if ref.startswith("refs/heads/"):
            heads[ref.removeprefix("refs/heads/")] = sha
        elif ref.startswith("refs/tags/"):
            tags[ref.removeprefix("refs/tags/").removesuffix("^{}") ] = sha
    return default_branch, default_sha, heads, tags


def local_refs(repo: Path, namespace: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in git(repo, "for-each-ref", "--format=%(refname:short) %(objectname)", namespace).splitlines():
        name, _, sha = line.partition(" ")
        if name and sha:
            result[name] = sha
    return result


def fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def relative_path(value: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or path == Path("."):
        raise RetirementError("resource_relative_path_invalid")
    return path


def safe_resource_file(repo: Path, relative: Path) -> Path:
    source = repo / relative
    try:
        resolved = source.resolve(strict=True)
    except OSError as error:
        raise RetirementError("resource_source_missing") from error
    if repo not in resolved.parents or is_reparse_point(source) or not source.is_file():
        raise RetirementError("resource_source_unsafe")
    return source


def resource_category(relative: Path, total_bytes: int) -> str | None:
    names = {part.casefold() for part in relative.parts[:-1]}
    suffix = relative.suffix.casefold()
    if names & RESOURCE_DIRECTORY_SIGNALS:
        return "named_resource"
    if suffix in RESOURCE_SUFFIX_SIGNALS:
        return "typed_resource"
    if total_bytes >= RESOURCE_SIZE_THRESHOLD:
        return "large_resource"
    return None


def ignored_resource_candidates(repo: Path) -> list[dict[str, Any]]:
    grouped: dict[Path, list[Path]] = {}
    for raw_path in git_ignored_paths(repo):
        relative = relative_path(raw_path.as_posix())
        source = safe_resource_file(repo, relative)
        root = Path(relative.parts[0])
        grouped.setdefault(root, []).append(relative)

    candidates: list[dict[str, Any]] = []
    for root, files in sorted(grouped.items(), key=lambda item: item[0].as_posix().casefold()):
        file_fingerprint = []
        for path in sorted(files):
            metadata = safe_resource_file(repo, path).stat()
            file_fingerprint.append({"relative_path": path.as_posix(), "size": metadata.st_size, "mtime_ns": metadata.st_mtime_ns})
        total_bytes = sum(item["size"] for item in file_fingerprint)
        category = resource_category(root, total_bytes)
        if category is None:
            category = next((resource_category(path, total_bytes) for path in files if resource_category(path, total_bytes)), None)
        if category is not None:
            candidates.append({
                "relative_path": root.as_posix(),
                "category": category,
                "file_count": len(files),
                "total_bytes": total_bytes,
                "files": [path.as_posix() for path in sorted(files)],
                "file_fingerprint": file_fingerprint,
            })
    return candidates


def ignored_resource_inventory(repo: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for raw_path in git_ignored_paths(repo):
        relative = relative_path(raw_path.as_posix())
        metadata = safe_resource_file(repo, relative).stat()
        inventory.append({
            "relative_path": relative.as_posix(),
            "size": metadata.st_size,
            "mtime_ns": metadata.st_mtime_ns,
        })
    return sorted(inventory, key=lambda item: item["relative_path"].casefold())


def ignored_inventory_fingerprint(inventory: list[dict[str, Any]]) -> str:
    return fingerprint({"ignored_resources": inventory})


def public_resource_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: candidate[key] for key in ("relative_path", "category", "file_count", "total_bytes")}
        for candidate in candidates
    ]


def resource_fingerprint(candidates: list[dict[str, Any]]) -> str:
    return fingerprint({"resources": [
        {
            **item,
            "files": candidate.get("file_fingerprint", candidate.get("files", [])),
        }
        for candidate, item in zip(candidates, public_resource_candidates(candidates), strict=True)
    ]})


def resource_plan_template(repository_id: str, canonical: Path, audit_fingerprint: str, resources: list[dict[str, Any]], resources_fingerprint: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "repository_id": repository_id,
        "canonical_path": str(canonical),
        "audit_fingerprint": audit_fingerprint,
        "resource_fingerprint": resources_fingerprint,
        "candidates": [
            {"relative_path": item["relative_path"], "action": "recycle"}
            for item in resources
        ],
    }


def read_resource_plan(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RetirementError("resource_plan_unreadable") from error
    if not isinstance(data, dict):
        raise RetirementError("resource_plan_invalid")
    return data


def resource_plan_digest(plan: dict[str, Any]) -> str:
    return fingerprint(plan)


def audit(registry_path: Path, repository_id: str, workspace_root: Path | None = None) -> dict[str, Any]:
    registry = read_json(registry_path)
    record = repository_record(registry, repository_id)
    reasons: list[str] = []
    try:
        target = canonical_path(str(record["original_local_path"]), strict=True)
    except OSError:
        return {"status": "blocked", "repository_id": repository_id, "reasons": ["local_checkout_missing"]}
    if not target.is_dir():
        reasons.append("local_checkout_not_directory")
    if target.parent == target:
        reasons.append("drive_root_rejected")
    if is_reparse_point(target):
        reasons.append("reparse_point_rejected")
    root = workspace_root or registry_path.parents[2]
    if same_path(target, root) or root in target.parents:
        reasons.append("workspace_path_rejected")
    try:
        top_level = canonical_path(git(target, "rev-parse", "--show-toplevel"), strict=True)
        if not same_path(target, top_level):
            reasons.append("target_is_not_git_toplevel")
        if not (target / ".git").is_dir():
            reasons.append("linked_worktree_rejected")
        if git(target, "status", "--porcelain=v1", "--untracked-files=all"):
            reasons.append("worktree_not_clean")
        candidates = ignored_resource_candidates(target)
        candidates_fingerprint = resource_fingerprint(candidates)
        inventory_fingerprint = ignored_inventory_fingerprint(ignored_resource_inventory(target))
        origin = github_url(git(target, "remote", "get-url", "origin"))
        if origin != github_url(str(record["github_url"])):
            reasons.append("origin_does_not_match_record")
        default_branch, default_sha, remote_heads, remote_tags = remote_refs(target)
        if default_branch != record["default_branch"]:
            reasons.append("default_branch_does_not_match_record")
        if git(target, "rev-parse", "HEAD") != default_sha:
            reasons.append("head_does_not_match_remote_default")
        for name, sha in local_refs(target, "refs/heads").items():
            if remote_heads.get(name) != sha and not remote_contains_local_ref(target, sha, remote_heads):
                reasons.append("local_branch_not_fully_pushed")
                break
        for name, sha in local_refs(target, "refs/tags").items():
            if remote_tags.get(name) != sha and not remote_contains_local_ref(target, sha, remote_tags):
                reasons.append("local_tag_not_fully_pushed")
                break
    except RetirementError as error:
        reasons.append(error.code)
        default_branch = default_sha = origin = ""
        candidates = []
        candidates_fingerprint = resource_fingerprint(candidates)
        inventory_fingerprint = ignored_inventory_fingerprint([])
    if reasons:
        return {"status": "blocked", "repository_id": repository_id, "canonical_path": str(target), "reasons": sorted(set(reasons))}
    details = {
        "repository_id": repository_id,
        "canonical_path": str(target),
        "github_url": origin,
        "default_branch": default_branch,
        "head": default_sha,
        "resource_fingerprint": candidates_fingerprint,
        "ignored_inventory_fingerprint": inventory_fingerprint,
    }
    audit_fingerprint = fingerprint(details)
    result: dict[str, Any] = {
        "status": "ready",
        **details,
        "fingerprint": audit_fingerprint,
        "resource_candidates": public_resource_candidates(candidates),
    }
    result["local_resource_plan_template"] = local_resource_plan_template(result)
    if candidates:
        result["next_action"] = "invoke_$grill-me_then_provide_resource_plan"
        result["resource_plan_template"] = resource_plan_template(
            repository_id, target, audit_fingerprint, result["resource_candidates"], candidates_fingerprint
        )
    return result


def recycle(target: Path) -> None:
    adapter = Path(__file__).with_name("recycle_repository.ps1")
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(adapter), "-LiteralPath", str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode or target.exists():
        raise RetirementError("recycle_failed")


def cleanup_launcher(path: Path | None, target: Path) -> list[str]:
    if path is None or not path.exists():
        return []
    data = read_json(path)
    projects = data.get("projects")
    if not isinstance(projects, dict):
        raise RetirementError("launcher_registry_invalid")
    removed = [key for key, value in projects.items() if isinstance(value, dict) and isinstance(value.get("path"), str) and same_path(value["path"], target)]
    for key in removed:
        del projects[key]
    if removed:
        write_json(path, data)
    return removed


def cleanup_external_projects(path: Path, target: Path) -> str | None:
    if not path.exists():
        return None
    try:
        import yaml  # Workspace bundled runtime dependency; required only when a match exists.
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except ImportError as error:
        raise RetirementError("yaml_runtime_unavailable") from error
    except (OSError, yaml.YAMLError) as error:
        raise RetirementError("external_project_registry_unreadable") from error
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict):
        raise RetirementError("external_project_registry_invalid")
    matches = [key for key, value in projects.items() if isinstance(value, dict) and isinstance(value.get("local_path"), str) and same_path(value["local_path"], target)]
    if len(matches) > 1:
        raise RetirementError("external_project_registry_ambiguous")
    if not matches:
        return None
    key = matches[0]
    del projects[key]
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return key


def has_reparse_ancestor(path: Path) -> bool:
    current = path
    while current != current.parent:
        if current.exists() and is_reparse_point(current):
            return True
        current = current.parent
    return current.exists() and is_reparse_point(current)


def is_within(path: Path, parent: Path) -> bool:
    return same_path(path, parent) or canonical_path(parent) in canonical_path(path).parents


def validate_resource_destination(value: str, checkout: Path) -> Path:
    raw = Path(value).expanduser()
    if not raw.is_absolute() or raw.exists() or not raw.parent.exists():
        raise RetirementError("resource_destination_invalid")
    if has_reparse_ancestor(raw.parent):
        raise RetirementError("resource_destination_unsafe")
    destination = canonical_path(raw, strict=False)
    if is_within(destination, checkout) or is_within(checkout, destination):
        raise RetirementError("resource_destination_unsafe")
    return destination


def validate_resource_plan(plan: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, dict[str, Any]]:
    expected = {item["relative_path"] for item in current.get("resource_candidates", [])}
    if not expected:
        if plan is not None:
            raise RetirementError("resource_plan_unexpected")
        return {}
    if not isinstance(plan, dict):
        raise RetirementError("resource_plan_required")
    required = {"schema_version", "repository_id", "canonical_path", "audit_fingerprint", "resource_fingerprint", "candidates"}
    if set(plan) != required or plan.get("schema_version") != "1.0":
        raise RetirementError("resource_plan_invalid")
    string_fields = ("repository_id", "canonical_path", "audit_fingerprint", "resource_fingerprint")
    if any(not isinstance(plan.get(field), str) for field in string_fields):
        raise RetirementError("resource_plan_invalid")
    for field in ("audit_fingerprint", "resource_fingerprint"):
        value = plan[field]
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise RetirementError("resource_plan_invalid")
    if plan["repository_id"] != current["repository_id"] or not same_path(plan["canonical_path"], current["canonical_path"]):
        raise RetirementError("resource_plan_identity_mismatch")
    if plan["audit_fingerprint"] != current["fingerprint"] or plan["resource_fingerprint"] != current["resource_fingerprint"]:
        raise RetirementError("resource_plan_stale")
    entries = plan["candidates"]
    if not isinstance(entries, list):
        raise RetirementError("resource_plan_invalid")
    decisions: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("relative_path"), str) or entry.get("action") not in {"recycle", "preserve"}:
            raise RetirementError("resource_plan_invalid")
        relative = relative_path(entry["relative_path"]).as_posix()
        if relative in decisions or relative not in expected:
            raise RetirementError("resource_plan_coverage_invalid")
        if entry["action"] == "recycle":
            if set(entry) != {"relative_path", "action"}:
                raise RetirementError("resource_plan_invalid")
        else:
            if set(entry) != {"relative_path", "action", "destination_path"} or not isinstance(entry.get("destination_path"), str):
                raise RetirementError("resource_plan_invalid")
        decisions[relative] = entry
    if set(decisions) != expected:
        raise RetirementError("resource_plan_coverage_invalid")
    return decisions


def paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def validate_local_resource_plan(plan: dict[str, Any] | None, current: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[Path]]:
    if not isinstance(plan, dict):
        raise RetirementError("local_resource_plan_required")
    required = {
        "schema_version", "retirement_mode", "repository_id", "canonical_path",
        "audit_fingerprint", "resource_fingerprint", "ignored_inventory_fingerprint",
        "candidates", "local_retained_paths",
    }
    if set(plan) != required or plan.get("schema_version") != "1.1" or plan.get("retirement_mode") != "local-directory":
        raise RetirementError("local_resource_plan_invalid")
    fields = ("repository_id", "canonical_path", "audit_fingerprint", "resource_fingerprint", "ignored_inventory_fingerprint")
    if any(not isinstance(plan.get(field), str) for field in fields):
        raise RetirementError("local_resource_plan_invalid")
    if plan["repository_id"] != current["repository_id"] or not same_path(plan["canonical_path"], current["canonical_path"]):
        raise RetirementError("resource_plan_identity_mismatch")
    if any(len(plan[field]) != 64 or any(char not in "0123456789abcdef" for char in plan[field]) for field in fields[2:]):
        raise RetirementError("local_resource_plan_invalid")
    if plan["audit_fingerprint"] != current["fingerprint"] or any(plan[field] != current[field] for field in ("resource_fingerprint", "ignored_inventory_fingerprint")):
        raise RetirementError("resource_plan_stale")
    expected = {item["relative_path"] for item in current.get("resource_candidates", [])}
    entries = plan["candidates"]
    if not isinstance(entries, list) or not isinstance(plan["local_retained_paths"], list):
        raise RetirementError("local_resource_plan_invalid")
    decisions: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"relative_path", "action"} or not isinstance(entry.get("relative_path"), str) or entry.get("action") not in {"recycle", "retain_local"}:
            raise RetirementError("local_resource_plan_invalid")
        relative = relative_path(entry["relative_path"]).as_posix()
        if relative not in expected or relative in decisions:
            raise RetirementError("resource_plan_coverage_invalid")
        decisions[relative] = entry
    if set(decisions) != expected:
        raise RetirementError("resource_plan_coverage_invalid")
    retained: list[Path] = []
    for entry in plan["local_retained_paths"]:
        if not isinstance(entry, dict) or set(entry) != {"relative_path"} or not isinstance(entry.get("relative_path"), str):
            raise RetirementError("local_resource_plan_invalid")
        path = relative_path(entry["relative_path"])
        if any(paths_overlap(path, existing) for existing in retained):
            raise RetirementError("local_resource_plan_overlap")
        retained.append(path)
    candidate_roots = [relative_path(name) for name, entry in decisions.items() if entry["action"] == "retain_local"]
    if any(any(paths_overlap(path, root) for root in candidate_roots) for path in retained):
        raise RetirementError("local_resource_plan_overlap")
    return decisions, retained


def local_resource_plan_template(current: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.1",
        "retirement_mode": "local-directory",
        "repository_id": current["repository_id"],
        "canonical_path": current["canonical_path"],
        "audit_fingerprint": current["fingerprint"],
        "resource_fingerprint": current["resource_fingerprint"],
        "ignored_inventory_fingerprint": current["ignored_inventory_fingerprint"],
        "candidates": [{"relative_path": item["relative_path"], "action": "recycle"} for item in current["resource_candidates"]],
        "local_retained_paths": [],
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preserve_resource(repo: Path, candidate: dict[str, Any], destination: Path) -> dict[str, Any]:
    root = relative_path(candidate["relative_path"])
    stage = destination.with_name(f".{destination.name}.kill-for-remote-{uuid.uuid4().hex}.partial")
    if stage.exists():
        raise RetirementError("resource_staging_conflict")
    manifest: list[dict[str, str]] = []
    try:
        stage.mkdir()
        for value in candidate["files"]:
            relative = relative_path(value)
            if root != relative and root not in relative.parents:
                raise RetirementError("resource_plan_coverage_invalid")
            if not git_path_is_ignored(repo, relative):
                raise RetirementError("resource_source_not_ignored")
            source = safe_resource_file(repo, relative)
            inner = Path(source.name) if relative == root else relative.relative_to(root)
            copied = stage / inner
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copied)
            source_hash = sha256_file(source)
            copied_hash = sha256_file(copied)
            if source_hash != copied_hash:
                raise RetirementError("resource_hash_mismatch")
            manifest.append({"relative_path": relative.as_posix(), "sha256": source_hash})
        os.replace(stage, destination)
    except RetirementError as error:
        raise RetirementError(error.code, details={"recovery_path": str(stage)}) from error
    except OSError as error:
        raise RetirementError("resource_copy_failed", details={"recovery_path": str(stage)}) from error
    return {
        "relative_path": root.as_posix(),
        "action": "preserve",
        "destination_path": str(destination),
        "file_count": len(manifest),
        "total_bytes": candidate["total_bytes"],
        "file_manifest_sha256": fingerprint({"files": manifest}),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def preserve_resources(repo: Path, current: dict[str, Any], decisions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    if not current.get("resource_candidates"):
        return []
    candidates = ignored_resource_candidates(repo)
    if resource_fingerprint(candidates) != current.get("resource_fingerprint") or public_resource_candidates(candidates) != current.get("resource_candidates", []):
        raise RetirementError("resource_inventory_changed")
    destinations: dict[str, Path] = {}
    for candidate in candidates:
        decision = decisions[candidate["relative_path"]]
        if decision["action"] == "preserve":
            destinations[candidate["relative_path"]] = validate_resource_destination(
                decision["destination_path"], Path(current["canonical_path"])
            )
    destination_values = list(destinations.values())
    for index, destination in enumerate(destination_values):
        if any(paths_overlap(destination, other) for other in destination_values[index + 1:]):
            raise RetirementError("resource_destination_unsafe")
    receipt: list[dict[str, Any]] = []
    for candidate in candidates:
        decision = decisions[candidate["relative_path"]]
        if decision["action"] == "recycle":
            receipt.append({
                "relative_path": candidate["relative_path"], "action": "recycle",
                "file_count": candidate["file_count"], "total_bytes": candidate["total_bytes"],
            })
            continue
        receipt.append(preserve_resource(repo, candidate, destinations[candidate["relative_path"]]))
    return receipt


def local_retained_files(repo: Path, current: dict[str, Any], decisions: dict[str, dict[str, Any]], explicit_paths: list[Path]) -> list[Path]:
    inventory = ignored_resource_inventory(repo)
    if ignored_inventory_fingerprint(inventory) != current["ignored_inventory_fingerprint"]:
        raise RetirementError("resource_inventory_changed")
    available = {item["relative_path"] for item in inventory}
    selected: set[Path] = set()
    for root_name, decision in decisions.items():
        if decision["action"] == "retain_local":
            root = relative_path(root_name)
            selected.update(relative_path(item["relative_path"]) for item in inventory if root == relative_path(item["relative_path"]) or root in relative_path(item["relative_path"]).parents)
    for path in explicit_paths:
        if path.as_posix() not in available:
            raise RetirementError("local_resource_not_ignored")
        selected.add(path)
    return sorted(selected, key=lambda path: path.as_posix().casefold())


def stage_local_resources(repo: Path, target: Path, retained: list[Path]) -> tuple[Path | None, dict[str, Any]]:
    manifest: list[dict[str, str]] = []
    if not retained:
        return None, {"retained_paths": [], "file_count": 0, "file_manifest_sha256": fingerprint({"files": []})}
    stage = target.with_name(f".{target.name}.kill-for-remote-{uuid.uuid4().hex}.local-retention")
    if stage.exists():
        raise RetirementError("resource_staging_conflict")
    try:
        stage.mkdir()
        for relative in retained:
            if not git_path_is_ignored(repo, relative):
                raise RetirementError("resource_source_not_ignored")
            source = safe_resource_file(repo, relative)
            copied = stage / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copied)
            source_hash = sha256_file(source)
            if source_hash != sha256_file(copied):
                raise RetirementError("resource_hash_mismatch")
            manifest.append({"relative_path": relative.as_posix(), "sha256": source_hash})
    except RetirementError as error:
        raise RetirementError(error.code, details={"recovery_path": str(stage)}) from error
    except OSError as error:
        raise RetirementError("resource_copy_failed", details={"recovery_path": str(stage)}) from error
    return stage, {
        "retained_paths": [item["relative_path"] for item in manifest],
        "file_count": len(manifest),
        "file_manifest_sha256": fingerprint({"files": manifest}),
    }


def recreate_local_directory(target: Path, stage: Path | None, receipt: dict[str, Any]) -> None:
    if target.exists() or has_reparse_ancestor(target.parent):
        raise RetirementError("local_directory_recreate_failed", details={"recovery_path": str(stage) if stage else None})
    try:
        if stage is None:
            target.mkdir()
        else:
            os.replace(stage, target)
        if not target.is_dir() or (target / ".git").exists() or is_reparse_point(target):
            raise RetirementError("local_directory_verification_failed")
        actual = sorted(
            path.relative_to(target).as_posix() for path in target.rglob("*")
            if path.is_file() and not is_reparse_point(path)
        )
        if actual != receipt["retained_paths"]:
            raise RetirementError("local_directory_verification_failed")
    except RetirementError as error:
        raise RetirementError(error.code, details={"recovery_path": str(stage) if stage and stage.exists() else None}) from error
    except OSError as error:
        raise RetirementError("local_directory_recreate_failed", details={"recovery_path": str(stage) if stage and stage.exists() else None}) from error


def apply_retirement(
    registry_path: Path,
    repository_id: str,
    confirm_id: str,
    confirm_path: str,
    expected_fingerprint: str,
    launcher_registry: Path | None,
    external_projects: Path,
    recycle_action: Callable[[Path], None] = recycle,
    resource_plan: dict[str, Any] | None = None,
    confirm_resource_plan_digest: str | None = None,
    retirement_mode: str = "remote-only",
) -> dict[str, Any]:
    current = audit(registry_path, repository_id)
    if current.get("status") != "ready":
        raise RetirementError("preflight_blocked")
    if confirm_id != repository_id or not same_path(confirm_path, current["canonical_path"]):
        raise RetirementError("confirmation_mismatch")
    if expected_fingerprint != current["fingerprint"]:
        raise RetirementError("preflight_changed")
    if retirement_mode not in {"remote-only", "local-directory"}:
        raise RetirementError("retirement_mode_invalid")
    if retirement_mode == "local-directory":
        decisions, explicit_local_paths = validate_local_resource_plan(resource_plan, current)
        plan_required = True
    else:
        decisions = validate_resource_plan(resource_plan, current)
        explicit_local_paths = []
        plan_required = bool(decisions)
    if plan_required and confirm_resource_plan_digest != resource_plan_digest(resource_plan):
        raise RetirementError("resource_plan_confirmation_mismatch")
    target = Path(current["canonical_path"])
    if retirement_mode == "local-directory":
        retained = local_retained_files(target, current, decisions, explicit_local_paths)
    else:
        retained = []
        if "resource_fingerprint" in current:
            candidates = ignored_resource_candidates(target)
            if (
                resource_fingerprint(candidates) != current.get("resource_fingerprint")
                or public_resource_candidates(candidates) != current.get("resource_candidates", [])
            ):
                raise RetirementError("resource_inventory_changed")
    if retirement_mode == "local-directory":
        stage, local_receipt = stage_local_resources(target, target, retained)
        resource_receipt = []
    else:
        stage = None
        local_receipt = None
        resource_receipt = preserve_resources(target, current, decisions)
    registry = read_json(registry_path)
    record = repository_record(registry, repository_id)
    record["status"] = "pending_retirement"
    record["verification"] = {"status": "verified", "commit": current["head"], "verified_at": datetime.now(timezone.utc).isoformat(), "failure_code": None}
    write_json(registry_path, registry)
    try:
        recycle_action(target)
        if retirement_mode == "local-directory":
            recreate_local_directory(target, stage, local_receipt)
        removed_launchers = cleanup_launcher(launcher_registry, target)
        migrated_external = cleanup_external_projects(external_projects, target)
    except RetirementError as error:
        registry = read_json(registry_path)
        record = repository_record(registry, repository_id)
        record["status"] = "pending_retirement"
        record["verification"]["status"] = "failed"
        record["verification"]["failure_code"] = error.code
        write_json(registry_path, registry)
        raise
    registry = read_json(registry_path)
    record = repository_record(registry, repository_id)
    record["status"] = "local_directory_retired" if retirement_mode == "local-directory" else "remote_only"
    record["retired_at"] = datetime.now(timezone.utc).isoformat()
    record["verification"] = {"status": "verified", "commit": current["head"], "verified_at": record["retired_at"], "failure_code": None}
    if resource_receipt:
        record["resource_receipt"] = resource_receipt
    if local_receipt is not None:
        record["local_directory_receipt"] = {**local_receipt, "recreated_at": record["retired_at"]}
    write_json(registry_path, registry)
    return {
        **current, "status": record["status"], "resource_receipt": resource_receipt,
        "local_directory_receipt": local_receipt,
        "removed_launcher_keys": removed_launchers, "migrated_external_project": migrated_external,
    }


def require_apply_authorization(
    record_id: str | None,
    agent: str,
    registry: Path,
    canonical_target: Path,
) -> None:
    if not record_id:
        raise RetirementError("active_task_record_required")
    try:
        subprocess.run(
            [
                "workspace", "records", "require", record_id,
                "--operation", "workspace_write",
                "--task-type", "cleanup_migration",
                "--bind", f"retirement-target={canonical_target}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["workspace", "agent", "check", "--agent", agent, "--operation", "write", "--path", str(registry), "--record-id", record_id], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RetirementError("agent_authorization_denied") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("audit", "inventory", "apply"))
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--id", required=True, dest="repository_id")
    parser.add_argument("--confirm-id")
    parser.add_argument("--confirm-path")
    parser.add_argument("--fingerprint")
    parser.add_argument("--resource-plan", type=Path)
    parser.add_argument("--confirm-resource-plan-sha256")
    parser.add_argument("--retirement-mode", choices=("remote-only", "local-directory"), default="remote-only")
    parser.add_argument("--launcher-registry", type=Path)
    parser.add_argument("--external-projects", type=Path)
    parser.add_argument("--record-id")
    parser.add_argument("--agent", default="codex")
    arguments = parser.parse_args(argv)
    try:
        if arguments.mode == "audit":
            result = audit(arguments.registry, arguments.repository_id)
        elif arguments.mode == "inventory":
            current = audit(arguments.registry, arguments.repository_id)
            if current.get("status") != "ready":
                result = current
            else:
                target = Path(current["canonical_path"])
                inventory = ignored_resource_inventory(target)
                result = {**current, "ignored_inventory": inventory, "ignored_inventory_fingerprint": ignored_inventory_fingerprint(inventory)}
        else:
            required = (arguments.confirm_id, arguments.confirm_path, arguments.fingerprint)
            if not all(required):
                raise RetirementError("apply_confirmation_required")
            authorized_audit = audit(arguments.registry, arguments.repository_id)
            if authorized_audit.get("status") != "ready":
                raise RetirementError("preflight_blocked")
            require_apply_authorization(
                arguments.record_id,
                arguments.agent,
                arguments.registry,
                Path(authorized_audit["canonical_path"]),
            )
            external = arguments.external_projects or arguments.registry.parents[1] / "external_projects.yaml"
            plan = read_resource_plan(arguments.resource_plan) if arguments.resource_plan else None
            result = apply_retirement(
                arguments.registry, arguments.repository_id, arguments.confirm_id, arguments.confirm_path,
                arguments.fingerprint, arguments.launcher_registry, external, resource_plan=plan,
                confirm_resource_plan_digest=arguments.confirm_resource_plan_sha256,
                retirement_mode=arguments.retirement_mode,
            )
    except RetirementError as error:
        result = {"status": "blocked", "reasons": [error.code], **error.details}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") in {"ready", "remote_only", "local_directory_retired"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
