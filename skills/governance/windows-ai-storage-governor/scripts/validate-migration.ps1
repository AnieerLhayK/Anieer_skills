[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$PlanPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $PlanPath -PathType Leaf)) {
  throw "[ERROR] Missing required migration plan: $PlanPath"
}

$plan = Get-Content -Raw -LiteralPath $PlanPath -Encoding UTF8 | ConvertFrom-Json
if ([string]$plan.report_type -ne "plan") {
  throw "[ERROR] Input is not a migration plan: $PlanPath"
}

$results = foreach ($action in @($plan.actions)) {
  $sourceExists = Test-Path -LiteralPath ([string]$action.source)
  $targetExists = -not [string]::IsNullOrWhiteSpace([string]$action.target) -and
    (Test-Path -LiteralPath ([string]$action.target))
  $linkState = "not-a-link"
  if ($sourceExists) {
    $sourceItem = Get-Item -LiteralPath ([string]$action.source) -Force
    if (-not [string]::IsNullOrWhiteSpace([string]$sourceItem.LinkType)) {
      $actualTarget = [string]($sourceItem.Target | Select-Object -First 1)
      $linkState = if (-not [string]::IsNullOrWhiteSpace([string]$action.target) -and
        [System.IO.Path]::GetFullPath($actualTarget).TrimEnd('\') -ieq
        [System.IO.Path]::GetFullPath([string]$action.target).TrimEnd('\')) {
        "correct"
      } else {
        "different-target"
      }
    }
  }

  $status = "WARNING"
  $message = "Planned action has not been applied or cannot be proven from path state alone."
  if ([string]$action.operation -in @("preserve", "report-only", "blocked")) {
    $status = "PASS"
    $message = "No migration state is required for this action."
  } elseif ($targetExists -and $linkState -eq "correct") {
    $status = "PASS"
    $message = "Target exists and source link resolves to the planned target."
  }

  [pscustomobject]@{
    action_id = [string]$action.action_id
    source_state = if ($sourceExists) { "present" } else { "missing" }
    target_state = if ($targetExists) { "present" } else { "missing" }
    link_state = $linkState
    command_state = "not-checked"
    residual_write_state = "not-checked"
    status = $status
    message = $message
  }
}

$overall = if (@($results | Where-Object status -ne "PASS").Count -gt 0) { "WARNING" } else { "PASS" }
[ordered]@{
  schema_version = "1.0"
  report_type = "verify"
  report_id = "verify-$([DateTimeOffset]::Now.ToString('yyyyMMdd-HHmmss'))"
  source_report_id = [string]$plan.report_id
  generated_at = [DateTimeOffset]::Now.ToString("o")
  mode = "verify"
  status = $overall
  target_root = [string]$plan.target_root
  results = @($results)
  warnings = @("Command health and live residual writes require tool-specific checks.")
  errors = @()
} | ConvertTo-Json -Depth 8
