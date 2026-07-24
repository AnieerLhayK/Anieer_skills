# Shared collaboration rules

This is the common source for AI work records. Role `CLAUDE.md` files only point to their sibling `AGENTS.md`.

- Record an AI stage only when it forms or changes project facts: an assumption, decision, model, implementation behavior, result, conclusion, or handoff claim.
- Write records in `team/<role>/AI-records/<work-item>.md`. Continue the same record while the work item, delivery goal, key evidence and approach remain the same; add a new section when one changes materially.
- Use stable section IDs such as `AI-<role>-<work-item>-001`. State goal/continuity, AI contribution and human choices, sources and outputs, validation, risks and handoff.
- Link authoritative artifacts instead of copying them. Keep prompts, chat transcripts, secrets and transient logs out of records.
- At key AI delivery or handoff, stage the matching record and run the scope check with `--ai-work <work-item>`.

## Local extension boundary

Role owners may add commands, conventions and checklists to their `AGENTS.md`. Shared provenance, task routing, review and authorization requirements remain unchanged unless a maintainer updates this file and its configuration.
