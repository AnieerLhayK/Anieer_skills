"""Resolve report output roots without depending on the caller's working directory."""

from __future__ import annotations

import os
import tempfile
import importlib.util
import json
import re
from pathlib import Path
from typing import Mapping


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


def workspace_staging_root(manifest_path: Path = WORKSPACE_MANIFEST) -> Path | None:
    manifest = None
    if load_manifest is not None:
        try:
            manifest = load_manifest(manifest_path)
        except (OSError, ValueError):
            pass
    if manifest is None:
        manifest = _load_staging_manifest(manifest_path)
    value = manifest.get("runtime_roots", {}).get("staging")
    return Path(os.path.expandvars(str(value))).resolve() if value else None


def _load_staging_manifest(manifest_path: Path) -> dict[str, object]:
    """Read the one optional host setting this standalone skill needs."""
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        in_runtime_roots = False
        for line in text.splitlines():
            if line and not line[0].isspace():
                in_runtime_roots = line.strip() == "runtime_roots:"
                continue
            if in_runtime_roots:
                match = re.fullmatch(r"\s+staging:\s*(.*?)\s*", line)
                if match:
                    value = _yaml_scalar(match.group(1))
                    if value is None:
                        return {}
                    return {"runtime_roots": {"staging": value}}
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _yaml_scalar(raw: str) -> str | None:
    """Read a plain or quoted YAML scalar with an optional trailing comment."""
    value = raw.strip()
    if value.startswith("'"):
        chars: list[str] = []
        index = 1
        while index < len(value):
            if value[index] == "'":
                if index + 1 < len(value) and value[index + 1] == "'":
                    chars.append("'")
                    index += 2
                    continue
                trailing = value[index + 1 :].strip()
                return "".join(chars) if not trailing or trailing.startswith("#") else None
            chars.append(value[index])
            index += 1
        return None
    if value.startswith('"'):
        try:
            decoded, end = json.JSONDecoder().raw_decode(value)
        except (json.JSONDecodeError, TypeError):
            return None
        trailing = value[end:].strip()
        return decoded if isinstance(decoded, str) and (not trailing or trailing.startswith("#")) else None
    return re.split(r"\s+#", value, maxsplit=1)[0].rstrip()


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
