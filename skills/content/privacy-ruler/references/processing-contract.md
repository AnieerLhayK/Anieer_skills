# Processing contract v1

## Runtime and locations

Use a Python 3.11+ runtime with the declared PyMuPDF version; prefer an existing
working runtime over changing global packages. DOCX rendering needs LibreOffice
on PATH or an explicit `SOFFICE_PATH`. Missing dependencies block documents.
Tests additionally need the dependencies in `tests/requirements.txt` (pytest,
python-docx and Pillow). `python -m unittest discover tests` delegates to the
same public CLI suite for portable hosts; direct pytest skips this bridge to
avoid duplicate execution. No model API credentials or
external detection service are used. Helpers remain standalone local Python;
they do not depend on Workspace, QQ or another skill.

Keep transient fixtures, conversions and test runs in the host's staging area.
Keep durable private batches outside Git and outside delivery. The default is
`CODEX_HOME/private/privacy-ruler/<random-batch-id>`; when `CODEX_HOME` is unset,
use `~/.codex/private/privacy-ruler/<random-batch-id>`. Explicit `--private-dir`
must be a new directory. Sources remain read-only; delivery must also be new.
The directory is a private placement boundary, not encryption or an anonymity
guarantee. Apply appropriate local account access controls.

## Request and inspect

```json
{
  "inputs": [{"path": "/absolute/selected/file.json"}, {"text": "explicitly supplied text"}],
  "level": "medium",
  "destination": "restricted",
  "execution_mode": "privacy_subagent",
  "rules": [{"category": "person", "values": ["Example name", "Example alias"]}]
}
```

`level` is low/medium/high; `destination` is local/restricted/public. Optional
`execution_mode` records actual main/privacy_subagent/fallback_subagent execution
(direct CLI defaults to main). The worker/caller must select the truthful mode;
this field records execution, it does not create a sub-agent or prove one ran.
Optional
`mapping_path` explicitly names a previous private mapping. Rule categories are
person, organization, place, email, phone, identity, account, credential, context,
other. Literal aliases in a rule share one pseudonym. Do not infer identity from
a spelling match alone when people may share names. Material requiring different
per-occurrence meanings must be disambiguated in a new reviewed input or blocked.

Run `python scripts/privacy_ruler.py inspect --request <request.json>
--private-dir <new-private-directory>` from the skill directory. This writes
private request/plan/mapping JSON, with source fingerprints and inspectable
units. Inspect never marks semantic review complete. Automatic rules recognize
common emails, mainland-China mobile numbers and identity numbers, labeled
QQ/WeChat accounts and labeled credentials. They are candidate rules, not a
complete entity recognizer; other identifiers require Codex review/rules.

No implicit filesystem recursion or link fetching occurs. Files are bounded to
100 MiB; DOCX expansion is bounded to 512 MiB and 10,000 parts. Invalid JSONL
lines and duplicate object keys block the file rather than disappear. Blank
JSONL lines carry no record. CSV/TSV values remain strings.

## Private plan and semantic receipt

`plan.json` contains `schema_version`, `batch_id`, requested/effective level,
destination, escalation reasons, replacements and files. A replacement is
`{"old":"literal source", "new":"[PERSON_001]", "category":"person"}`.
Review may add names, literal contextual generalizations or deletions. Assign
each identity once, update all its aliases, and avoid replacement text containing
any protected original. Longest matches win in a single pass; no cascading.
Conflicting aliases or resulting key/column collisions block processing.

For every inspected file, set its semantic receipt only after exhaustive review:

```json
{"semantic_review":{"status":"complete","reviewer":"codex","coverage":"all_units","risks":[],"losses":[]}}
```

Keep actual risks, retained identifying context, generalization/deletion losses,
and structure/type changes in these private lists. State medium/high contextual
decisions explicitly even when no change was necessary. Raise `effective_level`
and append a reason when context requires more protection. Public can never be
downgraded below high. A receipt records an actual review; it is not automatic
proof of semantic judgment and must not be synthesized just to bypass the gate.

## Apply and verify

Run `apply --plan <plan.json> --out <new-delivery-directory>`. It checks source
SHA-256, writes private candidates, reopens them, rejects known residual values,
and renders DOCX/PDF candidates to private PNGs. A private `run.json` records
candidate fingerprints, page counts, states and review receipts. Text/structured
outputs with completed semantic review can be delivered immediately pending
human review. Documents await visual review; other independent files can finish.
The private `review-diff.json` retains before/after inventories and review losses.

For each document, inspect every PNG and record this in its run-file entry:

```json
{"visual_review":{"status":"complete","reviewer":"codex","sha256":"exact candidate SHA-256","pages":[1,2]}}
```

The page list must include every page in order. Use actual inspection, including
vector drawings or missing text not represented by extraction. Then run
`verify --run <run.json>`; only verified candidates enter delivery. A changed
candidate invalidates its receipt. Use a new inspected batch for changed sources,
plans or failed candidates; explicit mapping reuse can preserve aliases.

Delivery contains neutral `file-0001.ext` names and `report.json`; source names,
fingerprints, original text, mappings and detailed review notes stay private.
Per-file states include blocked, awaiting_visual_review and delivered. Overall
status is processed_pending_human_review, partial, blocked or failed. Exit code
0 means inspection completed or every file is processed pending human review;
2 means partial/blocked/failed. Inspect can return 0 with blocked files: read its
blocked count and each private file state. Coded diagnostics contain no raw
exception text. No status means approved for publication or anonymous.

## Native-document limits

DOCX treats revision insertions/moves as accepted final text and removes deleted
text/history, comments, hidden styles/runs, field instructions, custom XML,
identity properties and external relationships. It covers paragraphs, nested
tables, headers/footers, notes and supported text boxes across package parts.
Final checks include internal package part names; a protected value remaining
there blocks the file rather than renaming unknown OOXML references.
Images, embedded objects, unsupported drawing payloads and binary parts block
the file; disposable Office preview thumbnails are removed as metadata.

PDF physically removes matching content, clears metadata/XML metadata,
annotations, links and outlines, removes invisible text, and fully saves with
garbage collection. It blocks images, scanned/empty-text pages, forms, embedded
files, optional-content layers, signatures, encryption and repaired documents.
Replacement text must fit its original area down to a minimum readable size;
otherwise block instead of truncating. Fonts and decoded streams are inspected
for protected values; visual review remains necessary for outlined/vector text.

These conservative subsets preserve file format, not all interactive features
or exact layout. Removing identity carriers and contextual facts can reduce
scientific or linguistic utility. Never label raw research-reader output or
an existing pipeline privacy score as an anonymized dataset.
