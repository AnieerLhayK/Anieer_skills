"""Validate a generated declarative collaboration scaffold."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from collaboration_config import ConfigError, normalize_config
SKILL_ROOT = Path(__file__).resolve().parents[1]
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("target", type=Path); args = parser.parse_args(); target = args.target.resolve()
    try: config = normalize_config(target / ".collaboration.yaml", SKILL_ROOT)
    except ConfigError as exc: print(f"[ERROR] invalid configuration: {exc}"); return 1
    required = ["AGENTS.md", "README.md", "PROJECT_CONTEXT/README.md", f"{config['governance']['root']}/AGENTS.md"] + [f"{x['path']}/AGENTS.md" for x in config["resolved_roles"]]
    if config["features"]["ai_records"]["enabled"]: required += ["scripts/check_change_scope.py", *[f"{x['path']}/ai-records/record-template.md" for x in config["resolved_roles"]]]
    if config["features"]["work_session_lock"]["enabled"]: required += ["scripts/work_session.py"]
    if config["features"]["git_hooks"]["enabled"]: required += [".githooks/pre-commit", ".githooks/pre-push", "scripts/check_change_scope.py", "scripts/install_collaboration_hooks.py"]
    missing = [x for x in required if not (target / x).exists()]
    if missing: print("\n".join("[ERROR] missing " + x for x in missing)); return 1
    print(f"[PASS] collaboration scaffold valid: layout={config['layout']}; roles={len(config['resolved_roles'])}"); return 0
if __name__ == "__main__": raise SystemExit(main())
