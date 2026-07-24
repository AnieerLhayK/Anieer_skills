# Migration Runbook

## Preconditions

1. Obtain an audit report and a stable plan ID.
2. Confirm the target root is user-selected, writable, and outside project source.
3. Confirm free space and tool shutdown requirements.
4. Record source type, link state, timestamps, and optional content hash.
5. Confirm the target does not contain unexpected data.
6. Obtain approval for exact action IDs.

## Preferred Relocation Order

1. Supported tool setting or command.
2. Documented environment variable.
3. Tool-supported cache or prefix command.
4. Directory junction or symlink when the tool cannot relocate itself.

## Reversible Sequence

For each approved action:

1. Stop the owning tool when required.
2. Create a new empty target.
3. Copy data while preserving the source.
4. Verify target content and permissions.
5. Rename the source to a timestamped rollback path.
6. Apply configuration or create the approved link.
7. Start the tool and run a health check.
8. Verify new writes land at the target.
9. Retain the rollback copy until a separately approved cleanup.

If any step fails, stop and restore the previous configuration or source name.

## Link Rules

- Do not replace an existing correct link.
- Do not replace an incorrect link automatically; report actual and expected targets.
- Do not create a link over a real directory.
- Record link type, source, target, and rollback command.

## Cleanup

Cleanup is a later operation. Require:

- Successful verification.
- A defined retention interval or explicit waiver.
- Exact rollback-copy paths.
- Separate user confirmation.
