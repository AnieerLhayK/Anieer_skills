from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from mardocx_errors import MardocxError
from mardocx_markdown import heading_warnings, prepare_images, quote_warnings
from mardocx_reference import create_reference, find_pandoc
from mardocx_verify import validate_output


def _resized_widths(markdown_path: Path, config: dict) -> list[str]:
    # The transformed source contains width attributes; only valid local images are counted during output validation.
    from mardocx_markdown import IMAGE, _image_width

    widths: list[str] = []
    for match in IMAGE.finditer(markdown_path.read_text(encoding="utf-8")):
        width, _ = _image_width(match.group(2), markdown_path.parent, config)
        if width:
            widths.append(width)
    return widths


def convert(markdown_path: Path, project_root: Path, output_path: Path, config: dict) -> list[str]:
    if not markdown_path.is_file():
        raise MardocxError(f"Markdown input does not exist: {markdown_path}")
    reference_path = project_root / "reference.docx"
    if not reference_path.exists():
        create_reference(reference_path, config)
    heading_messages, heading_levels = heading_warnings(markdown_path)
    punctuation_messages = quote_warnings(markdown_path)
    with tempfile.TemporaryDirectory(prefix="mardocx-") as temporary_directory:
        temporary_source = Path(temporary_directory) / markdown_path.name
        image_messages = prepare_images(markdown_path, temporary_source, config)
        command = [
            find_pandoc(),
            "--from=markdown+east_asian_line_breaks+smart",
            f"--reference-doc={reference_path}",
            f"--resource-path={markdown_path.parent}",
            "--output",
            str(output_path),
            str(temporary_source),
        ]
        result = subprocess.run(command, cwd=project_root, text=True, capture_output=True)
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise MardocxError(f"Pandoc conversion failed: {detail}")
    validate_output(output_path, config, heading_levels, _resized_widths(markdown_path, config))
    return heading_messages + punctuation_messages + image_messages
