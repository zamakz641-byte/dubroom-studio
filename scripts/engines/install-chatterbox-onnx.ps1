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
$precision = [Environment]::GetEnvironmentVariable("DUB_MODEL_QUANTIZATION")
if ([string]::IsNullOrWhiteSpace($precision)) { $precision = "fp16" }
$packageString = [Environment]::GetEnvironmentVariable("DUB_ENGINE_PACKAGES")
$repair = [Environment]::GetEnvironmentVariable("DUB_ENGINE_REPAIR") -eq "1"
$workspaceRoot = Split-Path (Split-Path $modelRoot -Parent) -Parent
$toolchainRoot = Join-Path $workspaceRoot "data\toolchains"
$uvRoot = Join-Path $toolchainRoot "uv"
$pythonRoot = Join-Path $toolchainRoot "python"
$uvExe = Join-Path $uvRoot "uv.exe"

if ($repoId -ne "ResembleAI/chatterbox-turbo-ONNX") {
    throw "This installer only accepts the official ResembleAI/chatterbox-turbo-ONNX repository"
}
if ($precision -notin @("fp16", "q4f16", "q4", "q8", "fp32")) {
    throw "Unsupported Chatterbox ONNX precision: $precision"
}

New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
New-Item -ItemType Directory -Force -Path $modelRoot | Out-Null
$venvRoot = Join-Path $runtimeRoot "venv"
$pythonExe = Join-Path $venvRoot "Scripts\python.exe"
$lockPath = Join-Path $runtimeRoot ".install.lock"
$lockStream = $null

