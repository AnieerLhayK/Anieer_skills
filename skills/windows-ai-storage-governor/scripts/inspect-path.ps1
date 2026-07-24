[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)]
  [string]$Path,
  [string]$Classification = "",
  [string]$Disposition = "",
  [string]$Evidence = "",
  [string]$Risk = "",
  [string]$Tool = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-Classification {
  param(
    [string]$Name,
    [bool]$IsLink
  )

  if ($IsLink) { return "junction / symlink" }
  $lower = $Name.ToLowerInvariant()
  if ($lower -match '(^|[-_.])(cache|caches)([-_.]|$)') { return "cache" }
  if ($lower -match '(^|[-_.])(tmp|temp|temporary)([-_.]|$)') { return "temp" }
  if ($lower -match '(session|sessions|history|conversation|checkpoint)') { return "session data" }
  if ($lower -match '(config|settings|profile)') { return "configuration" }
  if ($lower -match '(backup|archive|snapshot)') { return "backup" }
  if ($lower -match '(node_modules|src|source|repository|repo)') { return "project source" }
  if ($lower -match '(runtime|data|database|db|models|browsers|ms-playwright)') { return "runtime data" }
  return "unknown"
}

function Get-Disposition {
  param([string]$Classification)

  switch ($Classification) {
    "cache" { return "migrate-candidate" }
    "temp" { return "report-only" }
    "runtime data" { return "migrate-candidate" }
    "junction / symlink" { return "preserve" }
    "project source" { return "preserve" }
    "backup" { return "preserve" }
    "configuration" { return "preserve" }
    "session data" { return "preserve" }
    default { return "blocked" }
  }
}

$expanded = [Environment]::ExpandEnvironmentVariables($Path)
$fullPath = [System.IO.Path]::GetFullPath($expanded)
$exists = Test-Path -LiteralPath $fullPath
$item = $null
$isLink = $false
$linkType = ""
$linkTarget = ""
$pathType = "missing"

if ($exists) {
  $item = Get-Item -LiteralPath $fullPath -Force
  $pathType = if ($item.PSIsContainer) { "directory" } else { "file" }
  $isLink = -not [string]::IsNullOrWhiteSpace([string]$item.LinkType)
  if ($isLink) {
    $linkType = [string]$item.LinkType
    $targetValue = $item.Target
    if ($targetValue -is [array]) {
      $linkTarget = [string]($targetValue | Select-Object -First 1)
    } elseif ($null -ne $targetValue) {
      $linkTarget = [string]$targetValue
    }
  }
}

$resolvedClassification = if ([string]::IsNullOrWhiteSpace($Classification)) {
  Get-Classification -Name ([System.IO.Path]::GetFileName($fullPath)) -IsLink $isLink
} else {
  $Classification
}
$resolvedDisposition = if ([string]::IsNullOrWhiteSpace($Disposition)) {
  Get-Disposition -Classification $resolvedClassification
} else {
  $Disposition
}
$systemRoot = [System.IO.Path]::GetPathRoot([Environment]::GetFolderPath("Windows"))
$pathRoot = [System.IO.Path]::GetPathRoot($fullPath)
$onSystemDrive = -not [string]::IsNullOrWhiteSpace($pathRoot) -and
  $pathRoot.TrimEnd('\') -ieq $systemRoot.TrimEnd('\')
$resolvedEvidence = if (-not [string]::IsNullOrWhiteSpace($Evidence)) {
  $Evidence
} elseif ($exists) {
  "filesystem metadata and conservative name heuristic"
} else {
  "path not found"
}
$resolvedRisk = if (-not [string]::IsNullOrWhiteSpace($Risk)) {
  $Risk
} elseif ($resolvedClassification -eq "unknown") {
  "purpose and ownership are not proven"
} elseif ($onSystemDrive) {
  "system-drive usage observed; no mutation authorized"
} else {
  "no immediate mutation authorized"
}

[pscustomobject]@{
  path = $fullPath
  exists = $exists
  path_type = $pathType
  classification = $resolvedClassification
  disposition = $resolvedDisposition
  link_type = $linkType
  link_target = $linkTarget
  system_drive = $onSystemDrive
  tool = $Tool
  evidence = $resolvedEvidence
  risk = $resolvedRisk
}
