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

$engineId = Require-Env "DUB_ENGINE_ID"
$engineRoot = [System.IO.Path]::GetFullPath((Require-Env "DUB_ENGINE_ENV"))
$runtimeRoot = [System.IO.Path]::GetFullPath((Require-Env "DUB_TTS_RUNTIME_ENV"))
$modelRoot = [System.IO.Path]::GetFullPath((Require-Env "DUB_ENGINE_MODELS"))
$workspaceRoot = Split-Path (Split-Path $modelRoot -Parent) -Parent
$uvExe = Join-Path $workspaceRoot "data\toolchains\uv\uv.exe"
$venvRoot = Join-Path $runtimeRoot "venv"
$pythonExe = Join-Path $venvRoot "Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $engineRoot,$runtimeRoot,$modelRoot | Out-Null
$env:UV_CACHE_DIR = Join-Path $workspaceRoot "data\cache\uv"
$env:UV_LINK_MODE = "hardlink"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $workspaceRoot "data\toolchains\python"
$env:HF_HOME = Join-Path $workspaceRoot "data\cache\huggingface"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

Set-DubProgress 10 "Preparation du runtime CPU partage"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    & $uvExe venv --python 3.12 $venvRoot
    if ($LASTEXITCODE -ne 0) { throw "Impossible de creer le runtime Pocket TTS" }
}

Set-DubProgress 30 "Installation de Pocket TTS 2.1.0"
& $uvExe pip install --python $pythonExe "pocket-tts==2.1.0"
if ($LASTEXITCODE -ne 0) { throw "Impossible d'installer Pocket TTS" }
& $uvExe pip check --python $pythonExe
if ($LASTEXITCODE -ne 0) { throw "Les dependances Pocket TTS sont incompatibles" }

Set-DubProgress 55 "Telechargement et validation du modele francais"
& $pythonExe -c "from pocket_tts import TTSModel; m=TTSModel.load_model(language='french_24l'); s=m.get_state_for_audio_prompt('estelle'); assert m.sample_rate == 24000; assert s"
if ($LASTEXITCODE -ne 0) { throw "Le modele francais Pocket TTS n'est pas utilisable" }

$manifest = @{
    engine_id = $engineId
    family = "kyutai_pocket"
    language_model = "french_24l"
    sample_rate = 24000
    model_cache = $env:HF_HOME
    installed_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $modelRoot "model.json") -Value $manifest -Encoding UTF8

$ready = @{
    engine_id = $engineId
    family = "kyutai_pocket"
    python = $pythonExe
    model = $modelRoot
    self_test = "pocket-tts-french-estelle"
    installed_at = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Value $ready -Encoding UTF8
Set-Content -LiteralPath (Join-Path $runtimeRoot "ready.json") -Value $ready -Encoding UTF8
Set-DubProgress 98 "Pocket TTS francais pret sur CPU"
