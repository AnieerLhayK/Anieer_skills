"""Initialize or migrate the external disk-scan-reporter configuration."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.audit_guard import DEFAULT_POLICY_PATH, load_audit_policy
    from scripts.disk_scan_schema import load_config
    from scripts.output_paths import default_audit_policy_path, default_config_path
except ModuleNotFoundError:
    from audit_guard import DEFAULT_POLICY_PATH, load_audit_policy
    from disk_scan_schema import load_config
    from output_paths import default_audit_policy_path, default_config_path


SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
SCAN_TEMPLATE = SKILL_ROOT / "config" / "scan_config.example.json"
POLICY_TEMPLATE = DEFAULT_POLICY_PATH
SOURCE_SCAN_CONFIG = SKILL_ROOT / "config" / "scan_config.json"
SOURCE_AUDIT_POLICY = SKILL_ROOT / "config" / "audit_policy.json"


def _read_json(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _create_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)


def require_external_write_authority(
    paths: tuple[Path, ...], *, record_id: str | None, lease: Path | None
) -> None:
    if not record_id or lease is None:
        raise ValueError("external writes require --record-id and --lease")
    for path in paths:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "scripts.workspace.workspace_cli",
                "agent",
                "check",
                "--agent",
                "codex",
                "--operation",
                "write",
                "--path",
                str(path),
                "--record-id",
                record_id,
                "--lease",
                str(lease),
            ],
            cwd=WORKSPACE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stdout or result.stderr).strip()
            raise PermissionError(f"external write check denied for {path}: {detail}")


def initialize(
    *,
    migrate_current: bool = False,
    record_id: str | None = None,
    lease: Path | None = None,
) -> tuple[Path, Path]:
    scan_target = default_config_path()
    policy_target = default_audit_policy_path()
    if scan_target.exists() or policy_target.exists():
        raise FileExistsError(
            "External configuration already exists; nothing was overwritten: "
            f"{scan_target} ; {policy_target}"
        )

    if migrate_current:
        if not SOURCE_SCAN_CONFIG.is_file():
            raise FileNotFoundError(
                "Current in-workspace configuration is unavailable for migration. "
                "Use the default initializer to copy the generic templates."
            )
        scan_payload = load_config(SOURCE_SCAN_CONFIG)
        policy_source = SOURCE_AUDIT_POLICY if SOURCE_AUDIT_POLICY.is_file() else POLICY_TEMPLATE
        policy_payload = load_audit_policy(policy_source)
        if policy_payload != load_audit_policy(POLICY_TEMPLATE):
            raise ValueError("Current audit policy differs from the reviewed template")
        if scan_payload.get("audit_policy") != "audit_policy.json":
            raise ValueError("Current scan config must reference audit_policy.json")
        scan_bytes = SOURCE_SCAN_CONFIG.read_bytes()
        policy_bytes = POLICY_TEMPLATE.read_bytes()
    else:
        scan_bytes = SCAN_TEMPLATE.read_bytes()
        policy_bytes = POLICY_TEMPLATE.read_bytes()
        load_config(SCAN_TEMPLATE)
        load_audit_policy(POLICY_TEMPLATE)

    require_external_write_authority(
        (scan_target, policy_target), record_id=record_id, lease=lease
    )
    scan_target.parent.mkdir(parents=True, exist_ok=True)
    _create_exclusive(scan_target, scan_bytes)
    _create_exclusive(policy_target, policy_bytes)

    if _read_json(scan_target).get("audit_policy") != policy_target.name:
        raise ValueError("Initialized scan config does not reference the active audit policy")
    if load_audit_policy(policy_target) != load_audit_policy(POLICY_TEMPLATE):
        raise ValueError("Initialized audit policy does not match the reviewed template")
    return scan_target, policy_target


def sync_audit_policy(*, record_id: str | None = None, lease: Path | None = None) -> Path:
    target = default_audit_policy_path()
    template = load_audit_policy(POLICY_TEMPLATE)
    active = load_audit_policy(target)
    if active == template:
        print("Active audit policy already matches its reviewed template.")
        return target
    print(f"This will replace the active policy at: {target}")
    confirmation = input("Type SYNC-AUDIT-POLICY to confirm: ")
    if confirmation != "SYNC-AUDIT-POLICY":
        raise RuntimeError("Policy synchronization cancelled")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = target.with_name(f"{target.stem}.backup-{timestamp}{target.suffix}")
    require_external_write_authority(
        (target, backup), record_id=record_id, lease=lease
    )
    original_bytes = target.read_bytes()
    template_bytes = POLICY_TEMPLATE.read_bytes()
    _create_exclusive(backup, original_bytes)
    if backup.read_bytes() != original_bytes:
        raise OSError(f"policy backup verification failed: {backup}")
    try:
        target.write_bytes(template_bytes)
        if target.read_bytes() != template_bytes:
            raise OSError(f"policy update verification failed: {target}")
    except OSError as update_error:
        try:
            target.write_bytes(original_bytes)
            if target.read_bytes() != original_bytes:
                raise OSError("restored policy did not match its verified backup")
        except OSError as rollback_error:
            raise RuntimeError(
                f"policy update and rollback failed; verified backup remains at {backup}: "
                f"{rollback_error}"
            ) from update_error
        raise
    print(f"Verified rollback copy: {backup}")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--migrate-current",
        action="store_true",
        help="copy current in-workspace config without changing its source files",
    )
    modes.add_argument(
        "--sync-audit-policy",
        action="store_true",
        help="update the active external policy after explicit confirmation",
    )
    parser.add_argument("--record-id", help="active external_write TASK record ID")
    parser.add_argument("--lease", type=Path, help="validated external_write lease file")
    args = parser.parse_args()
    try:
        if args.sync_audit_policy:
            print(sync_audit_policy(record_id=args.record_id, lease=args.lease))
        else:
            scan, policy = initialize(
                migrate_current=args.migrate_current,
                record_id=args.record_id,
                lease=args.lease,
            )
            print(f"Scan config: {scan}")
            print(f"Audit policy: {policy}")
            print("Source files were preserved; verify these copies before removing them from the Workspace.")
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"ERROR: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
