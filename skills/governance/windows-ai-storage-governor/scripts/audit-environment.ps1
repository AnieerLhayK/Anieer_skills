[CmdletBinding()]
param(
  [string[]]$Paths = @(),
  [string]$TargetRoot = "",
  [string]$OutputPath = "",
  [switch]$IncludeKnownCandidates
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$inspectScript = Join-Path $PSScriptRoot "inspect-path.ps1"
if (-not (Test-Path -LiteralPath $inspectScript -PathType Leaf)) {
  throw "[ERROR] Missing required script: $inspectScript"
}

function Get-NormalizedPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  return [System.IO.Path]::GetFullPath(
    [Environment]::ExpandEnvironmentVariables($Path)
  )
}

function Test-SystemDrive {
  param([Parameter(Mandatory = $true)][string]$Path)

  $systemRoot = [System.IO.Path]::GetPathRoot(
    [Environment]::GetFolderPath("Windows")
  )
  $pathRoot = [System.IO.Path]::GetPathRoot((Get-NormalizedPath -Path $Path))
  return -not [string]::IsNullOrWhiteSpace($pathRoot) -and
    $pathRoot.TrimEnd('\') -ieq $systemRoot.TrimEnd('\')
}

function Get-EnvironmentValue {
  param([Parameter(Mandatory = $true)][string]$Name)

  foreach ($scope in @("Process", "User", "Machine")) {
    $value = [Environment]::GetEnvironmentVariable($Name, $scope)
    if (-not [string]::IsNullOrWhiteSpace($value)) {
      return [pscustomobject]@{ Value = [string]$value; Scope = $scope }
    }
  }
  return [pscustomobject]@{ Value = ""; Scope = "" }
}

function Test-PlaywrightRegistrationDirectory {
  param([Parameter(Mandatory = $true)][string]$Path)

  if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return $false }
  $top = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)
  if ($top.Count -ne 1 -or -not $top[0].PSIsContainer -or $top[0].Name -ne "b") {
    return $false
  }
  $records = @(Get-ChildItem -LiteralPath $top[0].FullName -File -Force -ErrorAction SilentlyContinue)
  return $records.Count -gt 0 -and
    @($records | Where-Object { $_.Name -notlike "browser@*" }).Count -eq 0
}

function Test-UsablePathValue {
  param([AllowEmptyString()][string]$Value)

  if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
  if ($Value -in @("undefined", "null")) { return $false }
  try {
    [void](Get-NormalizedPath -Path $Value)
    return $true
  } catch {
    return $false
  }
}

$candidateMap = @{}
function Add-Candidate {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$Classification = "",
    [string]$Disposition = "",
    [string]$Evidence = "",
    [string]$Risk = "",
    [string]$Tool = ""
  )

  if ([string]::IsNullOrWhiteSpace($Path)) { return }
  $normalized = Get-NormalizedPath -Path $Path
  $candidateMap[$normalized.ToLowerInvariant()] = [pscustomobject]@{
    Path = $normalized
    Classification = $Classification
    Disposition = $Disposition
    Evidence = $Evidence
    Risk = $Risk
    Tool = $Tool
  }
}

foreach ($candidate in $Paths) {
  Add-Candidate -Path $candidate -Evidence "user-supplied audit path"
}

$warnings = [System.Collections.Generic.List[string]]::new()
$commands = [System.Collections.Generic.List[object]]::new()

