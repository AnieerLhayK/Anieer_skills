#!/usr/bin/env python3
"""Audit disk-scan-reporter safety without modifying scanned content."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = SKILL_ROOT / "config" / "audit_policy.json"
SUBPROCESS_CALLS = {
    "os.system",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.Popen",
    "subprocess.run",
}


def load_audit_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("audit policy must be a JSON object")
    for key in (
        "allowed_write_roots",
        "static_source_roots",
        "destructive_apis",
        "destructive_command_tokens",
        "destructive_methods",
    ):
        if not isinstance(payload.get(key), list):
            raise ValueError(f"audit policy field must be a list: {key}")
    return payload


def qualified_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = qualified_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def string_literals(node: ast.AST) -> Iterable[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value


def static_audit_file(path: Path, policy: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        return [
            {
                "severity": "FAIL",
                "path": str(path),
                "line": getattr(exc, "lineno", None),
                "rule": "source_parse",
                "message": str(exc),
            }
        ]

    destructive_apis = {
        str(value).casefold() for value in policy.get("destructive_apis", [])
    }
    destructive_tokens = {
        str(value).casefold()
        for value in policy.get("destructive_command_tokens", [])
    }
    destructive_methods = {
        str(value).casefold()
        for value in policy.get("destructive_methods", [])
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = qualified_name(node.func)
        called_tail = called.rsplit(".", 1)[-1].casefold()
        if (
            called.casefold() in destructive_apis
            or called_tail in destructive_methods
        ):
            findings.append(
                {
                    "severity": "FAIL",
                    "path": str(path),
                    "line": node.lineno,
                    "rule": "destructive_api",
                    "message": f"destructive API detected: {called}",
                }
            )
        if called in SUBPROCESS_CALLS:
            command_text = " ".join(string_literals(node)).casefold()
            matched = sorted(
                token
                for token in destructive_tokens
                if token in command_text.split()
                or token in command_text.replace("_", "-")
            )
            if matched:
                findings.append(
                    {
                        "severity": "FAIL",
                        "path": str(path),
                        "line": node.lineno,
                        "rule": "destructive_command",
                        "message": (
                            "destructive command token detected in "
                            f"{called}: {', '.join(matched)}"
                        ),
                    }
                )
            elif not command_text:
                findings.append(
                    {
                        "severity": "WARNING",
                        "path": str(path),
                        "line": node.lineno,
                        "rule": "dynamic_subprocess",
                        "message": (
                            f"dynamic command in {called} could not be fully audited"
                        ),
                    }
                )
    return findings


def run_static_audit(
    skill_root: Path = SKILL_ROOT,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_policy = policy or load_audit_policy()
    files: list[Path] = []
    for relative in active_policy.get("static_source_roots", []):
        source_root = skill_root / str(relative)
        if source_root.is_file() and source_root.suffix.casefold() == ".py":
            files.append(source_root)
        elif source_root.is_dir():
            files.extend(sorted(source_root.rglob("*.py")))
    findings: list[dict[str, Any]] = []
    for path in files:
        file_findings = static_audit_file(path, active_policy)
        for finding in file_findings:
            try:
                finding["path"] = str(path.relative_to(skill_root))
            except ValueError:
                finding["path"] = path.name
        findings.extend(file_findings)
    status = (
        "FAIL"
        if any(item["severity"] == "FAIL" for item in findings)
        else (
            "WARNING"
            if any(item["severity"] == "WARNING" for item in findings)
            else "PASS"
        )
    )
    return {
        "status": status,
        "files_checked": len(files),
        "findings": findings,
        "limitations": (
            "Static analysis detects configured APIs and command literals; "
            "it cannot prove that arbitrary dynamic code is harmless."
        ),
    }


def allowed_write_roots(
    skill_root: Path,
    policy: dict[str, Any],
) -> list[Path]:
    lexical_root = Path(os.path.abspath(skill_root))
    resolved_root = lexical_root.resolve(strict=False)
    roots: list[Path] = []
    for relative in policy.get("allowed_write_roots", []):
        candidate = Path(os.path.abspath(lexical_root / str(relative)))
        try:
            candidate.relative_to(lexical_root)
            candidate.resolve(strict=False).relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(
                f"allowed write root escapes skill source: {relative}"
            ) from exc
        roots.append(candidate)
    return roots


def ensure_allowed_write_path(
    path: Path,
    skill_root: Path = SKILL_ROOT,
    policy: dict[str, Any] | None = None,
) -> Path:
    active_policy = policy or load_audit_policy()
    candidate = Path(os.path.abspath(path))
    resolved_candidate = candidate.resolve(strict=False)
    for root in allowed_write_roots(skill_root, active_policy):
        try:
            candidate.relative_to(root)
            resolved_candidate.relative_to(root.resolve(strict=False))
        except ValueError:
            continue
        return candidate
    raise PermissionError(
        "output path is outside allowed write roots: "
        f"{', '.join(active_policy.get('allowed_write_roots', []))}"
    )


def shallow_snapshot(
    root: Path,
    *,
    include_name_hash: bool = True,
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "available": False,
        "direct_child_count": 0,
        "root_mtime_ns": None,
        "direct_child_name_hash": None,
        "error": None,
    }
    try:
        metadata = root.stat()
        names: list[str] = []
        with os.scandir(root) as entries:
            for entry in entries:
                snapshot["direct_child_count"] += 1
                if include_name_hash:
                    names.append(entry.name)
        snapshot["available"] = True
        snapshot["root_mtime_ns"] = metadata.st_mtime_ns
        if include_name_hash:
            digest = hashlib.sha256()
            for name in sorted(names, key=str.casefold):
                digest.update(name.encode("utf-8", errors="surrogatepass"))
                digest.update(b"\0")
            snapshot["direct_child_name_hash"] = digest.hexdigest()
    except (OSError, PermissionError) as exc:
        snapshot["error"] = str(exc)
    return snapshot


def compare_snapshots(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any]:
    if not before or not after or not before.get("available") or not after.get("available"):
        return {
            "status": "UNAVAILABLE",
            "changed_fields": [],
            "limitations": "One or both shallow snapshots were unavailable.",
        }
    fields = (
        "direct_child_count",
        "root_mtime_ns",
        "direct_child_name_hash",
    )
    changed = [field for field in fields if before.get(field) != after.get(field)]
    return {
        "status": "WARNING" if changed else "UNCHANGED",
        "changed_fields": changed,
        "limitations": (
            "A shallow snapshot can reveal obvious concurrent changes but cannot "
            "prove that no file content changed."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", type=Path, default=SKILL_ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    policy = load_audit_policy(args.policy)
    result = run_static_audit(args.skill_root, policy)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Safety audit: {result['status']}")
        print(f"Files checked: {result['files_checked']}")
        for finding in result["findings"]:
            print(
                f"{finding['severity']}: {finding['path']}:{finding['line']} "
                f"{finding['message']}"
            )
        print(result["limitations"])
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
