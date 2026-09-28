# Safety Policy

## Read boundary

Inventory uses only explicit roots. It reads direct skill entrypoints or manifest-declared skill sources beneath those roots. It excludes session, cache, credential, secret, private-project, report, corpus, runtime-character, and version-control storage. A path that escapes through a symlink, junction, or reparse point is a blocker.

## Export boundary

The payload contains portable UTF-8 text. The deterministic scanner blocks:

- credential and authorization-token patterns;
- Windows drive, UNC, user-profile, Unix home, and system absolute paths;
- NUL bytes, decoding failures, unsupported file types, and oversized text;
- source links and paths outside the prepared payload;
- missing provenance, license, attribution, or adaptation mode.

The agent also performs semantic review for personal information, private project facts, machine configuration, copyrighted material beyond the recorded license, and unresolved local dependencies. Passing the deterministic scanner does not replace that review.

## Write boundary

The approved plan hash is the write capability. Before `apply`, satisfy the host's task-record, agent-authority, external-output, and rollback requirements. A denied check stops at the plan. The CLI never installs anything on the target machine and never changes Codex accounts, plugins, or configuration.

## Receiver boundary

The generated `START_HERE.md` instructs the receiving Codex to inspect its own environment, report differences and conflicts, and propose an integration plan. It waits for user approval before any installation or configuration write.
