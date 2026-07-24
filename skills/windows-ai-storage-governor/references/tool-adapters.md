# Tool Adapters

Adapters provide bounded evidence. They do not grant permission to move data.
Tool versions and storage contracts can change; prefer live command output and
official documentation over remembered defaults.

## npm

- Probe `npm config get cache`.
- Probe `npm config get prefix`.
- Probe `npm root --global`.
- Treat cache as a migration candidate.
- Treat the global prefix and its global `node_modules` as runtime/install data,
  not project source.
- Preserve cache and prefix when they already resolve off the system drive.
- Verify executable shims and `PATH` resolution after any approved prefix change.
- Do not move a Node project or its source tree as part of global storage governance.

## Playwright

- Inspect `PLAYWRIGHT_BROWSERS_PATH` when set.
- Treat downloaded browser binaries as cache/runtime data.
- On Windows, also inspect the default `%LOCALAPPDATA%\ms-playwright` candidate.
  If it contains only `b/browser@*` records, classify it as small live registration
  metadata and report it without proposing migration or cleanup.
- Do not assume `PLAYWRIGHT_BROWSERS_PATH` relocates branded Chrome or Edge
  installations; it governs Playwright-managed browser data.
- Verify the installed Playwright command can launch or locate its browsers.
- Do not assume one package manager or one default cache path.

## Gemini CLI

- Inspect the resolved executable and user-supplied configuration/data paths.
- Resolve user storage as `<GEMINI_CLI_HOME>/.gemini` when
  `GEMINI_CLI_HOME` is set; otherwise use `<user-home>/.gemini`.
- Treat profile candidates as mixed configuration, session, and runtime data until
  file-level evidence separates them.
- Preserve an existing correct junction or symlink for the user storage root.
- Do not relocate authentication or conversation data as if it were disposable cache.

## Documentation Checks

- Gemini CLI configuration: `https://geminicli.com/docs/reference/configuration/`
- npm configuration: `https://docs.npmjs.com/cli/using-npm/config`
- Playwright browser storage: `https://playwright.dev/docs/browsers`

Re-check these primary sources before applying a migration because tool storage
contracts and environment variables can change.

## MCP Hosts And Servers

- MCP is a protocol, not one storage layout.
- Inspect the host configuration first, then each server's declared working,
  cache, download, and log directories.
- Treat generated build/download directories as candidates only when provenance
  identifies the owning server and regeneration path.

## Hermes

- Treat `Hermes` as adapter-defined because multiple tools use the name.
- Require the executable, package, service, or user-provided path that identifies
  the implementation.
- Classify unknown Hermes directories as `unknown`; do not infer cleanup safety.

## Codex, Claude Code, OpenCode, And Copilot

- Preserve stable existing migrations, links, and session stores.
- Inspect configured homes, platform roots, session stores, and link targets.
- Do not recreate a correct junction or symlink.
- Treat sessions, history, databases, and recovery records as durable user data.
- Treat caches and downloaded runtimes separately from configuration and sessions.
