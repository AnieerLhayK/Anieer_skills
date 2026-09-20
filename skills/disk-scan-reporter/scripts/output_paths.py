"""Resolve report output roots without depending on the caller's working directory."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Mapping


SKILL_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_MANIFEST = SKILL_ROOT.parents[1] / "workspace_manifest.yaml"


def workspace_staging_root(manifest_path: Path = WORKSPACE_MANIFEST) -> Path | None:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    value = manifest.get("runtime_roots", {}).get("staging")
    return Path(os.path.expandvars(str(value))).resolve() if value else None


def default_output_root(
    *,
    environment: Mapping[str, str] | None = None,
    manifest_path: Path = WORKSPACE_MANIFEST,
    temp_root: Path | None = None,
) -> Path:
    active_environment = os.environ if environment is None else environment
    configured = active_environment.get("AI_TOOL_STAGING_DIR", "").strip()
    staging = Path(os.path.expandvars(configured)).resolve() if configured else None
    staging = staging or workspace_staging_root(manifest_path)
    staging = staging or Path(temp_root or tempfile.gettempdir()).resolve()
    return staging / "disk-scan-reporter"
