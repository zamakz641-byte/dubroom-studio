$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Require-Env([string]$Name) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Missing required environment variable: $Name"
    }
    return $value
}

$engineId = Require-Env "DUB_ENGINE_ID"
$basePython = Require-Env "DUB_BASE_PYTHON"
$runtimeRoot = Require-Env "DUB_TTS_RUNTIME_ENV"
$modelRoot = Require-Env "DUB_ENGINE_MODELS"
$repoId = Require-Env "DUB_MODEL_REPO"
$revision = [Environment]::GetEnvironmentVariable("DUB_MODEL_REVISION")
if ([string]::IsNullOrWhiteSpace($revision)) { $revision = "main" }
$packageString = [Environment]::GetEnvironmentVariable("DUB_ENGINE_PACKAGES")
$repair = [Environment]::GetEnvironmentVariable("DUB_ENGINE_REPAIR") -eq "1"
$workspaceRoot = Split-Path (Split-Path $modelRoot -Parent) -Parent
$toolchainRoot = Join-Path $workspaceRoot "data\toolchains"
$uvRoot = Join-Path $toolchainRoot "uv"
$pythonRoot = Join-Path $toolchainRoot "python"
$uvExe = Join-Path $uvRoot "uv.exe"

if ($repoId -ne "ResembleAI/chatterbox") {
    throw "This installer only accepts the official ResembleAI/chatterbox repository"
}

New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
New-Item -ItemType Directory -Force -Path $modelRoot | Out-Null
$venvRoot = Join-Path $runtimeRoot "venv"
$pythonExe = Join-Path $venvRoot "Scripts\python.exe"
$lockPath = Join-Path $runtimeRoot ".install.lock"
$lockStream = $null

try {
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        try {
            $lockStream = [System.IO.File]::Open(
                $lockPath,
                [System.IO.FileMode]::OpenOrCreate,
                [System.IO.FileAccess]::ReadWrite,
                [System.IO.FileShare]::None
            )
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if ($null -eq $lockStream) {
        throw "Timed out waiting for the shared Chatterbox runtime lock"
    }

    # The runtime is shared by Nano/Turbo/Multilingual. Repairing one model must
    # not delete a working shared Python environment used by the other models.
    New-Item -ItemType Directory -Force -Path $uvRoot,$pythonRoot | Out-Null
    if (-not (Test-Path -LiteralPath $uvExe)) {
        $env:UV_UNMANAGED_INSTALL = $uvRoot
        $installer = Invoke-RestMethod "https://astral.sh/uv/install.ps1"
        Invoke-Expression $installer
    }
    if (-not (Test-Path -LiteralPath $uvExe)) {
        throw "The project-local uv installer could not be prepared"
    }
    $env:UV_PYTHON_INSTALL_DIR = $pythonRoot
    $env:UV_CACHE_DIR = Join-Path $workspaceRoot "data\cache\uv"
    $env:UV_LINK_MODE = "hardlink"
    $env:UV_HTTP_TIMEOUT = "300"
    $env:HF_HOME = if ($env:HF_HOME) { $env:HF_HOME } else { Join-Path $workspaceRoot "data\cache\huggingface" }

    if (-not (Test-Path $pythonExe)) {
        Write-Output "Creating shared Chatterbox Python environment..."
        & $uvExe venv --python 3.11 $venvRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create the Chatterbox Python environment"
        }
    }

    $packages = @()
    if (-not [string]::IsNullOrWhiteSpace($packageString)) {
        $packages = $packageString.Split(';', [System.StringSplitOptions]::RemoveEmptyEntries)
    }
    if ($packages.Count -eq 0) {
        $packages = @("chatterbox-tts>=0.1.7")
    }

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

    $hasNvidia = @(Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match "NVIDIA" }).Count -gt 0
    $torchIndex = if ($hasNvidia) { "https://download.pytorch.org/whl/cu124" } else { "https://download.pytorch.org/whl/cpu" }
    Write-Output "Enforcing the official Chatterbox Torch 2.6 compatibility stack..."
    & $uvExe pip install --python $pythonExe "torch==2.6.0" "torchaudio==2.6.0" --index-url $torchIndex
    if ($LASTEXITCODE -ne 0) { throw "Failed to install Chatterbox Torch 2.6" }
    & $uvExe pip install --python $pythonExe @packages --constraint $constraintsArgument
    if ($LASTEXITCODE -ne 0) { throw "Failed to install the pinned official Chatterbox runtime" }
    & $uvExe pip check --python $pythonExe
    if ($LASTEXITCODE -ne 0) { throw "Chatterbox dependency validation failed" }
    & $pythonExe -c "import inspect,numpy,torch,torchaudio,perth; from chatterbox.mtl_tts import ChatterboxMultilingualTTS; assert numpy.__version__ == '1.26.4'; assert torch.__version__.startswith('2.6.0'); assert torchaudio.__version__.startswith('2.6.0'); assert 't3_model' in inspect.signature(ChatterboxMultilingualTTS.from_local).parameters; perth.PerthImplicitWatermarker()"
    if ($LASTEXITCODE -ne 0) { throw "Chatterbox V3 API or Perth validation failed" }

    $target = Join-Path $modelRoot "model"
    $requiredArtifacts = @(
        "ve.pt",
        "t3_mtl23ls_v3.safetensors",
        "s3gen.pt",
        "grapheme_mtl_merged_expanded_v1.json",
        "conds.pt",
        "Cangjie5_TC.json"
    )
    $modelReady = (Test-Path $target) -and @(
        $requiredArtifacts | Where-Object { -not (Test-Path (Join-Path $target $_)) }
    ).Count -eq 0
    # Preserve a complete 3 GB selective V3 download. Only clean a partial or
    # legacy full-repository attempt before resuming the official file set.
    if ((Test-Path $target) -and -not $modelReady) {
        Write-Output "Removing incomplete or oversized Multilingual model files..."
        Remove-Item -Recurse -Force $target
    }
    New-Item -ItemType Directory -Force -Path $target | Out-Null

    $downloadScript = Join-Path $runtimeRoot "download-multilingual-v3.py"
    @'
