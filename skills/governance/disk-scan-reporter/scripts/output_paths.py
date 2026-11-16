"""Resolve disk-scan-reporter runtime paths from the Workspace manifest."""

from __future__ import annotations

import os
import importlib.util
import json
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = SKILL_ROOT.parents[2]
WORKSPACE_MANIFEST = WORKSPACE_ROOT / "workspace_manifest.yaml"


def _load_manifest_loader():
    """Load the Workspace loader without colliding with this skill's `scripts` package."""
    loader_path = WORKSPACE_ROOT / "scripts" / "workspace" / "manifest_loader.py"
    spec = importlib.util.spec_from_file_location("workspace_manifest_loader", loader_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Workspace manifest loader is unavailable: {loader_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_manifest


try:
    load_manifest = _load_manifest_loader()
except (ImportError, OSError):  # standalone copies without Workspace runtime
    load_manifest = None


def _read_manifest(manifest_path: Path) -> dict[str, object]:
    if load_manifest is not None:
        try:
            return load_manifest(manifest_path)
        except (OSError, ValueError) as exc:
            raise ValueError(f"Workspace manifest is unavailable: {exc}") from exc
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Workspace manifest is unavailable: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Workspace manifest must contain an object")
    return payload


def workspace_governance_root(manifest_path: Path = WORKSPACE_MANIFEST) -> Path:
    """Return the explicitly registered external Workspace governance root."""
    manifest = _read_manifest(manifest_path)
    runtime_roots = manifest.get("runtime_roots")
    value = runtime_roots.get("workspace_governance") if isinstance(runtime_roots, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("workspace_manifest.yaml must define runtime_roots.workspace_governance")
    expanded = Path(os.path.expandvars(os.path.expanduser(value)))
    if not expanded.is_absolute():
        raise ValueError("runtime_roots.workspace_governance must be an absolute path")
    return expanded.resolve()


def disk_scan_data_root(manifest_path: Path = WORKSPACE_MANIFEST) -> Path:
    return workspace_governance_root(manifest_path) / "disk-scan-reporter"


def default_config_path(manifest_path: Path = WORKSPACE_MANIFEST) -> Path:
    return disk_scan_data_root(manifest_path) / "config" / "scan_config.json"


def default_audit_policy_path(manifest_path: Path = WORKSPACE_MANIFEST) -> Path:
    return disk_scan_data_root(manifest_path) / "config" / "audit_policy.json"


def default_output_root(manifest_path: Path = WORKSPACE_MANIFEST) -> Path:
    """The durable report directory is external to the Workspace source tree."""
    return disk_scan_data_root(manifest_path) / "reports"
