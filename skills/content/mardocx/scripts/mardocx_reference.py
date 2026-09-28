from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from mardocx_errors import MardocxError


REQUIRED_STYLES = ("Normal", "Heading 1", "Heading 2", "Heading 3", "Image Caption")


def find_pandoc() -> str:
    executable = os.environ.get("PANDOC_PATH") or shutil.which("pandoc")
    if not executable:
        raise MardocxError("Pandoc was not found. Install Pandoc or set PANDOC_PATH.")
    return executable


def _atomic_replace(source: Path, destination: Path) -> None:
    source.replace(destination)


def _set_font(style, name: str, size_pt: float, bold: bool | None = None) -> None:
    font = style.font
    font.name = name
    font.size = Pt(size_pt)
    if bold is not None:
        font.bold = bold
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.rFonts
    if rfonts is None:
        rfonts = rpr._add_rFonts()
    for key in ("ascii", "hAnsi", "eastAsia", "cs"):
        rfonts.set(qn(f"w:{key}"), name)


def _paragraph_style(document: Document, name: str):
    try:
        return document.styles[name]
    except KeyError:
        return document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)


def apply_styles(reference_path: Path, config: dict) -> None:
    document = Document(reference_path)
    body = config["typography"]["body"]
    normal = _paragraph_style(document, "Normal")
    _set_font(normal, body["font"], body["size_pt"])
    normal.paragraph_format.line_spacing = body["line_spacing"]
    for level in ("1", "2", "3"):
        heading = config["typography"]["headings"][level]
        _set_font(_paragraph_style(document, f"Heading {level}"), heading["font"], heading["size_pt"], heading["bold"])
    caption = config["images"]["caption"]
    image_caption = _paragraph_style(document, "Image Caption")
    _set_font(image_caption, caption["font"], caption["size_pt"])
    image_caption.font.color.rgb = RGBColor.from_string(caption["color"][1:])
    image_caption.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.save(reference_path)


def validate_reference(reference_path: Path, config: dict) -> None:
    try:
        document = Document(reference_path)
    except Exception as exc:  # python-docx reports several package exceptions
        raise MardocxError(f"reference.docx cannot be opened: {exc}") from exc
    for name in REQUIRED_STYLES:
        try:
            style = document.styles[name]
        except KeyError as exc:
            raise MardocxError(f"reference.docx is missing style '{name}'.") from exc
        rfonts = style.element.rPr.rFonts if style.element.rPr is not None else None
        if rfonts is None or rfonts.get(qn("w:eastAsia")) is None:
            raise MardocxError(f"Style '{name}' has no East Asian font definition.")
    if round(document.styles["Normal"].font.size.pt, 2) != round(config["typography"]["body"]["size_pt"], 2):
        raise MardocxError("Normal style size does not match mardocx.yaml.")


def create_reference(reference_path: Path, config: dict) -> None:
    pandoc = find_pandoc()
    result = subprocess.run([pandoc, "--print-default-data-file=reference.docx"], capture_output=True)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise MardocxError(f"Pandoc could not create its default reference.docx: {detail}")
    with tempfile.NamedTemporaryFile(prefix="mardocx-reference-", suffix=".docx", dir=reference_path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(result.stdout)
    try:
        apply_styles(temporary, config)
        validate_reference(temporary, config)
        _atomic_replace(temporary, reference_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def update_reference(reference_path: Path, config: dict) -> None:
    if not reference_path.exists():
        create_reference(reference_path, config)
        return
    with tempfile.NamedTemporaryFile(prefix="mardocx-reference-", suffix=".docx", dir=reference_path.parent, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copy2(reference_path, temporary)
        apply_styles(temporary, config)
        validate_reference(temporary, config)
        _atomic_replace(temporary, reference_path)
    finally:
        if temporary.exists():
            temporary.unlink()
