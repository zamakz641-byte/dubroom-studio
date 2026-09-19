$ErrorActionPreference = "Stop"

function Set-DubProgress {
  param([int]$Progress, [string]$Message, [string]$Phase = "install")
  if (-not $env:DUB_ENGINE_STATE) { return }
  $status = if ($env:DUB_ENGINE_REPAIR -eq "1") { "repairing" } else { "installing" }
  $payload = @{status=$status;progress=$Progress;message=$Message;phase=$Phase;log_path=$env:DUB_ENGINE_LOG;updated_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json
  Set-Content -LiteralPath $env:DUB_ENGINE_STATE -Value $payload -Encoding UTF8
}

$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$modelRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_MODELS)
$environmentsRoot = Split-Path -Parent $engineRoot
$sharedPython = Join-Path $environmentsRoot "whisperx-alignment\venv\Scripts\python.exe"
$dedicatedPython = Join-Path $engineRoot "venv\Scripts\python.exe"
New-Item -ItemType Directory -Path $engineRoot,$modelRoot,$env:DUB_ENGINE_CACHE -Force | Out-Null

Set-DubProgress 12 "Recherche du runtime Pyannote commun" "runtime"
$pythonExe = $null
$provider = "pyannote-community"
if (Test-Path -LiteralPath $sharedPython) {
  & $sharedPython -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('pyannote.audio') else 1)"
  if ($LASTEXITCODE -eq 0) {
    $pythonExe = $sharedPython
    $provider = "whisperx-alignment"
  }
}

if (-not $pythonExe) {
  Set-DubProgress 20 "Creation du runtime Pyannote isole" "venv"
  if (-not (Test-Path -LiteralPath $dedicatedPython)) {
    & $env:DUB_BASE_PYTHON -m venv (Join-Path $engineRoot "venv")
  }
  $pythonExe = $dedicatedPython
  Set-DubProgress 30 "Installation de Pyannote" "runtime"
  & $pythonExe -m pip install --upgrade pip wheel setuptools
  & $pythonExe -m pip install "pyannote.audio>=4,<5" "huggingface-hub>=0.30,<2"
  if ($LASTEXITCODE -ne 0) { throw "L'installation de Pyannote a echoue." }
} else {
  Set-DubProgress 30 "Runtime WhisperX/Pyannote reutilise sans reinstallation" "runtime"
  & $pythonExe -m pip show huggingface-hub | Out-Null
  if ($LASTEXITCODE -ne 0) {
    & $pythonExe -m pip install "huggingface-hub>=0.30,<2"
  }
}

if (-not $env:HF_TOKEN) {
  throw "Jeton Hugging Face requis. Acceptez les conditions de pyannote/speaker-diarization-community-1 puis fournissez le jeton dans DubRoom."
}

Set-DubProgress 42 "Telechargement du modele Community-1 autorise" "download"
$env:DUB_MODEL_LOCAL_SUBDIR = "snapshot"
$env:DUB_HELPER_KIND = "generic"
& $pythonExe (Join-Path $PSScriptRoot "download-huggingface-model.py")
if ($LASTEXITCODE -ne 0) {
  throw "Le modele Community-1 n'a pas pu etre telecharge. Verifiez le jeton et les conditions Hugging Face."
}

Set-DubProgress 94 "Validation du pipeline Pyannote local" "validate"
$modelManifest = Get-Content -LiteralPath (Join-Path $modelRoot "model.json") -Raw | ConvertFrom-Json
& $pythonExe -c "from pyannote.audio import Pipeline; Pipeline.from_pretrained(r'$($modelManifest.model_path)'); print('pyannote-community-ok')"
if ($LASTEXITCODE -ne 0) { throw "La validation locale de Pyannote Community-1 a echoue." }

$ready = @{
  engine_id = $env:DUB_ENGINE_ID
  python = $pythonExe
  execution_provider = $provider
  shared_runtime = ($provider -eq "whisperx-alignment")
  model_path = $modelManifest.model_path
  device = "cpu"
  self_test = "pipeline-local-load"
  installed_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Value $ready -Encoding UTF8
Set-DubProgress 100 "Pyannote Community-1 est pret" "complete"
