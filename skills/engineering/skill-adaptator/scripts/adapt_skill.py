"""Plan and apply a governed Workspace-skill publication to a Git project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

SCHEMA = "1.0"
RECEIPT = Path(".workspace/skill-adaptator/manifest.json")
WORKSPACE = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(WORKSPACE))
from scripts.workspace.manifest_loader import load_manifest
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".txt", ".py", ".ps1", ".sh", ".toml"}
FORBIDDEN = re.compile(r"(^|/)(cache|caches|credentials?|private|corpus|reports?)(/|$)", re.I)
PORTABILITY = {"portable", "host-adapted", "workspace-bound"}
RESIDUAL_PATH = re.compile(
    r"(?:\bworkspace_manifest\.ya?ml\b|\bworkspace-registry\b)",
    re.I,
)
HOST_PATH = re.compile(r"(?:\bd:/ai/workspace(?:/|$)|\bproject_context(?:/|\\))", re.I)
WORKSPACE_VERB = (
    r"agent|records|task|plans|skill|workflow|validate|merge|knowledge|bootstrap|"
    r"preflight|changes|health|summary|sessions|reports|explain|launcher|claude|prompt|failure"
)
# Commands must occur in command position; separate argv-array recognition handles
# common subprocess forms without treating explanatory prose as an invocation.
WORKSPACE_COMMAND = re.compile(
    rf"(?:^|[\n;&|`]\s*|\$\(\s*)(?:&\s*)?(?:[\w./\\:-]*[\\/])?"
    rf"workspace(?:\.exe|\.cmd|\.ps1)?\s+(?:{WORKSPACE_VERB})\b|"
    rf"[\[,(]\s*['\"]workspace(?:\.exe|\.cmd|\.ps1)?['\"]\s*,\s*['\"](?:{WORKSPACE_VERB})['\"]",
    re.I,
)
WORKSPACE_MODULE = re.compile(r"\bscripts\.workspace\.workspace_cli\b", re.I)


class AdaptError(RuntimeError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fail(message: str) -> None:
    raise AdaptError(message)


def git_root(project: str | Path) -> Path:
    project = Path(project).resolve()
    try:
        actual = Path(
            subprocess.check_output(
                ["git", "-C", str(project), "rev-parse", "--show-toplevel"],
                text=True,
                stderr=subprocess.STDOUT,
            ).strip()
        ).resolve()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AdaptError(f"target is not a usable Git project: {project}") from exc
    if actual != project:
        fail(f"project-root must be the Git root: {actual}")
    return actual


def safe_target(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if not relative or candidate.is_absolute() or ".." in candidate.parts:
        fail("target-root must be a non-empty project-relative path")
    target = (root / candidate).resolve()
    if os.path.commonpath([str(root), str(target)]) != str(root):
        fail("target-root escapes the Git root")
    return target


def source_files(source: Path) -> list[tuple[str, bytes]]:
    source = Path(source).resolve()
    if not source.is_dir():
        fail(f"source skill directory does not exist: {source}")
    result: list[tuple[str, bytes]] = []
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source).as_posix()
        if path.is_symlink():
            fail(f"source contains a link: {relative}")
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        if FORBIDDEN.search(relative):
            fail(f"forbidden source material: {relative}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            fail(f"unsupported non-text source file: {relative}")
        data = path.read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AdaptError(f"source is not UTF-8: {relative}") from exc
        if b"-----BEGIN " in data or (
            path.suffix.lower() not in {".py", ".ps1", ".sh"}
            and re.search(
                rb"(?i)(api[_-]?key|secret|password)\s*[:=]\s*[\"']?[A-Za-z0-9_/-]{4,}", data
            )
        ):
            fail(f"sensitive material detected: {relative}")
        result.append((relative, data))
    if not any(relative == "SKILL.md" for relative, _ in result):
        fail("source has no SKILL.md")
    return result


def skill_contract(files: list[tuple[str, bytes]]) -> dict[str, Any]:
    raw = next(data.decode("utf-8-sig") for relative, data in files if relative == "SKILL.md")
    match = re.match(r"\A---\s*\n(.*?)\n---", raw, re.DOTALL)
    if not match:
        fail("SKILL.md has no YAML frontmatter")
    frontmatter = yaml.safe_load(match.group(1))
    metadata = frontmatter.get("metadata") if isinstance(frontmatter, dict) else None
    if not isinstance(metadata, dict):
        fail("SKILL.md metadata contract is required")
    portability = metadata.get("portability")
    distribution = metadata.get("distribution")
    requires = metadata.get("requires")
    if portability not in PORTABILITY:
        fail("SKILL.md metadata.portability is invalid")
    if not isinstance(distribution, str) or not distribution:
        fail("SKILL.md metadata.distribution is required")
    if not isinstance(requires, list) or any(
        not isinstance(item, str) or not item for item in requires
    ):
        fail("SKILL.md metadata.requires must be a string list")
    return {"portability": portability, "distribution": distribution, "requires": requires}


def dependency_resolutions(values: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            fail("--resolve-dependency must be REQUIREMENT=RESOLUTION")
        requirement, resolution = value.split("=", 1)
        if not requirement.strip() or not resolution.strip() or requirement in result:
            fail("dependency resolutions must be unique and non-empty")
        result[requirement] = resolution
    return result


def residual_scan(rendered: dict[str, bytes]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for relative, data in sorted(rendered.items()):
        text = data.decode("utf-8")
        executable_text = text
        if relative.lower().endswith((".md", ".markdown")):
            executable_text = "\n".join(_markdown_operational_text(text))
        normalized = executable_text.replace("\\", "/")
        full_normalized = text.replace("\\", "/")

        # A declared requirement is an executable package contract even though
        # surrounding frontmatter and prose are not. Check only that field.
        if relative.lower().endswith((".md", ".markdown")):
            frontmatter = re.match(r"\A---\s*\n(.*?)\n---", text, re.DOTALL)
            if frontmatter:
                try:
                    metadata = yaml.safe_load(frontmatter.group(1)) or {}
                except yaml.YAMLError:
                    metadata = {}
                contract = metadata.get("metadata") if isinstance(metadata, dict) else None
                requires = contract.get("requires", []) if isinstance(contract, dict) else []
                for requirement in requires if isinstance(requires, list) else []:
                    if isinstance(requirement, str) and _workspace_dependency(requirement):
                        findings.append(
                            {
                                "file": relative,
                                "marker": f"declared Workspace dependency: {requirement}",
                            }
                        )

        for match in RESIDUAL_PATH.finditer(normalized):
            findings.append({"file": relative, "marker": match.group(0)})
        # Absolute host paths are unambiguous dependencies even in prose; unlike
        # bare names, they must not be hidden by Markdown prose filtering.
        for match in HOST_PATH.finditer(full_normalized):
            findings.append({"file": relative, "marker": match.group(0)})
        if WORKSPACE_COMMAND.search(normalized) or WORKSPACE_MODULE.search(normalized):
            findings.append({"file": relative, "marker": "Workspace CLI invocation"})
        workspace_root = WORKSPACE.as_posix().replace("\\", "/").rstrip("/")
        if workspace_root and re.search(re.escape(workspace_root), full_normalized, re.I):
            findings.append({"file": relative, "marker": "current Workspace root"})
    return findings


def _workspace_dependency(requirement: str) -> bool:
    normalized = requirement.strip().lower().replace("_", "-")
    return bool(
        re.search(r"(?:^|[^a-z0-9])workspace(?:$|[^a-z0-9])", normalized)
        or "project_context" in normalized
        or "workspace_manifest" in normalized
        or "d:/ai/" in normalized
    )


def _markdown_operational_text(text: str) -> list[str]:
    """Return code and path-bearing link targets, excluding ordinary prose."""
    operational: list[str] = []
    fenced = re.compile(r"(?ms)^\s*(```+|~~~+).*?^\s*\1\s*$")
    for match in fenced.finditer(text):
        operational.append(match.group(0))
    without_fences = fenced.sub("", text)
    operational.extend(re.findall(r"`+([^`\n]+)`+", without_fences))
    # Markdown links to local Workspace files are dependencies even when their
    # visible label is explanatory. Ignore ordinary URLs and fragment links.
    for target in re.findall(r"\]\(([^)]+)\)", without_fences):
        target = target.strip().split()[0] if target.strip() else ""
        if not re.match(r"(?i)^(?:https?://|mailto:|#)", target):
            operational.append(target)
    return operational


def canonical(plan: dict[str, Any]) -> str:
    body = dict(plan)
    body.pop("plan_sha256", None)
    return digest(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())


def read_receipt(path: Path) -> dict[str, Any]:
    return (
        json.loads(path.read_text(encoding="utf-8"))
        if path.exists()
        else {"schema_version": SCHEMA, "managed": []}
    )


def resolve_source(args: argparse.Namespace) -> tuple[Path, str]:
    if bool(args.source) == bool(args.skill_id):
        fail("provide exactly one of --skill-id or --source")
    if args.source:
        source = Path(args.source).resolve()
        if os.path.commonpath([str(WORKSPACE), str(source)]) != str(WORKSPACE):
            fail("explicit source must be inside Workspace")
        return source, f"path:{source}"
    manifest = WORKSPACE / "workspace_manifest.yaml"
    if not manifest.exists():
        fail("workspace_manifest.yaml is required for --skill-id")
    data = load_manifest(manifest)
    item = next(
        (
            item
            for item in data.get("skills", [])
            if item.get("id") == args.skill_id and item.get("source_path")
        ),
        None,
    )
    if item is None:
        fail(f"skill id is not registered: {args.skill_id}")
    source = (manifest.parent / item["source_path"]).resolve()
    if os.path.commonpath([str(manifest.parent), str(source)]) != str(manifest.parent):
        fail("registered source escapes Workspace")
    return source, f"workspace:{args.skill_id}"


def load_plan(path: str | Path) -> dict[str, Any]:
    plan = json.loads(Path(path).read_text(encoding="utf-8"))
    if plan.get("plan_sha256") != canonical(plan):
        fail("plan_sha256 does not match plan contents")
    return plan


def plan_contract(plan: dict[str, Any]) -> dict[str, Any]:
    """Return additive contract fields while preserving schema-1.0 plan compatibility."""
    return {
        "portability": plan.get("portability", "legacy-unclassified"),
        "distribution": plan.get("distribution", "legacy-unclassified"),
        "dependency_resolution": plan.get(
            "dependency_resolution",
            {"declared": [], "resolved": {}, "unresolved": []},
        ),
        "residual_scan": plan.get(
            "residual_scan",
            {"status": "NOT_RECORDED", "findings": []},
        ),
    }


def validate_apply_contract(
    plan: dict[str, Any],
    current_contract: dict[str, Any],
    original_files: list[tuple[str, bytes]] | None = None,
) -> None:
    """Enforce the current source contract even for legacy schema-1.0 plans."""
    portability = current_contract["portability"]
    distribution = current_contract["distribution"]
    requires = current_contract["requires"]
    if distribution == "internal-only":
        fail("internal-only skill distribution forbids external publication")
    if "portability" in plan and plan["portability"] != portability:
        fail("plan portability no longer matches the current source contract")
    if "distribution" in plan and plan["distribution"] != distribution:
        fail("plan distribution no longer matches the current source contract")
    resolution = plan.get("dependency_resolution")
    if portability in {"host-adapted", "workspace-bound"}:
        if not isinstance(resolution, dict):
            fail(f"legacy plan lacks dependency evidence required for {portability} publication")
        if resolution.get("declared") != requires:
            fail("plan dependency declarations no longer match the current source contract")
        resolved = resolution.get("resolved")
        unresolved = resolution.get("unresolved")
        if (
            not isinstance(resolved, dict)
            or set(resolved) != set(requires)
            or unresolved
            or any(not isinstance(value, str) or not value.strip() for value in resolved.values())
        ):
            fail(f"{portability} plan contains unresolved source dependencies")
    recorded_scan = plan.get("residual_scan")
    payload = plan.get("payload")
    if recorded_scan is not None:
        if (
            not isinstance(recorded_scan, dict)
            or not isinstance(payload, dict)
            or not all(
                isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
            )
        ):
            fail("plan residual scan or payload is invalid")
        current_findings = residual_scan({key: value.encode() for key, value in payload.items()})
        expected_status = "PASS" if not current_findings else "WARNING"
        if (
            recorded_scan.get("findings") != current_findings
            or recorded_scan.get("status") != expected_status
        ):
            fail("plan residual scan no longer matches rendered payload")
    if portability == "workspace-bound":
        if not isinstance(recorded_scan, dict) or recorded_scan.get("findings"):
            fail("workspace-bound plan lacks a clean residual Workspace scan")
        if not isinstance(payload, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
        ):
            fail("workspace-bound plan payload is invalid")
        if residual_scan({key: value.encode() for key, value in payload.items()}):
            fail("workspace-bound plan still contains residual Workspace dependencies")
        if original_files is not None:
            rendered = {key: value.encode() for key, value in payload.items()}
            evidence = adaptation_evidence(original_files, rendered)
            if not evidence:
                fail("workspace-bound publication requires verifiable content adaptations")
            recorded = plan.get("dependency_resolution", {}).get("evidence")
            if recorded is not None and recorded != evidence:
                fail(
                    "dependency adaptation evidence does not match the source and rendered payload"
                )


def adaptation_evidence(
    files: list[tuple[str, bytes]], rendered: dict[str, bytes]
) -> list[dict[str, str]]:
    return [
        {
            "file": relative,
            "source_sha256": digest(data),
            "rendered_sha256": digest(rendered[relative]),
        }
        for relative, data in files
        if data != rendered.get(relative, data)
    ]


def make_plan(args: argparse.Namespace) -> dict[str, Any]:
    project = git_root(args.project_root)
    target = safe_target(project, args.target_root)
    source, source_id = resolve_source(args)
    files = source_files(source)
    contract = skill_contract(files)
    if contract["distribution"] == "internal-only":
        fail("internal-only skill distribution forbids external publication")
    rendered = {relative: data for relative, data in files}
    adaptations: list[dict[str, str]] = []
    for item in args.replace or []:
        try:
            relative, old, new = item.split("=", 2)
        except ValueError as exc:
            raise AdaptError("--replace must be FILE=OLD=NEW") from exc
        text = rendered.get(relative, b"").decode("utf-8")
        if text.count(old) != 1:
            fail(f"replacement must match exactly once: {relative}")
        rendered[relative] = text.replace(old, new, 1).encode()
        adaptations.append({"file": relative, "old": old, "new": new})
    resolutions = dependency_resolutions(args.resolve_dependency)
    unknown = sorted(set(resolutions) - set(contract["requires"]))
    if unknown:
        fail("dependency resolution names are not declared: " + ", ".join(unknown))
    unresolved = [item for item in contract["requires"] if item not in resolutions]
    residuals = residual_scan(rendered)
    if contract["portability"] == "host-adapted" and unresolved:
        fail(
            "host-adapted publication requires handling for every dependency: "
            + ", ".join(unresolved)
        )
    if contract["portability"] == "workspace-bound" and (unresolved or residuals):
        details = []
        if unresolved:
            details.append("unresolved dependencies: " + ", ".join(unresolved))
        if residuals:
            details.append("residual Workspace markers remain")
        fail("workspace-bound skill cannot be published verbatim; " + "; ".join(details))
    evidence = adaptation_evidence(files, rendered)
    if contract["portability"] == "workspace-bound" and not evidence:
        fail("workspace-bound publication requires verifiable content adaptations")
    receipt = read_receipt(project / RECEIPT)
    existing = next(
        (
            item
            for item in receipt["managed"]
            if item["source_id"] == source_id and item["target_root"] == args.target_root
        ),
        None,
    )
    if args.mode == "update" and existing is None:
        fail("update requires an existing managed receipt entry")
    entries: list[dict[str, Any]] = []
    for relative, data in files:
        path = target / relative
        current = path.read_bytes() if path.exists() and path.is_file() else None
        old = (
            next(
                (item["rendered_sha256"] for item in existing["files"] if item["path"] == relative),
                None,
            )
            if existing
            else None
        )
        if current is not None and old != digest(current):
            fail(f"target collision or local modification: {args.target_root}/{relative}")
        entries.append(
            {
                "path": relative,
                "source_sha256": digest(data),
                "rendered_sha256": digest(rendered[relative]),
                "bytes": len(rendered[relative]),
            }
        )
    plan = {
        "schema_version": SCHEMA,
        "mode": args.mode,
        "source": {
            "id": source_id,
            "path": str(source),
            "source_sha256": digest(
                json.dumps([(r, digest(d)) for r, d in files], separators=(",", ":")).encode()
            ),
        },
        "target": {"project_root": str(project), "target_root": args.target_root},
        "portability": contract["portability"],
        "distribution": contract["distribution"],
        "dependency_resolution": {
            "declared": contract["requires"],
            "resolved": resolutions,
            "unresolved": unresolved,
            "evidence": evidence,
        },
        "residual_scan": {"status": "PASS" if not residuals else "WARNING", "findings": residuals},
        "adaptations": adaptations,
        "files": entries,
        "payload": {relative: rendered[relative].decode() for relative, _ in files},
    }
    plan["plan_sha256"] = canonical(plan)
    return plan


def apply_plan(args: argparse.Namespace) -> None:
    if not args.record_id:
        fail("apply requires an active external-origin workspace_write --record-id")
    lease = getattr(args, "lease", None)
    if not lease:
        fail("apply requires a valid --lease covering both external write paths")
    plan = load_plan(args.plan)
    project = Path(plan["target"]["project_root"]).resolve()
    workspace_cli = [sys.executable, "-B", "-m", "scripts.workspace.workspace_cli"]
    try:
        subprocess.run(
            workspace_cli
            + [
                "records",
                "require",
                args.record_id,
                "--operation",
                "workspace_write",
                "--external-client-root",
                str(project),
                "--agent",
                args.agent,
            ],
            cwd=WORKSPACE,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AdaptError(
            "record-id is not an active workspace_write registration for this external project"
        ) from exc
    contract = plan_contract(plan)
    source_files_now = source_files(Path(plan["source"]["path"]))
    validate_apply_contract(plan, skill_contract(source_files_now), source_files_now)
    project = git_root(project)
    target = safe_target(project, plan["target"]["target_root"])
    receipt_path = project / RECEIPT
    receipt = read_receipt(receipt_path)
    lease_args = ["--lease", lease]
    try:
        for write_path in (target, receipt_path):
            subprocess.run(
                workspace_cli
                + [
                    "agent",
                    "check",
                    "--agent",
                    args.agent,
                    "--operation",
                    "write",
                    "--path",
                    str(write_path),
                    "--record-id",
                    args.record_id,
                    "--external-client-root",
                    str(project),
                ]
                + lease_args,
                cwd=WORKSPACE,
                check=True,
                capture_output=True,
                text=True,
            )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AdaptError("agent is not authorized to write the external target") from exc
    if [(relative, digest(data)) for relative, data in source_files_now] != [
        (item["path"], item["source_sha256"]) for item in plan["files"]
    ]:
        fail("source changed after plan; regenerate the plan")
    if set(plan["payload"]) != {item["path"] for item in plan["files"]}:
        fail("rendered payload paths do not match planned files")
    for item in plan["files"]:
        data = plan["payload"][item["path"]].encode()
        if digest(data) != item["rendered_sha256"] or len(data) != item["bytes"]:
            fail("rendered payload does not match planned file hashes")
    entry = next(
        (
            item
            for item in receipt["managed"]
            if item["source_id"] == plan["source"]["id"]
            and item["target_root"] == plan["target"]["target_root"]
        ),
        None,
    )
    if plan["mode"] == "update" and entry is None:
        fail("receipt entry disappeared before apply")
    for item in plan["files"]:
        path = target / item["path"]
        old = (
            next(
                (
                    file["rendered_sha256"]
                    for file in entry["files"]
                    if file["path"] == item["path"]
                ),
                None,
            )
            if entry
            else None
        )
        if path.exists() and old != digest(path.read_bytes()):
            fail(f"target collision or local modification: {path}")
    target.mkdir(parents=True, exist_ok=True)
    for item in plan["files"]:
        path = target / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(plan["payload"][item["path"]].encode())
        os.replace(temporary, path)
    new_entry = {
        "source_id": plan["source"]["id"],
        "source_revision": None,
        "source_sha256": plan["source"]["source_sha256"],
        "target_root": plan["target"]["target_root"],
        **contract,
        "files": plan["files"],
        "adaptations": plan["adaptations"],
        "plan_sha256": plan["plan_sha256"],
    }
    receipt["managed"] = [
        item
        for item in receipt["managed"]
        if not (
            item["source_id"] == new_entry["source_id"]
            and item["target_root"] == new_entry["target_root"]
        )
    ] + [new_entry]
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".manifest.", dir=receipt_path.parent)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(temporary, receipt_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--project-root", required=True)
    plan.add_argument("--target-root", required=True)
    plan.add_argument("--source")
    plan.add_argument("--skill-id")
    plan.add_argument("--mode", choices=["publish", "update"], default="publish")
    plan.add_argument("--replace", action="append")
    plan.add_argument("--resolve-dependency", action="append")
    plan.add_argument("--output", required=True)
    apply = subparsers.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--record-id", required=True)
    apply.add_argument("--agent", default="codex")
    apply.add_argument("--lease", help="Existing scoped capability lease for the external target")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "plan":
            result = make_plan(args)
            Path(args.output).write_text(
                json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(json.dumps({"status": "planned", "plan_sha256": result["plan_sha256"]}))
        else:
            apply_plan(args)
            print(json.dumps({"status": "applied", "plan": args.plan}))
        return 0
    except (AdaptError, OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
