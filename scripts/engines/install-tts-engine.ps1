$ErrorActionPreference = "Stop"

$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$modelRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_MODELS)
$workspaceRoot = Split-Path (Split-Path (Split-Path $engineRoot -Parent) -Parent) -Parent
$toolchainRoot = Join-Path $workspaceRoot "data\toolchains"
$uvRoot = Join-Path $toolchainRoot "uv"
$pythonRoot = Join-Path $toolchainRoot "python"
$uvExe = Join-Path $uvRoot "uv.exe"
$runtimeRoot = if ($env:DUB_TTS_RUNTIME_ENV) { [System.IO.Path]::GetFullPath($env:DUB_TTS_RUNTIME_ENV) } else { $engineRoot }
$venvPath = Join-Path $runtimeRoot "venv"
$pythonVersion = if ($env:DUB_TTS_PYTHON) { $env:DUB_TTS_PYTHON } else { "3.12" }
$family = $env:DUB_TTS_FAMILY
$package = $env:DUB_TTS_PACKAGE

New-Item -ItemType Directory -Path $engineRoot,$runtimeRoot,$modelRoot,$uvRoot,$pythonRoot -Force | Out-Null

function Set-DubProgress {
  param([int]$Progress, [string]$Message)
  if (-not $env:DUB_ENGINE_STATE) { return }
  $status = if ($env:DUB_ENGINE_REPAIR -eq "1") { "repairing" } else { "installing" }
  $payload = @{
    status = $status
    progress = $Progress
    message = $Message
    log_path = $env:DUB_ENGINE_LOG
    updated_at = (Get-Date).ToUniversalTime().ToString("o")
  } | ConvertTo-Json
  for ($attempt = 0; $attempt -lt 3; $attempt++) {
    try { Set-Content -LiteralPath $env:DUB_ENGINE_STATE -Value $payload -Encoding UTF8; return }
    catch { Start-Sleep -Milliseconds (50 * ($attempt + 1)) }
  }
}

function Invoke-UvPip {
  param([string[]]$Arguments, [string]$FailureMessage)
  for ($attempt = 1; $attempt -le 3; $attempt++) {
    & $uvExe pip install --python $pythonExe @Arguments
    if ($LASTEXITCODE -eq 0) { return }
    if ($attempt -lt 3) { Start-Sleep -Seconds (4 * $attempt) }
  }
  throw $FailureMessage
}

$runtimeLock = $null
$runtimeLockPath = Join-Path $runtimeRoot ".install.lock"
Set-DubProgress 5 "Reservation du runtime partage de la famille $family"
while ($null -eq $runtimeLock) {
  try {
    $runtimeLock = [System.IO.File]::Open(
      $runtimeLockPath,
      [System.IO.FileMode]::OpenOrCreate,
      [System.IO.FileAccess]::ReadWrite,
      [System.IO.FileShare]::None
    )
  } catch [System.IO.IOException] {
    Set-DubProgress 5 "Un autre modele $family prepare deja le runtime partage"
    Start-Sleep -Seconds 2
  }
}

try {
Set-DubProgress 6 "Preparation du runtime TTS partage"
if (-not (Test-Path -LiteralPath $uvExe)) {
  $env:UV_UNMANAGED_INSTALL = $uvRoot
  $installer = Invoke-RestMethod "https://astral.sh/uv/install.ps1"
  Invoke-Expression $installer
}
if (-not (Test-Path -LiteralPath $uvExe)) { throw "Le gestionnaire Python portable n'a pas pu etre prepare." }

$env:UV_PYTHON_INSTALL_DIR = $pythonRoot
$env:UV_CACHE_DIR = Join-Path $workspaceRoot "data\cache\uv"
$env:UV_LINK_MODE = "hardlink"
$env:UV_HTTP_TIMEOUT = "300"
$env:UV_HTTP_RETRIES = "8"
$env:UV_CONCURRENT_DOWNLOADS = "2"
$env:HF_HOME = if ($env:HF_HOME) { $env:HF_HOME } else { Join-Path $workspaceRoot "data\cache\huggingface" }
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) {
  & $uvExe venv --python $pythonVersion $venvPath
  if ($LASTEXITCODE -ne 0) { throw "Impossible de creer Python $pythonVersion pour $family." }
}
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
Set-DubProgress 18 "Python $pythonVersion pret"

