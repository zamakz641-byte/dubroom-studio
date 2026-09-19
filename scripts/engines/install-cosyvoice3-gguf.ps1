$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Require-Env([string]$Name) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) { throw "Missing required environment variable: $Name" }
    return $value
}

function Set-DubProgress([int]$Progress, [string]$Message) {
    if (-not $env:DUB_ENGINE_STATE) { return }
    $payload = @{
        status = if ($env:DUB_ENGINE_REPAIR -eq "1") { "repairing" } else { "installing" }
        progress = $Progress
        message = $Message
        log_path = $env:DUB_ENGINE_LOG
        updated_at = (Get-Date).ToUniversalTime().ToString("o")
    } | ConvertTo-Json
    Set-Content -LiteralPath $env:DUB_ENGINE_STATE -Value $payload -Encoding UTF8
}

function Download-File([string]$Url, [string]$Destination) {
    if (Test-Path -LiteralPath $Destination) { return }
    & curl.exe -L --fail --retry 5 --retry-delay 2 --output $Destination $Url
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
}

$engineId = Require-Env "DUB_ENGINE_ID"
$engineRoot = [System.IO.Path]::GetFullPath((Require-Env "DUB_ENGINE_ENV"))
$runtimeRoot = [System.IO.Path]::GetFullPath((Require-Env "DUB_TTS_RUNTIME_ENV"))
$modelRoot = [System.IO.Path]::GetFullPath((Require-Env "DUB_ENGINE_MODELS"))
$workspaceRoot = Split-Path (Split-Path $modelRoot -Parent) -Parent
$uvExe = Join-Path $workspaceRoot "data\toolchains\uv\uv.exe"
$venvRoot = Join-Path $runtimeRoot "venv"
$pythonExe = Join-Path $venvRoot "Scripts\python.exe"
$hasNvidia = $null -ne (Get-Command "nvidia-smi.exe" -ErrorAction SilentlyContinue)
$crispBackend = if ($hasNvidia) { "cuda" } else { "vulkan" }
$crispRuntimeName = if ($hasNvidia) { "crispasr-cuda-v0.8.25" } else { "crispasr-vulkan" }
$crispArchiveName = "crispasr-windows-x86_64-$crispBackend.zip"
$crispRoot = Join-Path $workspaceRoot "data\runtimes\$crispRuntimeName"
$crispArchive = Join-Path $crispRoot $crispArchiveName
$crispDir = Join-Path $crispRoot "crispasr-windows-x86_64-$crispBackend"
$crispExe = Join-Path $crispDir "crispasr.exe"

New-Item -ItemType Directory -Force -Path $engineRoot,$runtimeRoot,$modelRoot,$crispRoot | Out-Null

Set-DubProgress 8 "Preparation du runtime compact sans PyTorch"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    & $uvExe venv --python 3.12 $venvRoot
    if ($LASTEXITCODE -ne 0) { throw "Impossible de creer le runtime CosyVoice compact" }
}

Set-DubProgress 18 (if ($hasNvidia) { "Installation de CrispASR CUDA pour NVIDIA" } else { "Installation du secours CrispASR CPU" })
if (-not (Test-Path -LiteralPath $crispExe)) {
    Download-File `
        "https://github.com/CrispStrobe/CrispASR/releases/download/v0.8.25/$crispArchiveName" `
        $crispArchive
    Expand-Archive -LiteralPath $crispArchive -DestinationPath $crispRoot -Force
}
if (-not (Test-Path -LiteralPath $crispExe)) { throw "CrispASR 0.8.25 is incomplete" }
Remove-Item -LiteralPath $crispArchive -Force -ErrorAction SilentlyContinue

$baseUrl = "https://huggingface.co/cstr/cosyvoice3-0.5b-2512-GGUF/resolve/main"
$files = @(
    "cosyvoice3-llm-q4_k.gguf",
    "cosyvoice3-flow-q8_0.gguf",
    "cosyvoice3-s3tok-q4_k.gguf",
    "cosyvoice3-hift-f16.gguf",
    "cosyvoice3-campplus-f16.gguf",
    "cosyvoice3-voices.gguf"
)
$progress = 28
foreach ($file in $files) {
    Set-DubProgress $progress "Telechargement compact: $file"
    Download-File "$baseUrl/$file?download=true" (Join-Path $modelRoot $file)
    $progress += 10
}

# v0.8.25 validates this literal legacy name before opening the GGUF metadata.
# A hard link keeps the Q4 tokenizer at one physical copy on NTFS.
$s3Source = Join-Path $modelRoot "cosyvoice3-s3tok-q4_k.gguf"
$s3Alias = Join-Path $modelRoot "cosyvoice3-s3tok-f16.gguf"
if (-not (Test-Path -LiteralPath $s3Alias)) {
    New-Item -ItemType HardLink -Path $s3Alias -Target $s3Source | Out-Null
}

Set-DubProgress 90 "Validation du runtime CosyVoice 3 compact"
& $crispExe --version | Out-Null
if ($LASTEXITCODE -ne 0) { throw "CrispASR cannot start" }

$manifest = @{
    engine_id = $engineId
    family = "cosyvoice3_gguf"
    backend = "CrispASR 0.8.25"
    precision = "LLM Q4_K; Flow Q8_0; S3Tokenizer Q4_K"
    sample_rate = 24000
    flow_steps = 5
    device = if ($hasNvidia) { "cuda" } else { "cpu" }
    gpu_backend = if ($hasNvidia) { "CUDA" } else { $null }
    vulkan_status = "disabled-invalid-output"
    model_repo = "cstr/cosyvoice3-0.5b-2512-GGUF"
    license = "Apache-2.0"
    installed_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $modelRoot "model.json") -Value $manifest -Encoding UTF8

$ready = @{
    engine_id = $engineId
    family = "cosyvoice3_gguf"
    python = $pythonExe
    model = $modelRoot
    runtime = $crispExe
    self_test = if ($hasNvidia) { "cosyvoice3-gguf-fr-clone-cuda-flow5" } else { "cosyvoice3-gguf-fr-clone-cpu-flow5" }
    device = if ($hasNvidia) { "cuda" } else { "cpu" }
    gpu_backend = if ($hasNvidia) { "CUDA" } else { $null }
    vulkan_status = "disabled-invalid-output"
    installed_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Value $ready -Encoding UTF8
Set-Content -LiteralPath (Join-Path $runtimeRoot "ready.json") -Value $ready -Encoding UTF8
Set-DubProgress 98 (if ($hasNvidia) { "CosyVoice 3 compact pret sur GPU CUDA" } else { "CosyVoice 3 compact pret en secours CPU" })
