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
$modelRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_MODELS)
if (-not $env:DUB_MODEL_REPO) { throw "Le depot du modele n'est pas configure." }
New-Item -ItemType Directory -Path $engineRoot,$modelRoot -Force | Out-Null

Set-DubProgress 8 "Creation de l'environnement ASR" "venv"
$venvPath = Join-Path $engineRoot "venv"
$basePython = if ($env:DUB_BASE_PYTHON) { $env:DUB_BASE_PYTHON } else { "python" }
if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) {
  & $basePython -m venv $venvPath
}
$pythonExe = Join-Path $venvPath "Scripts\python.exe"

Set-DubProgress 16 "Mise a jour des outils Python" "python"
& $pythonExe -m pip install --upgrade pip wheel setuptools
if ($LASTEXITCODE -ne 0) { throw "Impossible de preparer Python pour ASR." }

$runtime = if ($env:DUB_MODEL_RUNTIME) { $env:DUB_MODEL_RUNTIME } else { "ctranslate2" }
Set-DubProgress 26 "Installation du runtime ASR $runtime" "runtime"
if ($runtime -eq "ctranslate2") {
  & $pythonExe -m pip install "faster-whisper>=1.1,<2" "huggingface-hub>=0.30,<1"
  if (Get-Command "nvidia-smi" -ErrorAction SilentlyContinue) {
    $sharedCuda = if ($env:DUBROOM_WORKSPACE_ROOT) {
      Join-Path $env:DUBROOM_WORKSPACE_ROOT "data\environments\rvc-runtime\venv\Lib\site-packages\torch\lib"
    } else { "" }
    if (
      $sharedCuda -and
      (Test-Path -LiteralPath (Join-Path $sharedCuda "cublas64_12.dll")) -and
      (Test-Path -LiteralPath (Join-Path $sharedCuda "cudnn64_9.dll"))
    ) {
      Set-DubProgress 31 "Reutilisation du runtime NVIDIA partage" "runtime"
    } else {
      Set-DubProgress 31 "Installation de l'acceleration NVIDIA Whisper" "runtime"
      $uvExe = if ($env:DUBROOM_WORKSPACE_ROOT) {
        Join-Path $env:DUBROOM_WORKSPACE_ROOT "data\toolchains\uv\uv.exe"
      } else { "" }
      if ($uvExe -and (Test-Path -LiteralPath $uvExe)) {
        & $uvExe pip install --python $pythonExe "nvidia-cublas-cu12==12.8.4.1" "nvidia-cudnn-cu12==9.8.0.87"
      } else {
        & $pythonExe -m pip install "nvidia-cublas-cu12==12.8.4.1" "nvidia-cudnn-cu12==9.8.0.87"
      }
    }
  }
} elseif ($runtime -eq "transformers") {
  & $pythonExe -m pip install "torch>=2.6" "transformers>=4.51,<5" accelerate librosa soundfile "huggingface-hub>=0.30,<1"
} elseif ($runtime -eq "onnx") {
  & $pythonExe -m pip install "torch>=2.6" "transformers>=4.51,<5" "optimum[onnxruntime]>=1.24" onnx librosa soundfile "huggingface-hub>=0.30,<1"
} else { throw "Runtime ASR inconnu: $runtime" }
if ($LASTEXITCODE -ne 0) { throw "L'installation du runtime ASR a echoue." }

Set-DubProgress 36 "Preparation du telechargement modele" "download"
$env:DUB_HELPER_KIND = "asr"
& $pythonExe (Join-Path $PSScriptRoot "download-huggingface-model.py")
if ($LASTEXITCODE -ne 0) { throw "Le telechargement ou la validation du modele a echoue." }
