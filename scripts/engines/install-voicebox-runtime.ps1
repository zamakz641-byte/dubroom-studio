$ErrorActionPreference = "Stop"

$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$sourceRoot = if ($env:DUB_VOICEBOX_SOURCE) { [System.IO.Path]::GetFullPath($env:DUB_VOICEBOX_SOURCE) } else { Join-Path $engineRoot "source" }
$toolsRoot = Join-Path $engineRoot "tools"
$pythonRoot = Join-Path $engineRoot "python"
$venvPath = Join-Path $sourceRoot "backend\venv"
New-Item -ItemType Directory -Path $engineRoot,$toolsRoot,$pythonRoot -Force | Out-Null

function Set-DubProgress {
  param([int]$Progress, [string]$Message)
  if (-not $env:DUB_ENGINE_STATE) { return }
  $status = if ($env:DUB_ENGINE_REPAIR -eq "1") { "repairing" } else { "installing" }
  @{status=$status;progress=$Progress;message=$Message;log_path=$env:DUB_ENGINE_LOG;updated_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json | Set-Content -LiteralPath $env:DUB_ENGINE_STATE -Encoding UTF8
}
Set-DubProgress 7 "Préparation de la source Voicebox"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git est requis pour récupérer Voicebox." }
if (Test-Path -LiteralPath (Join-Path $sourceRoot ".git")) {
  & git -C $sourceRoot fetch --all --prune
  & git -C $sourceRoot pull --ff-only
} else {
  & git clone --filter=blob:none https://github.com/jamiepine/voicebox.git $sourceRoot
}
if ($LASTEXITCODE -ne 0) { throw "Impossible de récupérer le runtime Voicebox." }
Set-DubProgress 14 "Source Voicebox synchronisée"

$uvExe = Join-Path $toolsRoot "uv.exe"
if (-not (Test-Path -LiteralPath $uvExe)) {
  $env:UV_UNMANAGED_INSTALL = $toolsRoot
  $installer = Invoke-RestMethod "https://astral.sh/uv/install.ps1"
  Invoke-Expression $installer
}
if (-not (Test-Path -LiteralPath $uvExe)) { throw "L'installation portable de uv a échoué." }
Set-DubProgress 20 "Gestionnaire Python portable prêt"

$env:UV_PYTHON_INSTALL_DIR = $pythonRoot
$env:UV_CACHE_DIR = if ($env:DUB_ENGINE_CACHE) { $env:DUB_ENGINE_CACHE } else { Join-Path $engineRoot "cache" }
$env:UV_HTTP_TIMEOUT = "300"
$env:UV_HTTP_RETRIES = "8"
$env:UV_CONCURRENT_DOWNLOADS = "4"
if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) {
  & $uvExe venv --python 3.12 $venvPath
}
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
function Invoke-UvInstall {
  param([string[]]$Arguments, [string]$FailureMessage)
  for ($attempt = 1; $attempt -le 3; $attempt++) {
    & $uvExe pip install --python $pythonExe @Arguments
    if ($LASTEXITCODE -eq 0) { return }
    if ($attempt -lt 3) { Start-Sleep -Seconds (5 * $attempt) }
  }
  throw $FailureMessage
}

# Prime small dependencies that previously caused a complete multi-gigabyte
# resolution to abort. uv keeps every successful wheel in the portable cache.
Invoke-UvInstall -Arguments @("mpmath==1.3.0", "wheel", "setuptools") -FailureMessage "Impossible de préparer les dépendances Python de base."
Set-DubProgress 28 "Dépendances Python de base prêtes"
$gpuNames = Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name
if (($gpuNames | Where-Object { $_ -match "NVIDIA" }).Count -gt 0) {
  Invoke-UvInstall -Arguments @("torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cu128") -FailureMessage "L'installation de PyTorch CUDA a échoué."
} else {
  Invoke-UvInstall -Arguments @("torch", "torchvision", "torchaudio", "--index-url", "https://download.pytorch.org/whl/cpu") -FailureMessage "L'installation de PyTorch CPU a échoué."
}
Set-DubProgress 48 "Runtime PyTorch installé"
# misaki[ja] normally pulls the source-only pyopenjtalk package. On Windows it
# requires MSVC/NMake. pyopenjtalk-plus is import-compatible and publishes a
# CPython 3.12 wheel, so Japanese support stays available without build tools.
Invoke-UvInstall -Arguments @("pyopenjtalk-plus==0.4.1.post8", "fugashi>=1.4.0") -FailureMessage "Impossible de préparer la synthèse japonaise Voicebox."
$requirementsSource = Join-Path $sourceRoot "backend\requirements.txt"
$requirementsPortable = Join-Path $engineRoot "requirements-windows.txt"
(Get-Content -LiteralPath $requirementsSource -Raw).Replace("misaki[en,ja,zh]", "misaki[en,zh]") | Set-Content -LiteralPath $requirementsPortable -Encoding UTF8
Invoke-UvInstall -Arguments @("-r", $requirementsPortable) -FailureMessage "L'installation des dépendances Voicebox a échoué."
Set-DubProgress 78 "Dépendances Voicebox installées"
Invoke-UvInstall -Arguments @("--no-deps", "chatterbox-tts", "hume-tada") -FailureMessage "L'installation des adaptateurs TTS Voicebox a échoué."
Set-DubProgress 91 "Adaptateurs vocaux installés"

Push-Location $sourceRoot
try {
  & $pythonExe -c "import fastapi, uvicorn, sqlalchemy, pyopenjtalk; from backend.app import app; print('voicebox-runtime-ok')"
  if ($LASTEXITCODE -ne 0) { throw "La validation de l'API Voicebox a échoué." }
} finally { Pop-Location }
Set-DubProgress 97 "Validation finale du runtime"

$ready = @{engine_id=$env:DUB_ENGINE_ID; source=$sourceRoot; python=$pythonExe; installed_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Value $ready -Encoding UTF8