try {
    # DubRoom keeps toolchains inside data\toolchains; DUB_BASE_PYTHON already points to the selected project-local interpreter.
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        try {
            $lockStream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
            break
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if ($null -eq $lockStream) { throw "Timed out waiting for the shared Chatterbox ONNX runtime lock" }

    New-Item -ItemType Directory -Force -Path $uvRoot,$pythonRoot | Out-Null
    if (-not (Test-Path -LiteralPath $uvExe)) {
        $env:UV_UNMANAGED_INSTALL = $uvRoot
        $installer = Invoke-RestMethod "https://astral.sh/uv/install.ps1"
        Invoke-Expression $installer
    }
    if (-not (Test-Path -LiteralPath $uvExe)) { throw "The project-local uv installer could not be prepared" }
    $env:UV_PYTHON_INSTALL_DIR = $pythonRoot
    $env:UV_CACHE_DIR = Join-Path $workspaceRoot "data\cache\uv"
    $env:UV_LINK_MODE = "hardlink"
    $env:UV_HTTP_TIMEOUT = "300"

    if ($repair -and (Test-Path $venvRoot)) {
        Remove-Item -Recurse -Force $venvRoot
    }
    if (-not (Test-Path $pythonExe)) {
        Write-Output "Creating Chatterbox ONNX Python environment..."
        & $uvExe venv --python 3.11 $venvRoot
        if ($LASTEXITCODE -ne 0) { throw "Failed to create the Chatterbox ONNX virtual environment" }
    }

    $packages = @()
    if (-not [string]::IsNullOrWhiteSpace($packageString)) {
        $packages = $packageString.Split(';', [System.StringSplitOptions]::RemoveEmptyEntries)
    }
    if ($packages.Count -gt 0) {
        Write-Output "Installing ONNX Runtime CUDA and Chatterbox dependencies..."
        & $uvExe pip install --python $pythonExe @packages
        if ($LASTEXITCODE -ne 0) { throw "Failed to install Chatterbox ONNX dependencies" }
    }
    & $uvExe pip check --python $pythonExe
    if ($LASTEXITCODE -ne 0) { throw "Chatterbox ONNX dependency validation failed" }

    $downloadScript = Join-Path $runtimeRoot "download-model.py"
    @'
from __future__ import annotations
import json
import os
from pathlib import Path
from huggingface_hub import snapshot_download

repo = os.environ["DUB_MODEL_REPO"]
revision = os.environ.get("DUB_MODEL_REVISION") or "main"
precision = (os.environ.get("DUB_MODEL_QUANTIZATION") or "fp16").lower()
root = Path(os.environ["DUB_ENGINE_MODELS"]).resolve()
target = root / "model"
target.mkdir(parents=True, exist_ok=True)
suffix = {
    "fp32": "",
    "fp16": "_fp16",
    "q8": "_quantized",
    "q4": "_q4",
    "q4f16": "_q4f16",
}[precision]
components = ("conditional_decoder", "speech_encoder", "embed_tokens", "language_model")
patterns = [
    "config.json",
    "generation_config.json",
    "preprocessor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
]
for component in components:
    graph = f"onnx/{component}{suffix}.onnx"
    patterns.extend([graph, graph + "_data"])

snapshot_download(
    repo_id=repo,
    revision=revision,
    local_dir=str(target),
    allow_patterns=patterns,
    token=os.environ.get("HF_TOKEN") or None,
)
missing = [name for name in patterns if not (target / name).is_file() and name != "special_tokens_map.json"]
if missing:
    raise SystemExit("Missing downloaded Chatterbox ONNX artifacts: " + ", ".join(missing))
manifest = {
    "engine_id": os.environ["DUB_ENGINE_ID"],
    "repo_id": repo,
    "revision": revision,
    "runtime": "onnxruntime-gpu",
    "format": "ONNX",
    "quantization": precision,
    "model_path": str(target),
    "artifacts": patterns,
    "self_test": "onnx-artifacts-and-cuda-provider",
}
(root / "model.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(manifest, ensure_ascii=False))
'@ | Set-Content -Path $downloadScript -Encoding UTF8

    Write-Output "Downloading only Chatterbox Turbo ONNX $precision files..."
    & $pythonExe $downloadScript
    if ($LASTEXITCODE -ne 0) { throw "The selective Chatterbox ONNX download failed" }

    $checkScript = Join-Path $runtimeRoot "validate-runtime.py"
    @'
from __future__ import annotations
import json
import os
from pathlib import Path
import onnxruntime as ort
if hasattr(ort, "preload_dlls"):
    ort.preload_dlls(directory="")
providers = ort.get_available_providers()
if "CUDAExecutionProvider" not in providers:
    raise SystemExit("CUDAExecutionProvider is unavailable: " + repr(providers))
root = Path(os.environ["DUB_ENGINE_MODELS"]).resolve() / "model" / "onnx"
precision = (os.environ.get("DUB_MODEL_QUANTIZATION") or "fp16").lower()
suffix = {"fp32": "", "fp16": "_fp16", "q8": "_quantized", "q4": "_q4", "q4f16": "_q4f16"}[precision]
graph = root / f"embed_tokens{suffix}.onnx"
session = ort.InferenceSession(str(graph), providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
active = session.get_providers()
if "CUDAExecutionProvider" not in active:
    raise SystemExit("CUDAExecutionProvider registered but failed to load: " + repr(active))
print(json.dumps({"onnxruntime": ort.__version__, "providers": providers, "active": active}))
'@ | Set-Content -Path $checkScript -Encoding UTF8
    & $pythonExe $checkScript
    if ($LASTEXITCODE -ne 0) { throw "ONNX Runtime GPU validation failed" }

    $ready = @{
        engine_id = $engineId
        runtime = "onnxruntime-gpu"
        quantization = $precision
        python = $pythonExe
        self_test = "onnx-artifacts-and-cuda-provider"
        installed_at = [DateTime]::UtcNow.ToString("o")
    } | ConvertTo-Json -Depth 4
    $ready | Set-Content -Path (Join-Path $runtimeRoot "ready.json") -Encoding UTF8
    $engineEnvRoot = Join-Path (Split-Path $runtimeRoot -Parent) $engineId
    New-Item -ItemType Directory -Force -Path $engineEnvRoot | Out-Null
    $ready | Set-Content -Path (Join-Path $engineEnvRoot "ready.json") -Encoding UTF8
    Write-Output "Chatterbox Turbo ONNX $precision is ready."
}
finally {
    if ($null -ne $lockStream) { $lockStream.Dispose() }
    Remove-Item -Force -ErrorAction SilentlyContinue $lockPath
}
