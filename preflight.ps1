param(
  [switch]$Install,
  [switch]$Upgrade
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Find-Python {
  $tries = @(
    @{ Exe = "py"; Args = @("-3.12") },
    @{ Exe = "py"; Args = @("-3.11") },
    @{ Exe = "py"; Args = @("-3.13") },
    @{ Exe = "python"; Args = @() }
  )
  foreach ($candidate in $tries) {
    $cmd = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    $code = "import sys; print('%d.%d.%d' % sys.version_info[:3])"
    try {
      $out = & $candidate.Exe @($candidate.Args + @("-c", $code)) 2>$null
    } catch {
      continue
    }
    if ($LASTEXITCODE -ne 0 -or -not $out) { continue }
    $text = ($out | Select-Object -Last 1).ToString().Trim()
    $parts = $text.Split(".")
    if ($parts.Count -lt 2) { continue }
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) { continue }
    if ($major -gt 3 -or $minor -gt 13) { continue }
    return @{ Exe = $candidate.Exe; Args = $candidate.Args; Version = $text }
  }
  return $null
}

Write-Output "Audio Monitor preflight"
Write-Output "This check does not record audio and does not install anything unless -Install is set."
Write-Output ""

$python = Find-Python
if (-not $python) {
  Write-Output "Python: MISSING"
  Write-Output "Install Python 3.12 (3.11 or 3.13 also works) from the usual Windows installer, then run this again."
  Write-Output "Nothing was installed."
  exit 1
}
Write-Output ("Python: {0} ({1})" -f $python.Version, $python.Exe)

$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
  Write-Output "NVIDIA:"
  & nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
} else {
  Write-Output "NVIDIA: nvidia-smi was not found. GPU transcription will refuse to start until a driver is visible."
}

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
$mods = @("numpy", "sounddevice", "pyaudiowpatch", "faster_whisper", "ctranslate2")
if (Test-Path $venvPy) {
  Write-Output "Existing .venv:"
  $check = "import importlib.util`n" + (($mods | ForEach-Object { "print('{0}', 'yes' if importlib.util.find_spec('{0}') else 'no')" -f $_ }) -join "`n")
  & $venvPy -c $check
} else {
  Write-Output "Existing .venv: no"
}

Write-Output ""
Write-Output "Would install into .\.venv only:"
Write-Output "  pip (inside that .venv)"
Get-Content (Join-Path $Root "requirements.txt") | Where-Object { $_ -and -not $_.StartsWith("#") } | ForEach-Object { Write-Output ("  " + $_) }
Write-Output "  plus dependencies already named in requirements.txt (numpy, cffi, ctranslate2, huggingface-hub, tokenizers, onnxruntime, av, tqdm)"
Write-Output "Would not install: a CUDA toolkit, Docker, a system ffmpeg, or a CPU fallback."
Write-Output "First model load may download speech-model weights once into .\models. Later runs stay on disk."

if (-not $Install) {
  Write-Output ""
  Write-Output "No install was performed. Re-run with -Install after you accept the list above."
  exit 0
}

if ((Test-Path $venvPy) -and -not $Upgrade) {
    $probe = & $venvPy -c "import importlib.util; mods=['numpy','sounddevice','pyaudiowpatch','faster_whisper','ctranslate2']; missing=[m for m in mods if importlib.util.find_spec(m) is None]; print(' '.join(missing))"
  if (-not ($probe | Out-String).Trim()) {
    Write-Output "Packages already present. Nothing installed. Pass -Upgrade to reinstall."
    exit 0
  }
}

if (-not (Test-Path $venvPy)) {
  & $python.Exe @($python.Args + @("-m", "venv", (Join-Path $Root ".venv")))
}
& $venvPy -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $venvPy -m pip install -r (Join-Path $Root "requirements.txt")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "Install finished inside .venv."
exit 0