Invoke-UvPip -Arguments @("wheel", "setuptools", "soundfile", "huggingface-hub>=0.32") -FailureMessage "Impossible d'installer les dependances TTS communes."
Set-DubProgress 28 "Dependances communes pretes"

$hasNvidia = @(Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match "NVIDIA" }).Count -gt 0
if ($family -in @("qwen3", "luxtts", "tada")) {
  Set-DubProgress 34 "Telechargement PyTorch CUDA (plusieurs Go, veuillez patienter)"
  $torchIndex = if ($hasNvidia) { "https://download.pytorch.org/whl/cu128" } else { "https://download.pytorch.org/whl/cpu" }
  Invoke-UvPip -Arguments @("torch", "torchaudio", "--index-url", $torchIndex) -FailureMessage "Impossible d'installer PyTorch pour $family."
}
if ($family -eq "chatterbox") {
  $torchIndex = if ($hasNvidia) { "https://download.pytorch.org/whl/cu124" } else { "https://download.pytorch.org/whl/cpu" }
  Invoke-UvPip -Arguments @("torch==2.6.0", "torchaudio==2.6.0", "--index-url", $torchIndex) -FailureMessage "Impossible d'installer PyTorch pour Chatterbox."
}
Set-DubProgress 46 "Acceleration materielle preparee"

if ($family -eq "kokoro") {
  Set-DubProgress 50 "Preparation des langues Kokoro"
  Invoke-UvPip -Arguments @(
    "pyopenjtalk-plus==0.4.1.post8",
    "fugashi>=1.4.0",
    "misaki[en,zh]",
    "https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"
  ) -FailureMessage "Impossible de preparer les langues Kokoro."
}
$engineInstallArguments = @($package)
if ($family -eq "chatterbox") {
  # The official Chatterbox project deliberately pins an older, mutually
  # compatible PyTorch/NumPy stack. A constraints file prevents a transitive
  # dependency (notably Perth) from silently upgrading that stack later.
  $constraintsPath = Join-Path $runtimeRoot "constraints-chatterbox.txt"
  @'
numpy==1.26.4
torch==2.6.0
torchaudio==2.6.0
transformers==5.2.0
librosa==0.11.0
diffusers==0.29.0
conformer==0.3.2
safetensors==0.5.3
pykakasi==2.3.0
'@ | Set-Content -LiteralPath $constraintsPath -Encoding UTF8
  $constraintsArgument = Resolve-Path -LiteralPath $constraintsPath -Relative
  $engineInstallArguments += @("--constraint", $constraintsArgument)
}
Invoke-UvPip -Arguments $engineInstallArguments -FailureMessage "L'installation du moteur $family a echoue."
if ($family -eq "qwen3" -and $hasNvidia) {
  Set-DubProgress 64 "Installation de l'acceleration Qwen CUDA Graphs"
  Invoke-UvPip -Arguments @("faster-qwen3-tts==0.3.2") -FailureMessage "Impossible d'installer l'acceleration Qwen CUDA Graphs."
}
Set-DubProgress 68 "Moteur $family installe"

$downloadScript = @'
import json
import os
from pathlib import Path

family = os.environ["DUB_TTS_FAMILY"]
repo_id = os.environ["DUB_MODEL_REPO"]
model_root = Path(os.environ["DUB_ENGINE_MODELS"])
local = model_root / "model"
local.mkdir(parents=True, exist_ok=True)

if family == "supertonic":
    from supertonic import TTS
    TTS(model_dir=local, auto_download=True)
else:
    from huggingface_hub import snapshot_download
    snapshot_download(
        repo_id=repo_id,
        revision=os.environ.get("DUB_MODEL_REVISION") or "main",
        local_dir=local,
        token=os.environ.get("HF_TOKEN") or None,
    )
    if family == "tada":
        codec = model_root / "codec"
        codec.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id="HumeAI/tada-codec",
            revision="main",
            local_dir=codec,
            token=os.environ.get("HF_TOKEN") or None,
        )
        # TADA resolves these dependencies by repository name internally.
        # Seed the shared cache now so generation remains local afterwards.
        snapshot_download(
            repo_id="HumeAI/tada-codec",
            revision="main",
            token=os.environ.get("HF_TOKEN") or None,
        )
        llama_size = "3B" if "3b" in repo_id.lower() else "1B"
        snapshot_download(
            repo_id=f"meta-llama/Llama-3.2-{llama_size}",
            revision="main",
            token=os.environ.get("HF_TOKEN") or None,
        )

