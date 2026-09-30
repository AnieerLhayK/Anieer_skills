# Remote Projection Audit

Use the selected registry entry's remote URL and contract. Audit named public content through the GitHub tree API; do not clone broadly. Run the helper from the skill directory so `scripts/audit_remote.py` resolves correctly.

```powershell
python scripts/audit_remote.py --repo OWNER/REPO --branch main --contract path/to/contract.json
```

`PASS` means the remote tree satisfies the contract. `WARN` requires a recorded decision before release. `FAIL` requires source, generator, checker, or contract repair before release. Preserve the JSON report when the caller asks for an audit artifact; otherwise include the status and actionable findings in the receipt.
