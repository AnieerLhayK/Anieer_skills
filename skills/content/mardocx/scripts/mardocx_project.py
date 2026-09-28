from __future__ import annotations

from pathlib import Path

from mardocx_errors import MardocxError


def resolve_project_root(markdown: Path | None, explicit_root: str | None) -> Path:
    if explicit_root:
        root = Path(explicit_root).expanduser().resolve()
        if not root.is_dir():
            raise MardocxError(f"Project root is not a directory: {root}")
        return root
    if markdown is None:
        return Path.cwd().resolve()
    source_dir = markdown.expanduser().resolve().parent
    cursor = source_dir
    while True:
        if (cursor / "mardocx.yaml").exists() or (cursor / "reference.docx").exists():
            return cursor
        if cursor.parent == cursor:
            return source_dir
        cursor = cursor.parent
