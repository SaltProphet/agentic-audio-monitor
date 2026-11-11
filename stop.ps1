$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root "monitor.pid"
$rootPattern = [regex]::Escape($Root)

# Only stop a recorded pid that still belongs to this folder.
if (Test-Path -LiteralPath $PidFile) {
  $procId = (Get-Content -LiteralPath $PidFile | Select-Object -First 1).Trim()
  if ($procId -match '^\d+$') {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $procId" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -and $process.CommandLine -match $rootPattern) {
      Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
      Write-Output "Stopped monitor pid $procId."
    }
  }
}
Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue

# Also clean up processes left by older launchers or duplicate starts in this folder.
$processes = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq "python.exe" -and $_.CommandLine -and
  $_.CommandLine -match $rootPattern -and
  (($_.CommandLine -match "-m monitor run") -or ($_.CommandLine -match "cc[\\/]companion\.py"))
}
foreach ($process in $processes) {
  Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
  Write-Output "Stopped process $($process.ProcessId)."
}

$supervisors = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq "powershell.exe" -and $_.CommandLine -and
  $_.CommandLine -match [regex]::Escape((Join-Path $Root "run.ps1"))
}
foreach ($supervisor in $supervisors) {
  Stop-Process -Id $supervisor.ProcessId -Force -ErrorAction SilentlyContinue
  Write-Output "Stopped monitor supervisor $($supervisor.ProcessId)."
}

$cmdHosts = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -eq "cmd.exe" -and $_.CommandLine -and
  $_.CommandLine -match [regex]::Escape((Join-Path $Root "run.bat"))
}
foreach ($cmdHost in $cmdHosts) {
  Stop-Process -Id $cmdHost.ProcessId -Force -ErrorAction SilentlyContinue
  Write-Output "Stopped monitor console $($cmdHost.ProcessId)."
}
exit 0