if ($IncludeKnownCandidates) {
  $geminiCommand = Get-Command gemini -ErrorAction SilentlyContinue
  $commands.Add([pscustomobject]@{
    command = "gemini"
    found = $null -ne $geminiCommand
    source = if ($null -eq $geminiCommand) { "" } else { [string]$geminiCommand.Source }
  })
  if ($null -eq $geminiCommand) {
    $warnings.Add("optional command not found: gemini")
  }

  $geminiHome = Get-EnvironmentValue -Name "GEMINI_CLI_HOME"
  $geminiRoot = if (-not [string]::IsNullOrWhiteSpace($geminiHome.Value)) {
    $geminiHome.Value
  } else {
    $env:USERPROFILE
  }
  if (-not [string]::IsNullOrWhiteSpace($geminiRoot)) {
    Add-Candidate `
      -Path (Join-Path $geminiRoot ".gemini") `
      -Tool "gemini" `
      -Evidence "Gemini CLI user storage root resolved from GEMINI_CLI_HOME or USERPROFILE" `
      -Risk "Mixed configuration, authentication references, history, cache, and runtime state; preserve unless a tool-aware plan is approved."
  }

  if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
    Add-Candidate -Path (Join-Path $env:USERPROFILE ".codex") -Tool "codex"
    Add-Candidate -Path (Join-Path $env:USERPROFILE ".claude") -Tool "claude"
  }
  if (-not [string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
    Add-Candidate -Path $env:CODEX_HOME -Tool "codex"
  }

  $playwrightCommand = Get-Command playwright -ErrorAction SilentlyContinue
  $commands.Add([pscustomobject]@{
    command = "playwright"
    found = $null -ne $playwrightCommand
    source = if ($null -eq $playwrightCommand) { "" } else { [string]$playwrightCommand.Source }
  })
  if ($null -eq $playwrightCommand) {
    $warnings.Add("optional command not found: playwright; browser paths can still be inspected")
  }

  $playwrightHome = Get-EnvironmentValue -Name "PLAYWRIGHT_BROWSERS_PATH"
  if (-not [string]::IsNullOrWhiteSpace($playwrightHome.Value) -and
      $playwrightHome.Value -ne "0") {
    $playwrightDisposition = if (Test-SystemDrive -Path $playwrightHome.Value) {
      "migrate-candidate"
    } else {
      "preserve"
    }
    Add-Candidate `
      -Path $playwrightHome.Value `
      -Classification "runtime data" `
      -Disposition $playwrightDisposition `
      -Tool "playwright" `
      -Evidence "PLAYWRIGHT_BROWSERS_PATH from $($playwrightHome.Scope) environment scope" `
      -Risk "Browser binaries and MCP browser runtime data; verify the owning Playwright installation before changes."
  }

  if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    $defaultPlaywright = Join-Path $env:LOCALAPPDATA "ms-playwright"
    if (Test-PlaywrightRegistrationDirectory -Path $defaultPlaywright) {
      Add-Candidate `
        -Path $defaultPlaywright `
        -Classification "runtime data" `
        -Disposition "report-only" `
        -Tool "playwright" `
        -Evidence "bounded shape check found only b/browser@* registration records" `
        -Risk "Small live registration metadata may support browser tracking or garbage collection; preserve."
    } else {
      Add-Candidate `
        -Path $defaultPlaywright `
        -Classification "runtime data" `
        -Disposition $(if (Test-SystemDrive -Path $defaultPlaywright) { "migrate-candidate" } else { "preserve" }) `
        -Tool "playwright" `
        -Evidence "Playwright default Windows browser-storage candidate"
    }
  }

  $npm = Get-Command npm -ErrorAction SilentlyContinue
  $commands.Add([pscustomobject]@{
    command = "npm"
    found = $null -ne $npm
    source = if ($null -eq $npm) { "" } else { [string]$npm.Source }
  })
  if ($null -ne $npm) {
    $npmCache = (& $npm.Source config get cache 2>$null | Select-Object -First 1)
    if (Test-UsablePathValue -Value ([string]$npmCache)) {
      Add-Candidate `
        -Path ([string]$npmCache) `
        -Classification "cache" `
        -Disposition $(if (Test-SystemDrive -Path ([string]$npmCache)) { "migrate-candidate" } else { "preserve" }) `
        -Tool "npm" `
        -Evidence "npm config get cache" `
        -Risk "Re-creatable package cache; preserve current location when already off the system drive."
    } else {
      $warnings.Add("npm config get cache did not return a usable path")
    }

    $npmPrefix = (& $npm.Source config get prefix 2>$null | Select-Object -First 1)
    if (Test-UsablePathValue -Value ([string]$npmPrefix)) {
      Add-Candidate `
        -Path ([string]$npmPrefix) `
        -Classification "runtime data" `
        -Disposition $(if (Test-SystemDrive -Path ([string]$npmPrefix)) { "migrate-candidate" } else { "preserve" }) `
        -Tool "npm" `
        -Evidence "npm config get prefix; global executables and package installation root" `
        -Risk "Global commands depend on this path and PATH resolution; preserve when already off the system drive."
    } else {
      $warnings.Add("npm config get prefix did not return a usable path")
    }

    $npmGlobalRoot = (& $npm.Source root --global 2>$null | Select-Object -First 1)
    if (Test-UsablePathValue -Value ([string]$npmGlobalRoot)) {
      Add-Candidate `
        -Path ([string]$npmGlobalRoot) `
        -Classification "runtime data" `
        -Disposition $(if (Test-SystemDrive -Path ([string]$npmGlobalRoot)) { "migrate-candidate" } else { "preserve" }) `
        -Tool "npm" `
        -Evidence "npm root --global; global package installation data, not project source" `
        -Risk "Installed global packages are executable runtime data; verify command resolution after any approved change."
    }
  } else {
    $warnings.Add("optional command not found: npm")
  }
}

$findings = @(
  $candidateMap.Values |
    Sort-Object Path |
    ForEach-Object {
      & $inspectScript `
        -Path $_.Path `
        -Classification $_.Classification `
        -Disposition $_.Disposition `
        -Evidence $_.Evidence `
        -Risk $_.Risk `
        -Tool $_.Tool
    }
)
$status = if ($warnings.Count -gt 0) { "WARNING" } else { "PASS" }
$report = [ordered]@{
  schema_version = "1.0"
  report_type = "audit"
  report_id = "audit-$([DateTimeOffset]::Now.ToString('yyyyMMdd-HHmmss'))"
  generated_at = [DateTimeOffset]::Now.ToString("o")
  mode = "audit"
  status = $status
  target_root = if ([string]::IsNullOrWhiteSpace($TargetRoot)) { "" } else { Get-NormalizedPath -Path $TargetRoot }
  commands = @($commands)
  findings = $findings
  warnings = @($warnings)
  errors = @()
}

$json = $report | ConvertTo-Json -Depth 8
if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
  $resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
  $parent = Split-Path -Parent $resolvedOutput
  if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
    throw "[ERROR] Output parent does not exist: $parent"
  }
  [System.IO.File]::WriteAllText(
    $resolvedOutput,
    $json + [Environment]::NewLine,
    [System.Text.UTF8Encoding]::new($false)
  )
}

$json
