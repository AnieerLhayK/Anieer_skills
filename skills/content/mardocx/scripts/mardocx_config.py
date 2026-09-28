from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml

from mardocx_errors import MardocxError


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MardocxError(f"{label} must be a YAML mapping.")
    return value


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if key not in merged:
            raise MardocxError(f"Unknown mardocx.yaml setting: {key}")
        if isinstance(value, dict) and isinstance(merged[key], dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _require_number(value: Any, label: str, positive: bool = True) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or (positive and value <= 0):
        qualifier = "a positive number" if positive else "a number"
        raise MardocxError(f"{label} must be {qualifier}.")


def validate_config(config: dict[str, Any]) -> None:
    typography = _mapping(config.get("typography"), "typography")
    body = _mapping(typography.get("body"), "typography.body")
    headings = _mapping(typography.get("headings"), "typography.headings")
    images = _mapping(config.get("images"), "images")
    caption = _mapping(images.get("caption"), "images.caption")
    for label, section in (("typography.body", body), ("images.caption", caption)):
        if not isinstance(section.get("font"), str) or not section["font"].strip():
            raise MardocxError(f"{label}.font must be a non-empty string.")
        _require_number(section.get("size_pt"), f"{label}.size_pt")
    _require_number(body.get("line_spacing"), "typography.body.line_spacing")
    for level in ("1", "2", "3"):
        heading = _mapping(headings.get(level), f"typography.headings.{level}")
        if not isinstance(heading.get("font"), str) or not heading["font"].strip():
            raise MardocxError(f"typography.headings.{level}.font must be a non-empty string.")
        _require_number(heading.get("size_pt"), f"typography.headings.{level}.size_pt")
        if not isinstance(heading.get("bold"), bool):
            raise MardocxError(f"typography.headings.{level}.bold must be true or false.")
    _require_number(images.get("landscape_width_cm"), "images.landscape_width_cm")
    _require_number(images.get("portrait_width_cm"), "images.portrait_width_cm")
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(caption.get("color", ""))):
        raise MardocxError("images.caption.color must be a #RRGGBB value.")
    if caption.get("alignment") != "center":
        raise MardocxError("images.caption.alignment currently supports only 'center'.")


def load_config(skill_dir: Path, project_root: Path) -> dict[str, Any]:
    defaults_path = skill_dir / "assets" / "defaults.yaml"
    try:
        defaults = _mapping(yaml.safe_load(defaults_path.read_text(encoding="utf-8")), "defaults.yaml")
    except OSError as exc:
        raise MardocxError(f"Cannot read bundled defaults: {exc}") from exc
    config_path = project_root / "mardocx.yaml"
    if config_path.exists():
        try:
            override = _mapping(yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}, "mardocx.yaml")
        except yaml.YAMLError as exc:
            raise MardocxError(f"Invalid mardocx.yaml: {exc}") from exc
        defaults = _merge(defaults, override)
    validate_config(defaults)
    return defaults
