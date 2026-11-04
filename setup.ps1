param(
  [switch]$Yes
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Output "Audio Monitor setup"
Write-Output "The report below is only a check. Nothing is installed until you type YES."
Write-Output ""

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "preflight.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $Yes) {
  $answer = Read-Host "Type YES to install those packages and add the Audio Monitor shortcut"
  if ($answer.Trim().ToUpperInvariant() -ne "YES") {
    Write-Output "Nothing was installed."
    exit 0
  }
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "preflight.ps1") -Install
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "shortcut.ps1") -Desktop -StartMenu
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Output ""
Write-Output "Setup finished. The desktop shortcut is Audio Monitor."
Write-Output "The speech model is not downloaded yet. That happens only if you press Load speech model."
$start = Read-Host "Type YES to start Audio Monitor now"
if ($start.Trim().ToUpperInvariant() -eq "YES") {
  Start-Process -FilePath (Join-Path $Root "run.bat") -WorkingDirectory $Root
}
exit 0
