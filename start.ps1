$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunScript = Join-Path $Root "run.ps1"

# Start from a clean process set so repeated starts cannot create duplicate monitors.
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "stop.ps1")
Start-Sleep -Seconds 1

Start-Process powershell.exe `
    -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $RunScript `
    -WorkingDirectory $Root

$ccUrl = "http://127.0.0.1:8765/api/cc"
$ready = $false
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    try {
        $response = Invoke-RestMethod -Uri $ccUrl -Method Get -TimeoutSec 1
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

if (-not $ready) {
    Write-Error "Audio Monitor did not become ready on port 8765."
    exit 1
}

Invoke-RestMethod `
    -Uri $ccUrl `
    -Method Post `
    -ContentType "application/json" `
    -Body '{"enabled":true}' | Out-Null

Write-Output "Audio Monitor and Closed Captions are running."
