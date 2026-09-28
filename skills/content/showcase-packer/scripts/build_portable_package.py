#!/usr/bin/env python3
"""Preview, plan, build, or verify a portable evidence package."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
WORKFLOW_SCHEMA_VERSION = "2.0"
PACKAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SECRET_EXTENSIONS = {".key", ".pem", ".pfx", ".p12", ".kdbx"}
SECRET_NAMES = {".env", "id_rsa", "id_ed25519"}
SECRET_TOKENS = ("secret", "credential", "password", "passwd", "api-key", "apikey", "token")
RAW_MARKERS = {"raw", "unredacted", "identifiable"}
EMAIL_PATTERN = re.compile(r"(?<![\w.-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
ABSOLUTE_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:\\|/Users/|/home/|/private/)")
TEXT_LIMIT = 1024 * 1024
CONTENT_FILES = (
    "README.md",
    "narrative/data.md",
    "narrative/approach.md",
    "narrative/conclusions.md",
    "review/evidence-map.md",
    "review/risks-and-limitations.md",
    "review/next-actions.md",
)
PLACEHOLDER_MARKERS = (
    "describe the goal, audience, scope",
    "record observed data, provenance summaries",
    "explain the proposed method, solution",
    "state supported conclusions, recommendations",
    "map each material claim to included evidence",
    "record exclusions, uncertainty, portability limits",
    "list the next decision, owner, evidence need",
)


class PackageError(ValueError):
    """Raised when a package operation cannot preserve the contract."""


def legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--package-name", required=True)
    parser.add_argument("--include", action="append", default=[], metavar="RELATIVE_PATH")
    parser.add_argument("--allow-risk", action="append", default=[], metavar="RELATIVE_PATH")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--confirmed", action="store_true")
    return parser


def workflow_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("preview", "plan"):
        command = subparsers.add_parser(name)
        command.add_argument("--source-root", required=True, type=Path)
        command.add_argument("--output-root", required=True, type=Path)
        command.add_argument("--package-name", required=True)
        command.add_argument("--include", action="append", default=[])
        command.add_argument("--allow-risk", action="append", default=[])
        if name == "plan":
            command.add_argument("--content-root", required=True, type=Path)
            command.add_argument("--output-plan", required=True, type=Path)
    build_command = subparsers.add_parser("build")
    build_command.add_argument("--plan", required=True, type=Path)
    build_command.add_argument("--approve-plan-sha256", required=True)
    verify_command = subparsers.add_parser("verify")
    verify_command.add_argument("--package-root", required=True, type=Path)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] in {"preview", "plan", "build", "verify"}:
        return workflow_parser().parse_args(values)
    args = legacy_parser().parse_args(values)
    args.command = "legacy"
    return args


def relative_path(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts or not value:
        raise PackageError(f"path must be a non-empty relative path: {value}")
    return candidate


def validate_roots(source_root: Path, output_root: Path, package_name: str) -> tuple[Path, Path]:
    if not PACKAGE_NAME.fullmatch(package_name):
        raise PackageError("package name must be lowercase ASCII kebab-case")
    source = source_root.resolve()
    output = output_root.resolve()
    if not source.is_dir():
        raise PackageError(f"source root does not exist: {source}")
    if output == source or output in source.parents or source in output.parents:
        raise PackageError("output root must be separate from the source tree")
    return source, output


def selected_files(source_root: Path, includes: list[str]) -> list[Path]:
    candidates = [source_root / relative_path(item) for item in includes] if includes else [
        path for path in source_root.rglob("*") if path.is_file()
    ]
    files: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            resolved.relative_to(source_root)
        except ValueError as exc:
            raise PackageError(f"selection escapes source root: {candidate}") from exc
        if not resolved.is_file():
            raise PackageError(f"selected material is not a file: {candidate}")
        files.append(resolved)
    return sorted(set(files), key=lambda path: path.relative_to(source_root).as_posix())


def read_text_for_risk(path: Path) -> str | None:
    if path.stat().st_size > TEXT_LIMIT:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def classify_risk(path: Path, source_root: Path) -> list[str]:
    relative = path.relative_to(source_root).as_posix()
    lowered_parts = [part.lower() for part in Path(relative).parts]
    basename = path.name.lower()
    risks: list[str] = []
    if path.suffix.lower() in SECRET_EXTENSIONS or basename in SECRET_NAMES or any(
        token in basename for token in SECRET_TOKENS
    ):
        risks.append("credential-or-private-key")
    if any(marker in lowered_parts or marker in basename for marker in RAW_MARKERS):
        risks.append("raw-sensitive-material")
    text = read_text_for_risk(path)
    if text:
        if EMAIL_PATTERN.search(text) or PHONE_PATTERN.search(text):
            risks.append("personal-data")
        if ABSOLUTE_PATH_PATTERN.search(text):
            risks.append("absolute-local-path")
    return risks


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def preview(source_root: Path, includes: list[str], allowed_risks: set[str]) -> dict[str, object]:
    accepted: list[dict[str, object]] = []
    excluded: list[dict[str, object]] = []
    for path in selected_files(source_root, includes):
        relative = path.relative_to(source_root).as_posix()
        risks = classify_risk(path, source_root)
        record = {
            "source_relative_path": relative,
            "size_bytes": path.stat().st_size,
            "sha256": sha256(path),
            "risks": risks,
        }
        if risks and relative not in allowed_risks:
            excluded.append(record)
        else:
            accepted.append(record)
    return {
        "schema_version": SCHEMA_VERSION,
        "accepted": accepted,
        "excluded": excluded,
        "estimated_size_bytes": sum(int(item["size_bytes"]) for item in accepted),
        "approved_exceptions": sorted(
            path for path in allowed_risks
            if any(item["source_relative_path"] == path for item in accepted)
        ),
    }


def canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_complete_content(content_root: Path) -> list[dict[str, object]]:
    root = content_root.resolve()
    if not root.is_dir():
        raise PackageError(f"content root does not exist: {root}")
    records: list[dict[str, object]] = []
    for relative in CONTENT_FILES:
        path = root / relative
        if not path.is_file():
            raise PackageError(f"missing staged content: {relative}")
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        if len(text.strip()) < 20 or "todo" in lowered or any(marker in lowered for marker in PLACEHOLDER_MARKERS):
            raise PackageError(f"staged content is incomplete or placeholder-only: {relative}")
        if ABSOLUTE_PATH_PATTERN.search(text):
            raise PackageError(f"staged content contains an absolute local path: {relative}")
        records.append({"package_relative_path": relative, "size_bytes": path.stat().st_size, "sha256": sha256(path)})
    return records


def create_plan(
    source_root: Path,
    content_root: Path,
    output_root: Path,
    package_name: str,
    includes: list[str],
    allowed_risks: set[str],
) -> dict[str, Any]:
    source, output = validate_roots(source_root, output_root, package_name)
    content = content_root.resolve()
    details = preview(source, includes, allowed_risks)
    payload: dict[str, Any] = {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "plan_type": "showcase-package",
        "package_name": package_name,
        "source_root": str(source),
        "content_root": str(content),
        "output_root": str(output),
        "includes": [relative_path(item).as_posix() for item in includes],
        "allowed_risks": sorted(allowed_risks),
        "materials": details,
        "content": load_complete_content(content),
    }
    payload["plan_sha256"] = canonical_hash(payload)
    return payload


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def validate_plan(plan: dict[str, Any], approved_hash: str) -> None:
    if plan.get("schema_version") != WORKFLOW_SCHEMA_VERSION or plan.get("plan_type") != "showcase-package":
        raise PackageError("unsupported showcase plan schema")
    recorded = str(plan.get("plan_sha256", ""))
    unhashed = {key: value for key, value in plan.items() if key != "plan_sha256"}
    if recorded != canonical_hash(unhashed):
        raise PackageError("plan content does not match its recorded SHA-256")
    if approved_hash != recorded:
        raise PackageError("approved plan SHA-256 does not match the plan")


def destination_for(output_root: Path, package_name: str) -> Path:
    destination = output_root / package_name
    try:
        destination.resolve().relative_to(output_root.resolve())
    except ValueError as exc:
        raise PackageError("package destination escapes output root") from exc
    if destination.exists():
        raise PackageError(f"refusing to overwrite existing package: {destination}")
    return destination


def build_from_plan(plan_path: Path, approved_hash: str) -> Path:
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    validate_plan(plan, approved_hash)
    source, output = validate_roots(Path(plan["source_root"]), Path(plan["output_root"]), plan["package_name"])
    content = Path(plan["content_root"]).resolve()
    allowed = set(plan["allowed_risks"])
    current_materials = preview(source, list(plan["includes"]), allowed)
    if current_materials != plan["materials"]:
        raise PackageError("source materials drifted after plan approval")
    current_content = load_complete_content(content)
    if current_content != plan["content"]:
        raise PackageError("staged content drifted after plan approval")
    destination = destination_for(output, plan["package_name"])
    output.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{plan['package_name']}.", dir=output))
    managed: list[dict[str, object]] = []
    try:
        for item in current_content:
            relative = str(item["package_relative_path"])
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(content / relative, target)
            if target.stat().st_size != item["size_bytes"] or sha256(target) != item["sha256"]:
                raise PackageError(f"staged content changed during copy: {relative}")
            managed.append({
                "package_relative_path": relative,
                "size_bytes": target.stat().st_size,
                "sha256": sha256(target),
                "role": "content",
            })
        for item in current_materials["accepted"]:
            source_relative = str(item["source_relative_path"])
            package_relative = (Path("materials") / source_relative).as_posix()
            target = temporary / package_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / source_relative, target)
            if target.stat().st_size != item["size_bytes"] or sha256(target) != item["sha256"]:
                raise PackageError(f"source material changed during copy: {source_relative}")
            managed.append({
                "package_relative_path": package_relative,
                "source_relative_path": source_relative,
                "size_bytes": target.stat().st_size,
                "sha256": sha256(target),
                "risks": item["risks"],
                "role": "material",
            })
        manifest = {
            "schema_version": WORKFLOW_SCHEMA_VERSION,
            "package_name": plan["package_name"],
            "plan_sha256": plan["plan_sha256"],
            "built_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "managed_files": sorted(managed, key=lambda item: str(item["package_relative_path"])),
            "approved_exceptions": current_materials["approved_exceptions"],
            "excluded": current_materials["excluded"],
        }
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.rename(destination)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return destination


def verify_package(package_root: Path) -> dict[str, Any]:
    root = package_root.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise PackageError("package manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != WORKFLOW_SCHEMA_VERSION:
        raise PackageError("unsupported package manifest schema")
    records = manifest.get("managed_files")
    if not isinstance(records, list):
        raise PackageError("manifest managed_files must be a list")
    expected = {"manifest.json"}
    problems: list[str] = []
    if not isinstance(manifest.get("plan_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", manifest["plan_sha256"]):
        problems.append("manifest plan_sha256 must be a SHA-256 digest")
    if not isinstance(manifest.get("package_name"), str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", manifest["package_name"]):
        problems.append("manifest package_name is invalid")
    roles: dict[str, str] = {}
    for item in records:
        if not isinstance(item, dict):
            problems.append("managed file record must be an object")
            continue
        if (not isinstance(item.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                or type(item.get("size_bytes")) is not int or item["size_bytes"] < 0
                or item.get("role") not in {"content", "material"}):
            problems.append("managed file record has invalid hash, size, or role")
        relative = relative_path(str(item.get("package_relative_path", ""))).as_posix()
        if relative in expected:
            problems.append(f"duplicate managed path: {relative}")
            continue
        expected.add(relative)
        roles[relative] = str(item.get("role", ""))
        path = root / relative
        if not path.is_file():
            problems.append(f"missing managed file: {relative}")
            continue
        if path.stat().st_size != item.get("size_bytes") or sha256(path) != item.get("sha256"):
            problems.append(f"managed file hash or size mismatch: {relative}")
    actual = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    for relative in CONTENT_FILES:
        if relative not in expected:
            problems.append(f"required content is not managed: {relative}")
        elif roles.get(relative) != "content":
            problems.append(f"required content has invalid role: {relative}")
    for relative, role in roles.items():
        if relative.startswith("materials/") and role != "material":
            problems.append(f"material has invalid role: {relative}")
        if role == "material" and not relative.startswith("materials/"):
            problems.append(f"material path is outside materials/: {relative}")
    problems.extend(f"unexpected file: {relative}" for relative in sorted(actual - expected))
    problems.extend(f"unlisted missing file: {relative}" for relative in sorted(expected - actual))
    return {
        "schema_version": WORKFLOW_SCHEMA_VERSION,
        "status": "PASS" if not problems else "ERROR",
        "package_name": manifest.get("package_name"),
        "plan_sha256": manifest.get("plan_sha256"),
        "checked_files": len(records),
        "problems": problems,
    }


def write_template(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")


def build(source_root: Path, output_root: Path, package_name: str, details: dict[str, object], *, confirmed: bool) -> Path:
    """Legacy compatibility builder; new callers should use a hashed plan."""
    if not confirmed:
        raise PackageError("build requires explicit confirmation after preview review")
    destination = destination_for(output_root, package_name)
    copied: list[dict[str, object]] = []
    try:
        destination.mkdir(parents=True)
        templates = {
            "README.md": ("Showcase Package", PLACEHOLDER_MARKERS[0].capitalize() + "."),
            "narrative/data.md": ("Data and Evidence", PLACEHOLDER_MARKERS[1].capitalize() + "."),
            "narrative/approach.md": ("Approach", PLACEHOLDER_MARKERS[2].capitalize() + "."),
            "narrative/conclusions.md": ("Conclusions", PLACEHOLDER_MARKERS[3].capitalize() + "."),
            "review/evidence-map.md": ("Evidence Map", PLACEHOLDER_MARKERS[4].capitalize() + "."),
            "review/risks-and-limitations.md": ("Risks and Limitations", PLACEHOLDER_MARKERS[5].capitalize() + "."),
            "review/next-actions.md": ("Next Actions", PLACEHOLDER_MARKERS[6].capitalize() + "."),
        }
        for relative, (title, body) in templates.items():
            write_template(destination / relative, title, body)
        for item in details["accepted"]:
            relative = str(item["source_relative_path"])
            source = source_root / relative
            target = destination / "materials" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append({
                "source_relative_path": relative,
                "package_relative_path": (Path("materials") / relative).as_posix(),
                "size_bytes": target.stat().st_size,
                "sha256": sha256(target),
                "risks": item["risks"],
            })
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "package_name": package_name,
            "built_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "files": copied,
            "approved_exceptions": details["approved_exceptions"],
            "excluded": details["excluded"],
        }
        (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command in {"legacy", "preview", "plan"}:
            source, output = validate_roots(args.source_root, args.output_root, args.package_name)
            allowed = {relative_path(item).as_posix() for item in args.allow_risk}
        if args.command == "legacy":
            details = preview(source, args.include, allowed)
            result: dict[str, object] = {"mode": "preview", "package_name": args.package_name, **details}
            if args.build:
                destination = build(source, output, args.package_name, details, confirmed=args.confirmed)
                result.update({"mode": "build", "output_path": str(destination)})
        elif args.command == "preview":
            result = {"mode": "preview", "package_name": args.package_name, **preview(source, args.include, allowed)}
        elif args.command == "plan":
            plan = create_plan(source, args.content_root, output, args.package_name, args.include, allowed)
            write_json_atomic(args.output_plan, plan)
            result = {"mode": "plan", "plan_path": str(args.output_plan.resolve()), "plan_sha256": plan["plan_sha256"]}
        elif args.command == "build":
            destination = build_from_plan(args.plan.resolve(), args.approve_plan_sha256)
            result = {"mode": "build", "output_path": str(destination)}
        else:
            result = {"mode": "verify", **verify_package(args.package_root)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") != "ERROR" else 1
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, PackageError) as exc:
        print(json.dumps({"status": "ERROR", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
