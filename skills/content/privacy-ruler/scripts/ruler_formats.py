"""Format adapters; preserve structure unless sensitive scalar/key replacement needs change."""
import csv
import io
import json
from pathlib import Path


class FormatError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


TEXT = {".txt", ".md"}
STRUCTURED = {".json", ".jsonl", ".csv", ".tsv"}


def load(path):
    suffix = path.suffix.lower()
    if suffix not in TEXT | STRUCTURED:
        raise FormatError("unsupported_format")
    text = path.read_text(encoding="utf-8-sig")
    if suffix in TEXT:
        return text
    if suffix == ".json":
        return json.loads(text, object_pairs_hook=unique_object)
    if suffix == ".jsonl":
        return [json.loads(line, object_pairs_hook=unique_object) for line in text.splitlines() if line.strip()]
    if suffix in {".csv", ".tsv"}:
        return list(csv.reader(io.StringIO(text, newline=""), delimiter="\t" if suffix == ".tsv" else ",", strict=True))
    raise FormatError("unsupported_format")


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise FormatError("duplicate_or_colliding_key")
        obj[key] = value
    return obj


def units(value):
    if isinstance(value, dict):
        return [v for key, child in value.items() for v in [str(key), *units(child)]]
    if isinstance(value, list):
        return [v for child in value for v in units(child)]
    return [str(value)]


def inspect_file(path):
    if path.suffix.lower() in {".docx", ".pdf"}:
        from ruler_documents import document_units
        return document_units(path)
    values = units(load(path))
    return [{"id": f"unit-{i}", "text": v} for i, v in enumerate(values)], []


def transform(value, replace):
    if isinstance(value, dict):
        return unique_object([(replace(key), transform(child, replace)) for key, child in value.items()])
    if isinstance(value, list):
        return [transform(child, replace) for child in value]
    if isinstance(value, str):
        return replace(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        changed = replace(str(value))
        return changed if changed != str(value) else value
    return value


def write_file(source, target, replace):
    if source.suffix.lower() in {".docx", ".pdf"}:
        from ruler_documents import write_document
        return write_document(source, target, replace)
    before = replace.count
    value = transform(load(source), replace)
    suffix = source.suffix.lower()
    if suffix in TEXT:
        text = value
    elif suffix == ".json":
        text = json.dumps(value, ensure_ascii=False, indent=2)
    elif suffix == ".jsonl":
        text = "\n".join(json.dumps(v, ensure_ascii=False) for v in value) + "\n"
    else:
        if value and len(set(value[0])) != len(value[0]):
            raise FormatError("duplicate_or_colliding_column")
        stream = io.StringIO(newline="")
        writer = csv.writer(stream, delimiter="\t" if suffix == ".tsv" else ",", lineterminator="\n")
        writer.writerows(value)
        text = stream.getvalue()
    target.write_text(text, encoding="utf-8")
    return replace.count - before


def schema_changes(source, candidate):
    if source.suffix.lower() not in STRUCTURED:
        return []
    changes = []
    def compare(a, b, location):
        if type(a) is not type(b):
            changes.append({"location": location, "before_type": type(a).__name__, "after_type": type(b).__name__})
        elif isinstance(a, dict):
            if list(a) != list(b):
                changes.append({"location": location, "changed_keys": True})
            for i, ((_, av), (_, bv)) in enumerate(zip(a.items(), b.items())):
                compare(av, bv, f"{location}/{i}")
        elif isinstance(a, list):
            for i, (av, bv) in enumerate(zip(a, b)):
                compare(av, bv, f"{location}/{i}")
    a, b = load(source), load(candidate)
    compare(a, b, "$")
    if source.suffix.lower() in {".csv", ".tsv"} and a and b and a[0] != b[0]:
        changes.append({"location": "header", "changed_columns": True})
    return changes


def check_file(path, replacements):
    values, _ = inspect_file(path)
    for unit in values:
        if any(entry["old"] in value for entry in replacements
               for value in (unit["text"], unit.get("part", ""))):
            raise FormatError("protected_value_remaining")
