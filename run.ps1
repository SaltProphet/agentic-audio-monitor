$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
  Write-Error "Nothing is installed yet. Run preflight.bat, read the list, then run install.bat."
}
$Config = Join-Path $Root "config.toml"
if (-not (Test-Path $Config)) {
  Copy-Item (Join-Path $Root "config.example.toml") $Config
}
$nv = Join-Path $Root ".venv\Lib\site-packages\nvidia"
$env:PATH = "$nv\cublas\bin;$nv\cudnn\bin;$env:PATH"
& $Py -m monitor run --config $Config
if ($LASTEXITCODE -ne 0) {
  Write-Output "Exited with code $LASTEXITCODE"
  Read-Host "Press Enter to close"
}
exit $LASTEXITCODE