from __future__ import annotations

import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download

repo = os.environ["DUB_MODEL_REPO"]
revision = os.environ.get("DUB_MODEL_REVISION") or "main"
root = Path(os.environ["DUB_ENGINE_MODELS"]).resolve()
target = root / "model"
target.mkdir(parents=True, exist_ok=True)

# This exact file list mirrors ChatterboxMultilingualTTS.from_pretrained(...,
# t3_model="v3") in the official Resemble AI source. The repository also
# contains English, V2 and duplicate checkpoints, which are not needed here.
artifacts = [
    "ve.pt",
    "t3_mtl23ls_v3.safetensors",
    "s3gen.pt",
    "grapheme_mtl_merged_expanded_v1.json",
    "conds.pt",
    "Cangjie5_TC.json",
]

snapshot_download(
    repo_id=repo,
    repo_type="model",
    revision=revision,
    local_dir=str(target),
    allow_patterns=artifacts,
    token=os.environ.get("HF_TOKEN") or None,
)

missing = [name for name in artifacts if not (target / name).is_file()]
if missing:
    raise SystemExit(
        "Missing Chatterbox Multilingual V3 artifacts: " + ", ".join(missing)
    )

manifest = {
    "engine_id": os.environ["DUB_ENGINE_ID"],
    "repo_id": repo,
    "revision": revision,
    "runtime": "dubroom-native-tts",
    "format": "PyTorch",
    "variant": "multilingual-v3",
    "t3_model": "v3",
    "model_path": str(target),
    "artifacts": artifacts,
    "selective_download": True,
}
(root / "model.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(json.dumps(manifest, ensure_ascii=False))
'@ | Set-Content -Path $downloadScript -Encoding UTF8

    Write-Output "Downloading only Chatterbox Multilingual V3 required files..."
    & $pythonExe $downloadScript
    if ($LASTEXITCODE -ne 0) {
        throw "The selective Chatterbox Multilingual V3 download failed"
    }

    $checkScript = Join-Path $runtimeRoot "validate-multilingual-v3.py"
    @'
from __future__ import annotations

import json
import os
from pathlib import Path

import torch
from chatterbox.mtl_tts import ChatterboxMultilingualTTS

root = Path(os.environ["DUB_ENGINE_MODELS"]).resolve()
model = root / "model"
required = [
    "ve.pt",
    "t3_mtl23ls_v3.safetensors",
    "s3gen.pt",
    "grapheme_mtl_merged_expanded_v1.json",
    "conds.pt",
    "Cangjie5_TC.json",
]
missing = [name for name in required if not (model / name).is_file()]
if missing:
    raise SystemExit("Missing local files: " + ", ".join(missing))

print(json.dumps({
    "torch": torch.__version__,
    "cuda_available": torch.cuda.is_available(),
    "cuda_version": torch.version.cuda,
    "loader": ChatterboxMultilingualTTS.__name__,
    "artifacts": len(required),
}))
'@ | Set-Content -Path $checkScript -Encoding UTF8

    & $pythonExe $checkScript
    if ($LASTEXITCODE -ne 0) {
        throw "Chatterbox Multilingual V3 runtime validation failed"
    }

    $ready = @{
        engine_id = $engineId
        runtime = "dubroom-native-tts"
        variant = "multilingual-v3"
        t3_model = "v3"
        python = $pythonExe
        selective_download = $true
        installed_at = [DateTime]::UtcNow.ToString("o")
    } | ConvertTo-Json -Depth 4

    $ready | Set-Content -Path (Join-Path $runtimeRoot "ready.json") -Encoding UTF8
    $engineEnvRoot = Join-Path (Split-Path $runtimeRoot -Parent) $engineId
    New-Item -ItemType Directory -Force -Path $engineEnvRoot | Out-Null
    $ready | Set-Content -Path (Join-Path $engineEnvRoot "ready.json") -Encoding UTF8
    Write-Output "Chatterbox Multilingual V3 is ready with selective model files."
}
finally {
    if ($null -ne $lockStream) { $lockStream.Dispose() }
    Remove-Item -Force -ErrorAction SilentlyContinue $lockPath
}
