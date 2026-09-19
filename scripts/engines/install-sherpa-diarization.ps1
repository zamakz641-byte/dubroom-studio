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
$pythonExe = Join-Path $engineRoot "venv\Scripts\python.exe"
$segmentationRoot = Join-Path $modelRoot "segmentation"
$segmentationModel = Join-Path $segmentationRoot "model.int8.onnx"
$embeddingModel = Join-Path $modelRoot "nemo_en_titanet_small.onnx"
New-Item -ItemType Directory -Path $engineRoot,$modelRoot,$segmentationRoot,$env:DUB_ENGINE_CACHE -Force | Out-Null

Set-DubProgress 12 "Création du moteur local sans jeton" "venv"
if (-not (Test-Path -LiteralPath $pythonExe)) {
  & $env:DUB_BASE_PYTHON -m venv (Join-Path $engineRoot "venv")
}

Set-DubProgress 28 "Installation du runtime ONNX léger" "runtime"
& $pythonExe -m pip install --disable-pip-version-check "sherpa-onnx>=1.10.28" soundfile
if ($LASTEXITCODE -ne 0) { throw "L'installation de Sherpa ONNX a échoué." }

if (-not (Test-Path -LiteralPath $segmentationModel)) {
  Set-DubProgress 48 "Téléchargement du détecteur de tours de parole" "download"
  $archive = Join-Path $env:DUB_ENGINE_CACHE "sherpa-segmentation.tar.bz2"
  & curl.exe -L --fail --retry 3 -o $archive "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
  if ($LASTEXITCODE -ne 0) { throw "Le modèle de segmentation Sherpa n'a pas pu être téléchargé." }
  & tar.exe -xf $archive -C $env:DUB_ENGINE_CACHE
  $extracted = Join-Path $env:DUB_ENGINE_CACHE "sherpa-onnx-pyannote-segmentation-3-0\model.int8.onnx"
  Copy-Item -LiteralPath $extracted -Destination $segmentationModel -Force
}

if (-not (Test-Path -LiteralPath $embeddingModel) -or (Get-Item -LiteralPath $embeddingModel).Length -lt 40000000) {
  Set-DubProgress 68 "Téléchargement de l'empreinte vocale multilingue" "download"
  & curl.exe -L --fail --retry 3 -C - -o $embeddingModel "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_small.onnx"
  if ($LASTEXITCODE -ne 0) { throw "Le modèle d'empreinte vocale Sherpa n'a pas pu être téléchargé." }
}
if ((Get-Item -LiteralPath $embeddingModel).Length -lt 40000000) {
  throw "Le modèle d'empreinte vocale Sherpa est incomplet. Relancez Réparer pour reprendre le téléchargement."
}

Set-DubProgress 92 "Validation du moteur multispeaker local" "validate"
& $pythonExe -c "import sherpa_onnx,soundfile; print('sherpa-diarization-ok')"
if ($LASTEXITCODE -ne 0) { throw "La validation Sherpa ONNX a échoué." }

$ready = @{
  engine_id = $env:DUB_ENGINE_ID
  python = $pythonExe
  model_path = $modelRoot
  device = "cpu-onnx"
  requires_token = $false
  installed_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Value $ready -Encoding UTF8
Set-DubProgress 100 "Détection multispeaker locale prête" "complete"
