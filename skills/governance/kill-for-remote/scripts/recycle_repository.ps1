[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$LiteralPath
)

$item = Get-Item -Force -LiteralPath $LiteralPath -ErrorAction Stop
if (-not $item.PSIsContainer) {
    throw "Retirement target is not a directory."
}
if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Retirement target is a reparse point."
}

Add-Type -AssemblyName Microsoft.VisualBasic
[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory(
    $item.FullName,
    [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,
    [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin
)
