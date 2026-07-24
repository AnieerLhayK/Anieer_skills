"""Read-only GitHub tree audit for a projection contract; no repository clone."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


JsonObject = dict[str, Any]
Runner = Callable[..., subprocess.CompletedProcess[str]]


def string_list(contract: JsonObject, key: str) -> list[str]:
    value = contract.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{key} must be a list of non-empty strings")
    return value


def any_path_groups(contract: JsonObject) -> list[list[str]]:
    value = contract.get("required_any", [])
    if not isinstance(value, list):
        raise ValueError("required_any must be a list of path lists")
    groups: list[list[str]] = []
    for group in value:
        if not isinstance(group, list) or not group or not all(isinstance(path, str) and path for path in group):
            raise ValueError("each required_any item must be a non-empty list of paths")
        groups.append(group)
    return groups


def load_contract(path: Path) -> JsonObject:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read contract: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("contract must be a JSON object")
    for key in ("required_paths", "forbidden_path_prefixes", "recommended_paths", "allowed_top_level"):
        string_list(payload, key)
    any_path_groups(payload)
    limit = payload.get("max_blob_bytes")
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        raise ValueError("max_blob_bytes must be a positive integer")
    return payload


def fetch_tree(repo: str, branch: str, runner: Runner = subprocess.run) -> list[JsonObject]:
    result = runner(
        ["gh", "api", f"repos/{repo}/git/trees/{branch}?recursive=1"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"GitHub tree request failed: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GitHub tree request returned invalid JSON: {exc}") from exc
    tree = payload.get("tree") if isinstance(payload, dict) else None
    if not isinstance(tree, list) or not all(isinstance(entry, dict) for entry in tree):
        raise RuntimeError("GitHub tree response has no tree list")
    if isinstance(payload, dict) and payload.get("truncated"):
        raise RuntimeError("GitHub tree response was truncated; narrow the projection before auditing")
    return tree


def evaluate_tree(entries: list[JsonObject], contract: JsonObject) -> JsonObject:
    blobs = {
        str(entry["path"]): entry
        for entry in entries
        if entry.get("type") == "blob" and isinstance(entry.get("path"), str)
    }
    paths = set(blobs)
    errors: list[str] = []
    warnings: list[str] = []

    for path in string_list(contract, "required_paths"):
        if path not in paths:
            errors.append(f"missing required path: {path}")
    for group in any_path_groups(contract):
        if not paths.intersection(group):
            errors.append(f"missing one of required paths: {', '.join(group)}")
    for prefix in string_list(contract, "forbidden_path_prefixes"):
        for path in sorted(item for item in paths if item == prefix.rstrip("/") or item.startswith(prefix)):
            errors.append(f"forbidden path: {path}")
    for path in string_list(contract, "recommended_paths"):
        if path not in paths:
            warnings.append(f"missing recommended path: {path}")

    allowed_top_level = set(string_list(contract, "allowed_top_level"))
    if allowed_top_level:
        for top_level in sorted({path.split("/", 1)[0] for path in paths} - allowed_top_level):
            warnings.append(f"unexpected top-level path: {top_level}")

    limit = contract.get("max_blob_bytes")
    if isinstance(limit, int):
        for path, entry in sorted(blobs.items()):
            size = entry.get("size")
            if isinstance(size, int) and size > limit:
                errors.append(f"blob exceeds max_blob_bytes: {path} ({size} > {limit})")

    return {
        "status": "FAIL" if errors else ("WARN" if warnings else "PASS"),
        "summary": {"blob_count": len(blobs), "top_level_paths": sorted({path.split("/", 1)[0] for path in paths})},
        "errors": errors,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a GitHub repository tree against a projection contract.")
    parser.add_argument("--repo", required=True, help="GitHub owner/repository")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--out", type=Path, help="Optional JSON report path")
    args = parser.parse_args(argv)
    try:
        contract = load_contract(args.contract)
        expected_repo = contract.get("repository")
        if expected_repo not in (None, "OWNER/REPOSITORY", args.repo):
            raise ValueError(f"contract repository does not match --repo: {expected_repo}")
        expected_branch = contract.get("branch")
        if expected_branch not in (None, args.branch):
            raise ValueError(f"contract branch does not match --branch: {expected_branch}")
        report = evaluate_tree(fetch_tree(args.repo, args.branch), contract)
    except (RuntimeError, ValueError) as exc:
        report = {"status": "ERROR", "errors": [str(exc)], "warnings": []}
    report.update({"repository": args.repo, "branch": args.branch})
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
