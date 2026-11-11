$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunScript = Join-Path $Root "run.ps1"

# Start from a clean process set so repeated starts cannot create duplicate monitors.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "stop.ps1")
Start-Sleep -Seconds 1

Start-Process powershell.exe `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $RunScript `
    -WorkingDirectory $Root

# Wait on the page itself, using the port the config actually binds.
$port = 8765
$config = Join-Path $Root "config.toml"
if (Test-Path -LiteralPath $config) {
    $match = Select-String -Path $config -Pattern '^\s*port\s*=\s*(\d+)' | Select-Object -First 1
    if ($match) { $port = [int]$match.Matches[0].Groups[1].Value }
}

$stateUrl = "http://127.0.0.1:$port/api/state"
$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        Invoke-RestMethod -Uri $stateUrl -Method Get -TimeoutSec 1 | Out-Null
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $ready) {
    Write-Error "Audio Monitor did not become ready on port $port."
    exit 1
}

Write-Output "Audio Monitor is running at http://127.0.0.1:$port/"
Write-Output "Closed captions follow the saved setting on the page."
exit 0