manifest = {
    "engine_id": os.environ["DUB_ENGINE_ID"],
    "family": family,
    "repo_id": repo_id,
    "model_path": str(local),
    "runtime": "dubroom-native-tts",
}
(model_root / "model.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
'@
$downloadScriptPath = Join-Path $engineRoot "download-model.py"
if ($family -in @("supertonic", "tada")) {
  Set-DubProgress 69 "Telechargement des poids $family et de ses composants"
  Set-Content -LiteralPath $downloadScriptPath -Value $downloadScript -Encoding UTF8
  & $pythonExe $downloadScriptPath
} else {
  $env:DUB_HELPER_KIND = "tts"
  $env:DUB_MODEL_LOCAL_SUBDIR = "model"
  & $pythonExe (Join-Path $PSScriptRoot "download-huggingface-model.py")
}
if ($LASTEXITCODE -ne 0) { throw "Le telechargement ou la validation des poids $family a echoue." }
Set-DubProgress 91 "Poids locaux verifies"

$importByFamily = @{
  supertonic = "from supertonic import TTS"
  kokoro = "from kokoro import KModel, KPipeline"
  luxtts = "from zipvoice.luxvoice import LuxTTS"
  qwen3 = "from qwen_tts import Qwen3TTSModel; from faster_qwen3_tts import FasterQwen3TTS"
  chatterbox = "from chatterbox.tts_turbo import ChatterboxTurboTTS; from chatterbox.mtl_tts import ChatterboxMultilingualTTS"
  tada = "from tada.modules.encoder import Encoder; from tada.modules.tada import TadaForCausalLM"
}
& $pythonExe -c $importByFamily[$family]
if ($LASTEXITCODE -ne 0) { throw "Le test d'import du moteur $family a echoue." }
if ($family -eq "chatterbox") {
  & $uvExe pip check --python $pythonExe
  if ($LASTEXITCODE -ne 0) { throw "Les versions du runtime Chatterbox sont incompatibles." }
  & $pythonExe -c "import inspect,numpy,torch,torchaudio,perth; from chatterbox.mtl_tts import ChatterboxMultilingualTTS; assert numpy.__version__ == '1.26.4'; assert torch.__version__.startswith('2.6.0'); assert torchaudio.__version__.startswith('2.6.0'); assert 't3_model' in inspect.signature(ChatterboxMultilingualTTS.from_local).parameters; perth.PerthImplicitWatermarker()"
  if ($LASTEXITCODE -ne 0) { throw "Le runtime Chatterbox officiel ou le watermarker Perth n'est pas utilisable." }
}

$ready = @{
  engine_id = $env:DUB_ENGINE_ID
  family = $family
  python = $pythonExe
  model = (Join-Path $modelRoot "model")
  self_test = "native-worker-import-and-model-validation"
  installed_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Value $ready -Encoding UTF8
if ($engineRoot -ne $runtimeRoot) {
  $runtimeReady = @{
    runtime_id = (Split-Path $runtimeRoot -Leaf)
    family = $family
    python = $pythonExe
    compatibility = if ($family -eq "chatterbox") { "python3.11-torch2.6-cu124" } elseif ($family -eq "qwen3") { "python3.12-torch-cu128-cuda-graphs" } else { "family-isolated" }
    validated_at = (Get-Date).ToUniversalTime().ToString("o")
  } | ConvertTo-Json
  Set-Content -LiteralPath (Join-Path $runtimeRoot "ready.json") -Value $runtimeReady -Encoding UTF8
}
Set-DubProgress 98 "Moteur TTS natif pret"
} finally {
  if ($null -ne $runtimeLock) {
    $runtimeLock.Dispose()
  }
}
