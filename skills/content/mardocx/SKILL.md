---
name: mardocx
description: Convert project Markdown into a styled DOCX with a reusable project reference.docx.
disable-model-invocation: true
metadata:
  portability: portable
  distribution: review-required
  requires: [python, PyYAML, python-docx, pandoc]
---

# Mardocx

Use this skill only when the user explicitly invokes `$mardocx` to convert Markdown into a project-formatted DOCX.

Run `scripts/mardocx.py` from this skill directory. The script keeps the project template beside the document instead of using a global Word template.

## Workflow

1. Resolve the project root from `--project-root`, then the nearest ancestor containing `mardocx.yaml` or `reference.docx`; otherwise use the Markdown file's directory.
2. Run `check` before conversion and report every heading warning. Warnings never alter the Markdown or stop conversion.
3. Run `convert` with an explicit output path when the default same-name DOCX is unsuitable. It creates and styles a missing `reference.docx` once, then reuses it unchanged on later conversions.
4. Run `update-reference` only when the user asks to apply the current `mardocx.yaml` settings to the project's existing template.

Mardocx treats Chinese soft line breaks as continuous text and converts ASCII quote pairs to Unicode left/right quotation marks (U+201C/U+201D). It warns about source text that already contains a likely double-right-quote pattern without rewriting it.

## Commands

```powershell
python scripts/mardocx.py check .\report.md
python scripts/mardocx.py convert .\report.md
python scripts/mardocx.py update-reference --project-root .
```

`convert` refuses to overwrite an existing output unless `--overwrite` is present. It validates the generated DOCX before reporting success.

## Optional Word visual smoke check

When a visual check is requested and Word is available, use an isolated generated DOCX, open it read-only, and inspect a screenshot for continuous Chinese text and U+201C/U+201D quote pairs. Do not save the document. If Word is unavailable, report that the visual layer was skipped; DOCX content validation remains required.

## Project configuration

The optional `mardocx.yaml` at the project root overrides only the values it declares. Read [configuration.md](references/configuration.md) before adding or changing it. The current version supports typography and image settings; other document features remain owned by `reference.docx` until Mardocx adds a corresponding configuration section.
