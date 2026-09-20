"""Create a declarative collaboration scaffold in a new target directory."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
import yaml
sys.dont_write_bytecode = True
from collaboration_config import ConfigError, normalize_config

SKILL_ROOT = Path(__file__).resolve().parents[1]

SCOPE_SCRIPT = '''"""Check staged paths against declarative AI-record coverage."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import yaml
ROOT = Path(__file__).resolve().parents[1]
def main():
    config = yaml.safe_load((ROOT / ".collaboration.yaml").read_text(encoding="utf-8")) or {}
    feature = config.get("features", {}).get("ai_records", {})
    if not feature.get("enabled"): print("[PASS] AI records disabled"); return 0
    changed = subprocess.run(["git", "diff", "--cached", "--name-only", "-z"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.split("\\0")
    covers = set()
    for role in config.get("resolved_roles", []):
        for record in (ROOT / role["path"] / "ai-records").glob("*.md"):
            text = record.read_text(encoding="utf-8")
            if text.startswith("---\\n") and "\\n---" in text[4:]:
                data = yaml.safe_load(text[4:text.find("\\n---", 4)]) or {}
                if isinstance(data, dict) and isinstance(data.get("covers"), list): covers.update(x for x in data["covers"] if isinstance(x, str))
    missing = [p for p in changed if p and "/ai-records/" not in p and p not in covers]
    if missing:
        message = "AI-record coverage missing: " + ", ".join(missing)
        if feature.get("enforcement") == "advisory": print("[WARNING] " + message); return 0
        print("[ERROR] " + message, file=sys.stderr); return 1
    print("[PASS] staged paths covered"); return 0
if __name__ == "__main__": raise SystemExit(main())
'''

LOCK_SCRIPT = '''"""Manage path-scoped local work sessions."""
from __future__ import annotations
import argparse, datetime as dt, json, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def location():
    value = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()
    return Path(value) / "collaboration-work-sessions.json"
def active(items):
    now = dt.datetime.now(dt.timezone.utc)
    return [x for x in items if dt.datetime.fromisoformat(x["expires_at"].replace("Z", "+00:00")) > now]
def overlaps(left, right): return any(a == b or a.startswith(b + "/") or b.startswith(a + "/") for a in left for b in right)
def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    acquire = sub.add_parser("acquire"); acquire.add_argument("--owner", required=True); acquire.add_argument("--work-item", required=True); acquire.add_argument("--paths", required=True); acquire.add_argument("--expires-at", required=True)
    release = sub.add_parser("release"); release.add_argument("--owner", required=True); release.add_argument("--work-item", required=True)
    handoff = sub.add_parser("handoff"); handoff.add_argument("--owner", required=True); handoff.add_argument("--work-item", required=True); handoff.add_argument("--to", required=True)
    check = sub.add_parser("check"); check.add_argument("--paths", required=True)
    args = parser.parse_args(); path = location(); items = active(json.loads(path.read_text(encoding="utf-8")) if path.exists() else [])
    if args.command == "acquire":
        paths = [x.strip().strip("/") for x in args.paths.split(",") if x.strip()]
        expiry = dt.datetime.fromisoformat(args.expires_at.replace("Z", "+00:00"))
        if not paths or expiry.tzinfo is None or expiry <= dt.datetime.now(dt.timezone.utc): raise SystemExit("paths and a future timezone-aware expiry are required")
        if any(x["owner"] != args.owner and overlaps(paths, x["paths"]) for x in items): raise SystemExit("conflicting active session")
        items.append({"owner": args.owner, "work_item": args.work_item, "paths": paths, "expires_at": args.expires_at}); path.write_text(json.dumps(items, indent=2), encoding="utf-8"); print("Session acquired.")
    elif args.command == "release":
        result = [x for x in items if not (x["owner"] == args.owner and x["work_item"] == args.work_item)]
        if len(result) == len(items): raise SystemExit("matching session not found")
        path.write_text(json.dumps(result, indent=2), encoding="utf-8"); print("Session released.")
    elif args.command == "handoff":
        found = False
        for x in items:
            if x["owner"] == args.owner and x["work_item"] == args.work_item: x["owner"] = args.to; found = True
        if not found: raise SystemExit("matching session not found")
        path.write_text(json.dumps(items, indent=2), encoding="utf-8"); print("Session handed off.")
    else:
        paths = [x.strip().strip("/") for x in args.paths.split(",") if x.strip()]
        if any(overlaps(paths, x["paths"]) for x in items): raise SystemExit("active session conflict")
        print("No active session conflict.")
if __name__ == "__main__": main()
'''

HOOK_INSTALLER = '''"""Install generated hooks only when local Git configuration is compatible."""
from __future__ import annotations
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def main():
    current = subprocess.run(["git", "config", "--local", "--get", "core.hooksPath"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if current and current.replace("\\\\", "/") != ".githooks": raise SystemExit(f"existing core.hooksPath={current}; integrate manually")
    subprocess.run(["git", "config", "--local", "core.hooksPath", ".githooks"], cwd=ROOT, check=True); print("Configured local core.hooksPath=.githooks")
if __name__ == "__main__": main()
'''

def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text, encoding="utf-8", newline="\n")

def create(target: Path, name: str, config: dict) -> None:
    root = config["governance"]["root"]
    write(target / ".collaboration.yaml", yaml.safe_dump(config, allow_unicode=False, sort_keys=False))
    write(target / "AGENTS.md", f"# Collaboration rules\n\nRead `.collaboration.yaml` and `{root}/AGENTS.md`.\n")
    write(target / "README.md", f"# {name}\n\nLayout: `{config['layout']}`.\n")
    write(target / root / "AGENTS.md", "# Governance\n\nThis directory owns shared permissions, handoff and integration guidance.\n")
    permissions = "# Permissions\n\n```yaml\n" + yaml.safe_dump({"protected_exact": config["governance"]["protected_exact"], "protected_prefixes": config["governance"]["protected_prefixes"], "shared_roots": config["shared_roots"]}, sort_keys=False) + "```\n"
    routes = "# Task routes\n\n```yaml\n" + yaml.safe_dump(config["tasks"], sort_keys=False) + "```\n"
    write(target / root / "permissions.md", permissions)
    write(target / root / "task-routes.md", routes)
    for file, text in {"handoff.md": "# Handoff\n", "integration.md": "# Integration\n"}.items(): write(target / root / file, text)
    write(target / "PROJECT_CONTEXT" / "README.md", "# Project context\n\nProject facts belong here.\n")
    for role in config["resolved_roles"]:
        area = target / role["path"]
        write(area / "AGENTS.md", f"# {role['id']} area\n\nRead root rules and `{root}/AGENTS.md`.\n")
        if config["features"]["ai_records"]["enabled"]:
            write(area / "ai-records" / "README.md", "# AI records\n")
            write(area / "ai-records" / "record-template.md", f"---\nai_record_version: 1\nwork_item: TODO\nowner: {role['id']}\nstatus: draft\ncovers: []\nevidence: []\n---\n\n# AI work record\n")
    if config["features"]["ai_records"]["enabled"] or config["features"]["git_hooks"]["enabled"]:
        write(target / "scripts" / "check_change_scope.py", SCOPE_SCRIPT)
    if config["features"]["work_session_lock"]["enabled"]: write(target / "scripts" / "work_session.py", LOCK_SCRIPT)
    if config["features"]["git_hooks"]["enabled"]:
        write(target / ".githooks" / "pre-commit", "#!/bin/sh\npython scripts/check_change_scope.py --staged\n")
        write(target / ".githooks" / "pre-push", "#!/bin/sh\npython scripts/check_change_scope.py --staged\n")
        write(target / "scripts" / "install_collaboration_hooks.py", HOOK_INSTALLER)

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--target", required=True, type=Path); parser.add_argument("--project-name", required=True); parser.add_argument("--config", type=Path); parser.add_argument("--roles"); parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if bool(args.config) == bool(args.roles): parser.error("provide exactly one of --config or --roles")
    source = args.config
    legacy = None
    if args.roles:
        print("WARNING: --roles is deprecated; use --config", file=sys.stderr)
        legacy = args.target.resolve().parent / ".collaboration-legacy.yaml"; legacy.write_text(yaml.safe_dump({"schema_version": 1, "layout": "isolated-areas", "roles": [x.strip() for x in args.roles.split(",") if x.strip()]}), encoding="utf-8"); source = legacy
    try: config = normalize_config(source.resolve(), SKILL_ROOT)
    except ConfigError as exc: print(f"Configuration error: {exc}", file=sys.stderr); return 2
    finally:
        if legacy: legacy.unlink(missing_ok=True)
    target = args.target.resolve()
    if target.exists() and any(target.iterdir()) and not args.dry_run: print("Target must be new or empty; use --dry-run for existing repositories.", file=sys.stderr); return 2
    planned = [".collaboration.yaml", "AGENTS.md", "README.md", config["governance"]["root"] + "/", "PROJECT_CONTEXT/"] + [x["path"] + "/" for x in config["resolved_roles"]]
    if args.dry_run: print(f"Would create {target} using {config['layout']}:\n" + "\n".join("- " + x for x in planned)); return 0
    create(target, args.project_name, config); print(f"Created declarative collaboration scaffold: {target}"); return 0
if __name__ == "__main__": raise SystemExit(main())
