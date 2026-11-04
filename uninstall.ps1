param(
  [switch]$Yes,
  [switch]$DeleteData,
  [switch]$DeleteModels
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$targets = @(".venv")
if ($DeleteData) {
  $targets += @("logs", "clips", "config.toml", "monitor.pid", "monitor.log", "monitor.log.1")
}
if ($DeleteModels) {
  $targets += @("models")
}

$desktop = [Environment]::GetFolderPath("Desktop")
$programs = [Environment]::GetFolderPath("Programs")
$links = @()
if ($desktop) { $links += (Join-Path $desktop "Audio Monitor.lnk") }
if ($programs) { $links += (Join-Path $programs "Audio Monitor.lnk") }

Write-Output "Uninstall would remove, inside this folder only:"
$targets | ForEach-Object { Write-Output ("  " + $_) }
foreach ($item in $links) { Write-Output ("Shortcut: " + $item) }
if (-not $DeleteData) { Write-Output "Logs, clips, and config.toml are kept. Pass -DeleteData to remove them." }
if (-not $DeleteModels) { Write-Output "The models folder is kept. Pass -DeleteModels to remove downloaded weights." }
Write-Output "A custom model_path outside this folder is never deleted."
Write-Output "The program files are not deleted. Delete this folder yourself after uninstalling."

if (-not $Yes) {
  Write-Output "Nothing was removed. Re-run with -Yes to do it."
  exit 0
}

& (Join-Path $Root "stop.ps1")
foreach ($name in $targets) {
  $path = Join-Path $Root $name
  if (Test-Path $path) {
    Remove-Item -LiteralPath $path -Recurse -Force
    Write-Output "Removed $name"
  }
}
foreach ($item in $links) {
  if (Test-Path -LiteralPath $item) {
    Remove-Item -LiteralPath $item -Force
    Write-Output "Removed shortcut $item"
  }
}
Write-Output "Uninstall finished."
exit 0
