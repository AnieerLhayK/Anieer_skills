[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$AuditPath,
  [Parameter(Mandatory = $true)]
  [string]$TargetRoot,
  [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $AuditPath -PathType Leaf)) {
  throw "[ERROR] Missing required audit report: $AuditPath"
}

$audit = Get-Content -Raw -LiteralPath $AuditPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$audit.report_type -ne "audit") {
  throw "[ERROR] Input is not an audit report: $AuditPath"
}

$resolvedTargetRoot = [System.IO.Path]::GetFullPath([Environment]::ExpandEnvironmentVariables($TargetRoot))
$actions = [System.Collections.Generic.List[object]]::new()
$index = 0

foreach ($finding in @($audit.findings)) {
  $index++
  $classification = [string]$finding.classification
  $disposition = [string]$finding.disposition
  $source = [string]$finding.path
  $leaf = Split-Path -Leaf $source
  $target = if ([string]::IsNullOrWhiteSpace($leaf)) { "" } else { Join-Path $resolvedTargetRoot $leaf }
  $operation = "preserve"
  $risk = "No mutation proposed."
  $reason = "Classification is not on the migration whitelist."
  $rollback = "No rollback required."

  if (-not [bool]$finding.exists) {
    $operation = "report-only"
    $reason = "Candidate path does not exist."
  } elseif ($classification -eq "junction / symlink") {
    $reason = "Existing links are preserved and verified, not rebuilt."
  } elseif ($disposition -eq "migrate-candidate" -and $classification -in @("cache", "runtime data")) {
    $operation = "copy-then-link"
    $reason = "Re-creatable or relocatable data is a migration candidate."
    $risk = "Tool-specific configuration, locks, permissions, or concurrent writes may invalidate the plan."
    $rollback = "Remove only the newly created link or configuration change, then restore the retained source path."
  } elseif ($classification -eq "unknown") {
    $operation = "blocked"
    $reason = "Purpose and ownership are not proven."
    $risk = "Moving unknown data may cause loss or break an unrelated application."
    $rollback = "Not applicable because execution is blocked."
  }

  $actions.Add([pscustomobject]@{
    action_id = "A{0:D3}" -f $index
    source = $source
    target = $target
    classification = $classification
    operation = $operation
    reason = $reason
    risk = $risk
    prerequisites = @("Re-audit source state", "Confirm target is expected and writable", "Stop the owning tool when required")
    verification = @("Check source and target state", "Check link or tool configuration", "Confirm new writes use the target")
    rollback = $rollback
    irreversible = $false
    approved = $false
  })
}

$plan = [ordered]@{
  schema_version = "1.0"
  report_type = "plan"
  report_id = "plan-$([DateTimeOffset]::Now.ToString('yyyyMMdd-HHmmss'))"
  source_report_id = [string]$audit.report_id
  generated_at = [DateTimeOffset]::Now.ToString("o")
  mode = "plan"
  status = if (@($actions | Where-Object operation -eq "blocked").Count -gt 0) { "WARNING" } else { "PASS" }
  target_root = $resolvedTargetRoot
  actions = @($actions)
  warnings = @("This plan does not authorize or execute migration actions.")
  errors = @()
}

$json = $plan | ConvertTo-Json -Depth 8
if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
  $resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
  $parent = Split-Path -Parent $resolvedOutput
  if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
    throw "[ERROR] Output parent does not exist: $parent"
  }
  [System.IO.File]::WriteAllText($resolvedOutput, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}

$json
