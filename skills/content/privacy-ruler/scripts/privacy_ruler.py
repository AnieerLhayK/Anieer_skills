#!/usr/bin/env python3
"""Bounded local processing. Semantic and visual receipts are supplied by Codex."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

from ruler_formats import FormatError, inspect_file, write_file, check_file

VERSION = 1
SAFE_FORMATS = {".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".docx", ".pdf"}
LEVELS = {"low": 0, "medium": 1, "high": 2}
PATTERNS = {
    "email": r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
    "phone": r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)",
    "identity": r"(?<!\d)\d{17}[\dXx](?!\d)",
    "account": r"(?:QQ|微信|WeChat|wechat|wx)[:：\s]*[A-Za-z0-9_-]{5,}",
    "credential": r"(?i)(?:api[_-]?key|password|token|密码)\s*[:=：]\s*(?P<secret>[^\s,;，；]+)",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_mapping(path, entries):
    save_json(path, {"schema_version": VERSION, "replacements": [e for e in entries if e["category"] != "credential"]})


def inside(path, root):
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def in_repository(path):
    return any((p / ".git").exists() for p in [Path(path).resolve(), *Path(path).resolve().parents])


def require(condition, code):
    if not condition:
        raise FormatError(code)


def validate_replacements(entries):
    seen = {}
    for entry in entries:
        old, new = entry["old"], entry["new"]
        require(isinstance(old, str) and old and isinstance(new, str) and old != new, "invalid_replacement")
        require(old not in seen or seen[old] == new, "conflicting_replacement")
        seen[old] = new
    # A replacement must never reintroduce any protected value.
    require(not any(old in new for old in seen for new in seen.values()), "replacement_reintroduces_source")
    return seen


class Replacer:
    def __init__(self, entries):
        self.mapping = validate_replacements(entries)
        self.pattern = re.compile("|".join(re.escape(v) for v in sorted(self.mapping, key=len, reverse=True))) if self.mapping else None
        self.count = 0

    def __call__(self, value):
        if not isinstance(value, str):
            return value
        if not self.pattern:
            return value
        def sub(match):
            self.count += 1
            return self.mapping[match[0]]
        return self.pattern.sub(sub, value)


def add_entity(entries, values, category):
    require(category in {"person", "organization", "place", "email", "phone", "identity", "account", "credential", "context", "other"}, "invalid_category")
    require(isinstance(values, list) and values and all(isinstance(v, str) and v for v in values), "invalid_rule")
    prior = {e["new"] for e in entries if e["old"] in values}
    require(len(prior) <= 1, "alias_conflict")
    used = {e["new"] for e in entries}
    serial = 1
    while f"[{category.upper()}_{serial:03d}]" in used:
        serial += 1
    token = next(iter(prior), f"[{category.upper()}_{serial:03d}]")
    for value in values:
        if not any(e["old"] == value for e in entries):
            entries.append({"old": value, "new": token, "category": category})


def inspect(request_path, private_dir=None):
    req = read_json(request_path)
    require(req.get("level", "medium") in LEVELS, "invalid_level")
    require(req.get("destination", "restricted") in {"local", "restricted", "public"}, "invalid_destination")
    require(req.get("execution_mode", "main") in {"main", "privacy_subagent", "fallback_subagent"}, "invalid_execution_mode")
    batch = uuid.uuid4().hex
    private = Path(private_dir).resolve() if private_dir else Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "private" / "privacy-ruler" / batch
    require(not private.exists() and not in_repository(private), "private_directory_not_new_or_in_repository")
    inputs = req.get("inputs", [])
    require(isinstance(inputs, list) and inputs, "explicit_inputs_required")
    require(all(isinstance(i, dict) and ("path" in i) != ("text" in i) for i in inputs), "invalid_input")
    for item in inputs:
        if "path" in item:
            require(Path(item["path"]).is_absolute(), "absolute_input_path_required")
            require(not inside(item["path"], private), "input_private_overlap")
    private.mkdir(parents=True)
    entries = []
    if req.get("mapping_path"):
        mapping_path = Path(req["mapping_path"]).resolve()
        require(not in_repository(mapping_path), "mapping_in_repository")
        prior = read_json(mapping_path)
        require(prior.get("schema_version") == VERSION, "unsupported_mapping_version")
        entries = prior["replacements"]
        validate_replacements(entries)
    for rule in req.get("rules", []):
        add_entity(entries, rule["values"], rule.get("category", "other"))
    files = []
    for number, source in enumerate(inputs, 1):
        ident = f"file-{number:04d}"
        if "text" in source:
            path = private / f"{ident}.source.txt"
            path.write_text(source["text"], encoding="utf-8")
        else:
            path = Path(source["path"]).resolve()
        item = {"id": ident, "path": str(path), "semantic_review": {"status": "pending"}}
        try:
            require(path.is_file() and path.stat().st_size <= 100 * 1024 * 1024, "input_missing_or_size_limit")
            item["sha256"] = digest(path)
            item["format"] = path.suffix.lower()
            item["units"], item["losses"] = inspect_file(path)
            # Filename participates in detection; it is never copied to delivery.
            for text in [path.name, *[u["text"] for u in item["units"]]]:
                for category, pattern in PATTERNS.items():
                    for match in re.finditer(pattern, text):
                        add_entity(entries, [match["secret"] if category == "credential" else match[0]], category)
            item["state"] = "inspected"
        except Exception as exc:
            item["state"] = "blocked" if isinstance(exc, FormatError) else "failed"
            item["code"] = exc.code if isinstance(exc, FormatError) else "input_unreadable"
        files.append(item)
    requested = req.get("level", "medium")
    effective = "high" if req.get("destination", "restricted") == "public" else requested
    plan = {"schema_version": VERSION, "batch_id": batch, "private_dir": str(private), "requested_level": requested,
            "execution_mode": req.get("execution_mode", "main"),
            "effective_level": effective, "destination": req.get("destination", "restricted"),
            "escalation_reasons": ["public_destination"] if effective != requested else [],
            "replacements": entries, "files": files}
    save_json(private / "request.json", req)
    save_json(private / "plan.json", plan)
    save_mapping(private / "mapping.json", entries)
    return {"status": "inspected", "effective_level": effective, "files": len(files), "blocked": sum(i["state"] != "inspected" for i in files)}


def semantic_complete(item):
    review = item.get("semantic_review", {})
    return (review.get("status") == "complete" and review.get("coverage") == "all_units"
            and review.get("reviewer") == "codex" and isinstance(review.get("risks"), list)
            and isinstance(review.get("losses"), list))


def apply(plan_path, output):
    plan_path = Path(plan_path).resolve()
    plan = read_json(plan_path)
    require(plan.get("schema_version") == VERSION, "unsupported_plan_version")
    private = Path(plan["private_dir"]).resolve()
    require(inside(plan_path, private) and not in_repository(private), "invalid_private_boundary")
    out = Path(output).resolve()
    require(not out.exists() and not in_repository(out) and not inside(out, private) and not inside(private, out), "invalid_delivery_boundary")
    require(all(out != Path(i["path"]).resolve() and not inside(i["path"], out) for i in plan["files"]), "source_delivery_overlap")
    requested, effective = plan["requested_level"], plan["effective_level"]
    require(requested in LEVELS and effective in LEVELS and LEVELS[effective] >= LEVELS[requested], "invalid_effective_level")
    require(plan["destination"] != "public" or effective == "high", "public_requires_high")
    replacer = Replacer(plan["replacements"])
    if not any(i["state"] == "inspected" and semantic_complete(i) for i in plan["files"]):
        report = {"status": "blocked", "requested_level": requested, "effective_level": effective,
                  "execution_mode": plan.get("execution_mode", "main"),
                  "files": [{"id": i["id"], "state": i["state"] if i["state"] in {"blocked", "failed"} else "blocked",
                             "code": i.get("code", "semantic_review_required"),
                             "format": i.get("format") if i.get("format") in SAFE_FORMATS else "unsupported"} for i in plan["files"]]}
        save_json(private / "report.json", report)
        return report
    require(not (private / "run.json").exists(), "run_already_exists_reinspect")
    save_mapping(private / "mapping.json", plan["replacements"])
    files = []
    diffs = []
    for item in plan["files"]:
        result = {"id": item["id"], "state": "failed" if item["state"] == "failed" else "blocked", "code": item.get("code", "semantic_review_required"), "format": item.get("format", "")}
        if item["state"] == "inspected" and semantic_complete(item):
            try:
                source = Path(item["path"])
                require(digest(source) == item["sha256"], "source_changed")
                candidate = private / (item["id"] + ".candidate" + item["format"])
                changes = write_file(source, candidate, replacer)
                check_file(candidate, plan["replacements"])
                from ruler_formats import schema_changes
                schema = schema_changes(source, candidate)
                after_units, _ = inspect_file(candidate)
                diffs.append({"id": item["id"], "before": item["units"], "after": after_units,
                              "schema_changes": schema, "semantic_review": item["semantic_review"]})
                result.update({"state": "verified", "code": "technical_checks_passed", "candidate": str(candidate),
                               "sha256": digest(candidate), "changes": changes, "losses": item["losses"],
                               "schema_changes": len(schema), "semantic_review": item["semantic_review"]})
                if item["format"] in {".docx", ".pdf"}:
                    from ruler_documents import render_candidate
                    pages = render_candidate(candidate)
                    result.update({"state": "awaiting_visual_review", "pages": pages, "visual_review": {"status": "pending"}})
            except Exception as exc:
                result.update({"state": "blocked" if isinstance(exc, FormatError) else "failed", "code": exc.code if isinstance(exc, FormatError) else "processing_failed"})
        files.append(result)
    run = {"schema_version": VERSION, "private_dir": str(private), "output_dir": str(out),
           "execution_mode": plan.get("execution_mode", "main"),
           "requested_level": requested, "effective_level": effective, "destination": plan["destination"],
           "escalation_reasons": plan["escalation_reasons"], "replacements": plan["replacements"], "files": files}
    save_json(private / "run.json", run)
    save_json(private / "review-diff.json", diffs)
    return verify(private / "run.json")


def verify(run_path):
    run = read_json(run_path)
    private = Path(run["private_dir"]).resolve()
    require(inside(run_path, private) and not in_repository(private), "invalid_private_boundary")
    out = Path(run["output_dir"]).resolve()
    require(not inside(out, private) and not inside(private, out) and not in_repository(out), "invalid_delivery_boundary")
    ready = []
    for item in run["files"]:
        if item["state"] not in {"verified", "awaiting_visual_review", "delivered"}:
            continue
        try:
            candidate = Path(item["candidate"]).resolve()
            require(inside(candidate, private), "candidate_outside_private")
            require(digest(candidate) == item["sha256"], "candidate_changed")
            check_file(candidate, run["replacements"])
            if item["format"] in {".pdf", ".docx"}:
                review = item.get("visual_review", {})
                require(review.get("status") == "complete" and review.get("reviewer") == "codex"
                        and review.get("sha256") == item["sha256"]
                        and review.get("pages") == list(range(1, item["pages"] + 1)), "visual_review_required")
            ready.append(item)
        except Exception as exc:
            item["code"] = exc.code if isinstance(exc, FormatError) else "verification_failed"
            item["state"] = "awaiting_visual_review" if item["code"] == "visual_review_required" else "blocked"
    if ready:
        # Refuse arbitrary pre-existing output directories, including a tampered run.
        if out.exists():
            require(run.get("published") is True, "delivery_already_exists")
            expected = {"report.json", *[i["id"] + i["format"] for i in run["files"] if i["state"] == "delivered"]}
            require({p.name for p in out.iterdir()} == expected, "delivery_contents_changed")
        else:
            out.mkdir(parents=True)
        for item in ready:
            target = out / (item["id"] + item["format"])
            if target.exists():
                require(digest(target) == item["sha256"], "delivered_file_changed")
            else:
                pending = out / (target.name + ".pending")
                require(not pending.exists(), "pending_output_already_exists")
                shutil.copyfile(item["candidate"], pending)
                require(digest(pending) == item["sha256"], "copied_output_changed")
                pending.replace(target)
            item["state"] = "delivered"
            item["code"] = "verified_pending_human_review"
        run["published"] = True
    delivered = sum(i["state"] == "delivered" for i in run["files"])
    status = ("processed_pending_human_review" if delivered == len(run["files"]) else "partial") if delivered else "blocked"
    report = {"schema_version": VERSION, "status": status, "requested_level": run["requested_level"],
              "execution_mode": run.get("execution_mode", "main"),
              "effective_level": run["effective_level"], "escalation_reasons": run["escalation_reasons"],
              "files": [{"id": i["id"], "state": i["state"], "code": i["code"],
                         "format": i["format"] if i["format"] in SAFE_FORMATS else "unsupported", "changes": i.get("changes", 0),
                         "schema_changes": i.get("schema_changes", 0),
                         "semantic_losses": len(i.get("semantic_review", {}).get("losses", []))} for i in run["files"]],
              "residual_risks": ["contextual_reidentification_remains_possible", "human_review_required", "not_an_anonymity_guarantee"],
              "losses": ["source_filenames_replaced", "document_identity_metadata_removed", "see_private_review_for_content_and_schema_changes"]}
    save_json(run_path, run)
    save_json(private / "report.json", report)
    if run.get("published"):
        save_json(out / "report.json", report)
    return report


def main():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            print(json.dumps({"status": "failed", "code": "invalid_cli_arguments"}))
            self.exit(2)
    parser = SafeParser(description="Privacy-Ruler local inspect/apply/verify; never publishes remotely.")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("inspect")
    p.add_argument("--request", required=True)
    p.add_argument("--private-dir")
    p = commands.add_parser("apply")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", required=True)
    p = commands.add_parser("verify")
    p.add_argument("--run", required=True)
    args = parser.parse_args()
    try:
        result = (inspect(args.request, args.private_dir) if args.command == "inspect" else
                  apply(args.plan, args.out) if args.command == "apply" else verify(args.run))
        print(json.dumps(result, ensure_ascii=True))
        return 0 if result["status"] in {"inspected", "processed_pending_human_review"} else 2
    except Exception as exc:
        print(json.dumps({"status": "failed", "code": exc.code if isinstance(exc, FormatError) else "invalid_request_or_io_failure"}))
        return 2


if __name__ == "__main__":
    sys.exit(main())
