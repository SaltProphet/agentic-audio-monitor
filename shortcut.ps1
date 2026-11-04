param(
  [switch]$Desktop,
  [switch]$StartMenu
)

$ErrorActionPreference = "Stop"
if (-not $PSBoundParameters.ContainsKey("Desktop") -and -not $PSBoundParameters.ContainsKey("StartMenu")) {
  $Desktop = $true
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Target = Join-Path $Root "Audio Monitor.bat"
if (-not (Test-Path -LiteralPath $Target)) {
  Write-Error "Audio Monitor.bat is not in this folder."
}

function New-MonitorShortcut {
  param([string]$Folder, [string]$Name)
  if (-not $Folder) {
    Write-Error "Windows did not report a folder for $Name"
  }
  if (-not (Test-Path -LiteralPath $Folder)) {
    New-Item -ItemType Directory -Path $Folder | Out-Null
  }
  $linkPath = Join-Path $Folder $Name
  $shell = New-Object -ComObject WScript.Shell
  $link = $shell.CreateShortcut($linkPath)
  $link.TargetPath = $Target
  $link.WorkingDirectory = $Root
  $link.WindowStyle = 1
  $link.Description = "Start Audio Monitor"
  $link.Save()
  Write-Output $linkPath
}

if ($Desktop) {
  $desktopDir = [Environment]::GetFolderPath("Desktop")
  Write-Output "Desktop shortcut:"
  New-MonitorShortcut -Folder $desktopDir -Name "Audio Monitor.lnk"
}
if ($StartMenu) {
  $programsDir = [Environment]::GetFolderPath("Programs")
  Write-Output "Start menu shortcut:"
  New-MonitorShortcut -Folder $programsDir -Name "Audio Monitor.lnk"
}
Write-Output "It starts:"
Write-Output $Target
exit 0
