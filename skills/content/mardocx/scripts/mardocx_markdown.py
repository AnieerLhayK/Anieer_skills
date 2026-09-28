from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image


HEADING = re.compile(r"^(?P<indent>[ ]{0,3})(?P<marks>#{1,6})[ \t]+(?P<title>\S.*?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})")
IMAGE = re.compile(r"!\[([^\]]*)\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)(?!\{)")
MALFORMED_CURVED_QUOTES = re.compile(r"”[^“”]*”")


def heading_warnings(markdown_path: Path) -> tuple[list[str], list[int]]:
    warnings: list[str] = []
    levels: list[int] = []
    in_fence: str | None = None
    previous: int | None = None
    for line_number, line in enumerate(markdown_path.read_text(encoding="utf-8").splitlines(), start=1):
        fence = FENCE.match(line)
        if fence:
            marker = fence.group(1)[0]
            if in_fence is None:
                in_fence = marker
            elif marker == in_fence:
                in_fence = None
            continue
        if in_fence is not None:
            continue
        match = HEADING.match(line)
        if not match:
            continue
        level = len(match.group("marks"))
        levels.append(level)
        if previous is None and level != 1:
            warnings.append(f"{markdown_path}:{line_number}: first heading is H{level}, not H1")
        if previous is not None and level > previous + 1:
            warnings.append(f"{markdown_path}:{line_number}: heading jumps from H{previous} to H{level}")
        if level > 3:
            warnings.append(f"{markdown_path}:{line_number}: H{level} has no Mardocx style configuration")
        previous = level
    return warnings, levels


def quote_warnings(markdown_path: Path) -> list[str]:
    """Report likely Chinese quotations that start and end with a right quote.

    Source punctuation is intentionally never rewritten: quoted text can be
    intentional, while an explicit warning gives the author a precise repair
    location before conversion.
    """
    warnings: list[str] = []
    in_fence: str | None = None
    for line_number, line in enumerate(markdown_path.read_text(encoding="utf-8").splitlines(), start=1):
        fence = FENCE.match(line)
        if fence:
            marker = fence.group(1)[0]
            if in_fence is None:
                in_fence = marker
            elif marker == in_fence:
                in_fence = None
            continue
        if in_fence is None and MALFORMED_CURVED_QUOTES.search(line):
            warnings.append(f"{markdown_path}:{line_number}: possible double-right quotation mark; use “…” for Chinese quotes")
    return warnings


def _is_remote(target: str) -> bool:
    return urlparse(target).scheme.lower() in {"http", "https"}


def _image_width(target: str, source_dir: Path, config: dict) -> tuple[str | None, str | None]:
    if _is_remote(target):
        return None, f"remote image retained without sizing: {target}"
    local = Path(unquote(target))
    if not local.is_absolute():
        local = source_dir / local
    try:
        with Image.open(local) as image:
            width, height = image.size
    except (OSError, ValueError) as exc:
        return None, f"local image retained without sizing ({exc}): {target}"
    image_config = config["images"]
    centimeters = image_config["landscape_width_cm"] if width >= height else image_config["portrait_width_cm"]
    return f"{centimeters:g}cm", None


def prepare_images(markdown_path: Path, destination: Path, config: dict) -> list[str]:
    warnings: list[str] = []
    in_fence: str | None = None
    result: list[str] = []
    for line in markdown_path.read_text(encoding="utf-8").splitlines(keepends=True):
        fence = FENCE.match(line)
        if fence:
            marker = fence.group(1)[0]
            if in_fence is None:
                in_fence = marker
            elif marker == in_fence:
                in_fence = None
            result.append(line)
            continue
        if in_fence is not None:
            result.append(line)
            continue

        def replace(match: re.Match[str]) -> str:
            width, warning = _image_width(match.group(2), markdown_path.parent, config)
            if warning:
                warnings.append(f"{markdown_path}: {warning}")
                return match.group(0)
            return f"![{match.group(1)}]({match.group(2)}){{width={width}}}"

        result.append(IMAGE.sub(replace, line))
    destination.write_text("".join(result), encoding="utf-8")
    return warnings
