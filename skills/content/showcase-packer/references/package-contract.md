# Portable Showcase Package Contract

The generated package is a derived deliverable. Its source material remains outside the package and is not modified.

## Required content

- `README.md`: goal, audience, scope, and navigation.
- `narrative/data.md`: observed data or evidence, provenance summary, and data gaps.
- `narrative/approach.md`: the solution, method, proposal, or decision path.
- `narrative/conclusions.md`: supported conclusions, recommendations, and confidence limits.
- `review/evidence-map.md`: claims linked to included evidence or marked unsupported.
- `review/risks-and-limitations.md`: selection risks, uncertainty, exclusions, and limitations.
- `review/next-actions.md`: follow-up work, owner or decision needed, and exit criteria.
- `materials/`: only confirmed portable copies preserving their relative material path.
- `manifest.json`: schema version, build timestamp, package slug, sorted file records, checksums, sizes, and approved exceptions.

## Integrity rules

All material records use forward-slash relative paths. The manifest never stores the absolute source root, account name, host name, or local output root. Every copied material has one SHA-256 value calculated from the copied bytes. Narrative documents may summarize sources but must not claim an unsupported conclusion as fact.
