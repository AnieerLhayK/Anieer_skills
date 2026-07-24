"""Create a generic collaboration scaffold in a new or empty directory."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SEED_ROOT = SKILL_ROOT / "assets" / "starter"
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")


def parse_roles(value: str) -> list[str]:
    roles = [item.strip() for item in value.split(",") if item.strip()]
    if not roles:
        raise ValueError("Provide at least one role.")
    if len(set(roles)) != len(roles) or any(not ROLE_PATTERN.fullmatch(role) for role in roles):
        raise ValueError("Roles must be unique lowercase IDs using letters, digits, and hyphens.")
    if "maintainer" in roles:
        raise ValueError("maintainer is reserved for shared governance.")
    return roles


def role_config(roles: list[str]) -> str:
    return "\n".join(f"  {role}:\n    path: team/{role}/" for role in roles)


def render_text(path: Path, replacements: dict[str, str]) -> None:
    if path.suffix.lower() not in {".md", ".yaml", ".yml", ".txt"}:
        return
    text = path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    path.write_text(text, encoding="utf-8", newline="\n")


def create_role_area(target: Path, role: str) -> None:
    root = target / "team" / role
    (root / "AI-records").mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text(
        f"# {role} area\n\nRead `../../COLLABORATION/AGENTS.md` first. "
        "Maintain this role's project artifacts and AI records. Add local operating details here "
        "without weakening the shared rules, task route, provenance, or review requirements.\n",
        encoding="utf-8",
    )
    (root / "CLAUDE.md").write_text(
        "Read `AGENTS.md`; it is the authoritative rule file for this role.\n", encoding="utf-8"
    )
    (root / "AI-records" / "README.md").write_text(
        "# AI work records\n\nCreate `<work-item>.md` only for AI work that forms or changes project facts. "
        "Use the common record structure in `COLLABORATION/AGENTS.md` and link authoritative artifacts.\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--roles", required=True, help="Comma-separated role IDs, e.g. delivery,research,writing")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    roles = parse_roles(args.roles)
    target = args.target.resolve()
    if not SEED_ROOT.is_dir():
        raise SystemExit(f"Starter assets are missing: {SEED_ROOT}")
    if target.exists() and any(target.iterdir()):
        raise SystemExit("Target must be new or empty. Generate beside an existing repository, then integrate deliberately.")

    planned = ["AGENTS.md", "README.md", "COLLABORATION/", "PROJECT_CONTEXT/", "scripts/"]
    planned.extend(f"team/{role}/" for role in roles)
    if args.dry_run:
        print(f"Would create {target} for {args.project_name} with roles: {', '.join(roles)}")
        print("\n".join(f"- {item}" for item in planned))
        return 0

    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SEED_ROOT, target, dirs_exist_ok=True)
    replacements = {"PROJECT_NAME": args.project_name, "ROLE_NAMES": ", ".join(roles), "ROLE_CONFIG": role_config(roles)}
    for path in target.rglob("*"):
        if path.is_file():
            render_text(path, replacements)
    for role in roles:
        create_role_area(target, role)
    print(f"Created collaboration scaffold: {target}")
    print("Next: install PyYAML, run scripts/validate_collaboration.py, then configure task scopes for project facts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
