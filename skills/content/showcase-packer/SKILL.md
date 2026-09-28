---
name: showcase-packer
description: Build a portable, review-gated evidence package when scoped materials must support a handoff, briefing, or decision with claim-to-evidence mapping.
metadata:
  portability: portable
  distribution: review-required
  requires: [python]
---

# Showcase-Packer

Create a portable, derived evidence package from user-scoped material. The package connects reviewed data, approach, and conclusions without changing source material.

## Use When

- The user needs to consolidate evidence, a proposed approach, and conclusions for an audience.
- The material may come from any domain and must become a handoff, review, briefing, or presentation package.
- The user needs a reviewable selection boundary before files are copied.

Do not use this skill to migrate external skills, publish a package, process private raw research data, or alter source material.

## Inputs

Require all of the following before previewing:

- **Goal:** the decision, review, or presentation the package supports.
- **Audience:** the people who will read it and their expected depth.
- **Material boundary:** one or more explicit source roots and allowed relative paths.
- **Output name:** a lowercase kebab-case package slug.
- **Output location:** a category and task slug under the manifest-declared `output_roots.workspace`; use `exports/<YYYY-MM>/<task-slug>/` for portable bundles unless the user chooses another allowed category.

Treat source roots as read-only. Use an output root authorized by the host; never embed its local absolute path in a generated package.

## Workflow

1. Run `preview` with an explicit source root, package name, output root, and optional includes. It is read-only and reports hashes, size, risks, exclusions, and exact approved exceptions. Default-exclude credentials, keys, personal data, raw-sensitive material, and absolute local paths.
2. Prepare complete staged content for `README.md`, the three `narrative/` files, and the three `review/` files. Placeholders and `TODO` content are not complete.
3. Run `plan` with the same material boundary plus `--content-root` and `--output-plan`. The plan records every selected material/content hash and a canonical `plan_sha256`.
4. Present the plan hash and risk exceptions for approval. Run `build --plan <path> --approve-plan-sha256 <hash>`. Build rechecks the plan, all inputs, and risk decisions before atomically publishing a new package.
5. Run `verify --package-root <path>`. Stop on missing, changed, duplicate, or unexpected files.

The original flat CLI remains available for compatibility: no `--build` previews, while `--build --confirmed` creates the historical schema-1.0 placeholder package. New completed work must use the hashed workflow.

The builder creates a derived package with this stable layout:

```text
<package>/
  README.md
  narrative/{data,approach,conclusions}.md
  review/{evidence-map,risks-and-limitations,next-actions}.md
  materials/
  manifest.json
```

New-workflow `manifest.json` covers every README, narrative, review, and material file with size and SHA-256. It records the approved plan hash but intentionally does not hash itself. Keep facts, interpretations, recommendations, uncertainty, and unknowns visibly separate.

## Boundaries

- Never modify, move, rename, or delete source material.
- Never overwrite an existing output package. Select a new output name or resolve the existing package through a separately authorized task.
- Never include a risk-classified file unless the user explicitly approved that exact relative path in the current confirmation.
- Never include absolute source paths in narrative, review, or manifest output.
- Stop if the source boundary is ambiguous, any material or staged-content hash changes, the approval hash differs, or output escapes the authorized root.

## Receipt

Report the confirmed package location, selected and excluded counts, explicitly approved exceptions, manifest checksum coverage, remaining evidence gaps, and the next review action.
