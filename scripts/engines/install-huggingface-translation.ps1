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
$workspaceRoot = Split-Path (Split-Path (Split-Path $engineRoot -Parent) -Parent) -Parent
$sharedCudaLib = Join-Path $workspaceRoot "data\environments\rvc-runtime\venv\Lib\site-packages\torch\lib"
if (Test-Path -LiteralPath $sharedCudaLib) {
  $env:PATH = "$sharedCudaLib;$($env:PATH)"
}
if (-not $env:DUB_MODEL_REPO) { throw "Le depot du modele de traduction n'est pas configure." }
New-Item -ItemType Directory -Path $engineRoot,$modelRoot -Force | Out-Null

$runtimeLock = $null
$runtimeLockPath = Join-Path $engineRoot ".install.lock"
Set-DubProgress 5 "Reservation du runtime de traduction partage" "runtime"
while ($null -eq $runtimeLock) {
  try {
    $runtimeLock = [System.IO.File]::Open(
      $runtimeLockPath,
      [System.IO.FileMode]::OpenOrCreate,
      [System.IO.FileAccess]::ReadWrite,
      [System.IO.FileShare]::None
    )
  } catch [System.IO.IOException] {
    Set-DubProgress 5 "Un autre modele prepare deja ce runtime; attente sans retelechargement" "runtime"
    Start-Sleep -Seconds 2
  }
}

try {
Set-DubProgress 8 "Creation de l'environnement traduction" "venv"
$venvPath = Join-Path $engineRoot "venv"
$basePython = if ($env:DUB_BASE_PYTHON) { $env:DUB_BASE_PYTHON } else { "python" }
if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) { & $basePython -m venv $venvPath }
$pythonExe = Join-Path $venvPath "Scripts\python.exe"

Set-DubProgress 16 "Mise a jour des outils Python" "python"
& $pythonExe -m pip install --upgrade pip wheel setuptools
if ($LASTEXITCODE -ne 0) { throw "Impossible de preparer Python pour la traduction." }

Set-DubProgress 25 "Installation du gestionnaire de modeles" "runtime"
& $pythonExe -m pip install "huggingface-hub>=0.30,<1" sentencepiece
if ($LASTEXITCODE -ne 0) { throw "L'installation du gestionnaire de modeles a echoue." }

Set-DubProgress 32 "Installation du runtime $($env:DUB_MODEL_RUNTIME)" "runtime"
if ($env:DUB_MODEL_RUNTIME -eq "llama_cpp") {
  $hasNvidia = [bool](Get-Command "nvidia-smi" -ErrorAction SilentlyContinue)
  if ($hasNvidia) {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $pythonExe -c "import sys; from llama_cpp import llama_supports_gpu_offload; sys.exit(0 if llama_supports_gpu_offload() else 1)" 2>$null
    $llamaCudaReady = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $previousErrorAction
    if ($llamaCudaReady) {
      Set-DubProgress 32 "Runtime llama.cpp CUDA partage deja pret" "runtime"
    } else {
      & $pythonExe -m pip install --upgrade --force-reinstall --no-deps `
        --index-url https://abetlen.github.io/llama-cpp-python/whl/cu125 `
        "llama-cpp-python>=0.3.22,<1"
    }
  } else {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $pythonExe -c "import llama_cpp" 2>$null
    $llamaCpuReady = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $previousErrorAction
    if (-not $llamaCpuReady) {
      & $pythonExe -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
    }
  }
} elseif ($env:DUB_MODEL_RUNTIME -eq "ctranslate2") {
  & $pythonExe -m pip install "ctranslate2>=4.6,<5" "transformers>=4.51,<5"
} elseif ($env:DUB_MODEL_RUNTIME -eq "transformers") {
  & $pythonExe -m pip install "torch>=2.6" "transformers>=4.51,<5" accelerate safetensors
} elseif ($env:DUB_MODEL_RUNTIME -eq "onnx") {
  & $pythonExe -m pip install "torch>=2.6" "transformers>=4.51,<5" "optimum[onnxruntime]>=1.24" onnx
} else {
  throw "Runtime de traduction inconnu: $($env:DUB_MODEL_RUNTIME)"
}
if ($LASTEXITCODE -ne 0) { throw "L'installation du runtime de traduction a echoue." }

Set-DubProgress 38 "Preparation du telechargement modele" "download"
$env:DUB_HELPER_KIND = "translation"
& $pythonExe (Join-Path $PSScriptRoot "download-huggingface-model.py")
if ($LASTEXITCODE -ne 0) { throw "Le telechargement ou l'export du modele a echoue." }
} finally {
  if ($null -ne $runtimeLock) {
    $runtimeLock.Dispose()
  }
}
