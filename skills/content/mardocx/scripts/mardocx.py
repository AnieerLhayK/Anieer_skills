from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True

from mardocx_config import load_config
from mardocx_convert import convert
from mardocx_errors import MardocxError
from mardocx_markdown import heading_warnings, quote_warnings
from mardocx_project import resolve_project_root
from mardocx_reference import update_reference


SKILL_DIR = Path(__file__).resolve().parent.parent


def _source(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _emit_warnings(warnings: list[str]) -> None:
    for warning in warnings:
        print(f"WARNING: {warning}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Project-scoped Markdown to DOCX conversion with reference.docx.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    check = subcommands.add_parser("check", help="Report heading warnings without converting.")
    check.add_argument("input", help="Markdown input path")
    check.add_argument("--project-root")
    conversion = subcommands.add_parser("convert", help="Convert Markdown with the project reference.docx.")
    conversion.add_argument("input", help="Markdown input path")
    conversion.add_argument("--project-root")
    conversion.add_argument("--output", help="DOCX output path; defaults beside the Markdown input")
    conversion.add_argument("--overwrite", action="store_true", help="Allow replacement of an existing output DOCX")
    update = subcommands.add_parser("update-reference", help="Apply mardocx.yaml to the project reference.docx.")
    update.add_argument("--project-root")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "update-reference":
            root = resolve_project_root(None, arguments.project_root)
            update_reference(root / "reference.docx", load_config(SKILL_DIR, root))
            print(f"Updated {root / 'reference.docx'}")
            return 0
        source = _source(arguments.input)
        root = resolve_project_root(source, arguments.project_root)
        if arguments.command == "check":
            if not source.is_file():
                raise MardocxError(f"Markdown input does not exist: {source}")
            heading_messages, _ = heading_warnings(source)
            _emit_warnings(heading_messages + quote_warnings(source))
            print("Markdown heading check completed.")
            return 0
        output = _source(arguments.output) if arguments.output else source.with_suffix(".docx")
        if output.exists() and not arguments.overwrite:
            raise MardocxError(f"Output already exists: {output}. Use --overwrite to replace it.")
        output.parent.mkdir(parents=True, exist_ok=True)
        messages = convert(source, root, output, load_config(SKILL_DIR, root))
        _emit_warnings(messages)
        print(f"Created {output}")
        return 0
    except MardocxError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
