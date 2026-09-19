$ErrorActionPreference = "Stop"

function Set-DubProgress {
  param([int]$Progress, [string]$Message, [string]$Phase = "install")
  if (-not $env:DUB_ENGINE_STATE) { return }
  $status = if ($env:DUB_ENGINE_REPAIR -eq "1") { "repairing" } else { "installing" }
  $payload = @{status=$status;progress=$Progress;message=$Message;phase=$Phase;log_path=$env:DUB_ENGINE_LOG;updated_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json
  for ($attempt = 0; $attempt -lt 3; $attempt++) {
    try { Set-Content -LiteralPath $env:DUB_ENGINE_STATE -Value $payload -Encoding UTF8; return }
    catch { Start-Sleep -Milliseconds (50 * ($attempt + 1)) }
  }
}

$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$cacheRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_CACHE)
$packages = @($env:DUB_ENGINE_PACKAGES -split ';' | Where-Object { $_.Trim() })
if (-not $engineRoot -or -not $cacheRoot -or $packages.Count -eq 0) { throw "Configuration d'installation incomplete." }

New-Item -ItemType Directory -Path $engineRoot,$cacheRoot -Force | Out-Null
$venvPath = Join-Path $engineRoot "venv"
$basePython = if ($env:DUB_BASE_PYTHON) { $env:DUB_BASE_PYTHON } else { "python" }
Set-DubProgress 10 "Creation de l'environnement Python" "venv"
if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) { & $basePython -m venv $venvPath }
$pythonExe = Join-Path $venvPath "Scripts\python.exe"

Set-DubProgress 20 "Installation des outils Python" "python"
& $pythonExe -m pip install --upgrade pip wheel setuptools
if ($LASTEXITCODE -ne 0) { throw "Impossible de preparer Python." }

Set-DubProgress 32 "Installation des paquets moteur" "runtime"
& $pythonExe -m pip install @packages
if ($LASTEXITCODE -ne 0) { throw "L'installation Python a echoue." }

if ($env:DUB_MODEL_REPO) {
  Set-DubProgress 42 "Preparation du telechargement modele" "download"
  & $pythonExe -m pip install "huggingface-hub>=0.30,<1"
  if ($LASTEXITCODE -ne 0) { throw "L'installation du client de modeles a echoue." }
  $modelRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_MODELS)
  New-Item -ItemType Directory -Path $modelRoot -Force | Out-Null
  $env:DUB_HELPER_KIND = "generic"
  & $pythonExe (Join-Path $PSScriptRoot "download-huggingface-model.py")
  if ($LASTEXITCODE -ne 0) { throw "Le telechargement du modele a echoue. Verifiez le jeton et les conditions d'acces." }
}

Set-DubProgress 92 "Validation de l'environnement" "validate"
& $pythonExe -m pip check
if ($LASTEXITCODE -ne 0) { throw "La validation des paquets Python a echoue." }
if (($packages -join ';') -match 'whisperx') {
  & $pythonExe -c "import whisperx; print('whisperx-ok')"
  if ($LASTEXITCODE -ne 0) { throw "L'import WhisperX a echoue." }
}
$ready = @{engine_id=$env:DUB_ENGINE_ID; packages=$packages; self_test="pip-check"; installed_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Value $ready -Encoding UTF8
