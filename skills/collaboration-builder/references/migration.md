# Legacy migration

`--roles` is accepted for one compatibility release and maps to `isolated-areas`. It writes the equivalent normalized `.collaboration.yaml` and prints a deprecation warning.

Replace legacy role calls with an external YAML passed through `--config`. Do not migrate an existing repository in place with bootstrap; use `--dry-run` and integrate the reviewed proposal manually.
