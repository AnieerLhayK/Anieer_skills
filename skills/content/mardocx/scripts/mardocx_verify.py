from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.shared import Cm

from mardocx_errors import MardocxError
from mardocx_reference import REQUIRED_STYLES, validate_reference


def validate_output(
    output_path: Path,
    config: dict,
    heading_levels: list[int],
    resized_widths: list[str],
) -> None:
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise MardocxError(f"Pandoc did not produce a DOCX at {output_path}.")
    validate_reference(output_path, config)
    try:
        document = Document(output_path)
    except Exception as exc:
        raise MardocxError(f"Generated DOCX cannot be opened: {exc}") from exc
    paragraph_styles = {paragraph.style.name for paragraph in document.paragraphs}
    for level in sorted({level for level in heading_levels if level <= 3}):
        expected = f"Heading {level}"
        if expected not in paragraph_styles:
            raise MardocxError(f"Generated DOCX is missing mapped paragraphs for {expected}.")
    if resized_widths and "Image Caption" not in paragraph_styles:
        raise MardocxError("Generated DOCX is missing mapped Image Caption paragraphs.")
    if resized_widths and len(document.inline_shapes) < len(resized_widths):
        raise MardocxError("Generated DOCX is missing one or more locally sized images.")
    expected_widths = [Cm(float(width.removesuffix("cm"))) for width in resized_widths]
    for actual, expected in zip(document.inline_shapes, expected_widths):
        if abs(actual.width - expected) > 2:
            raise MardocxError("Generated DOCX image width does not match the configured Mardocx width.")
