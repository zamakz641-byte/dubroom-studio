$ErrorActionPreference = "Stop"

$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$sourceRoot = Join-Path $engineRoot "source"
$venvPath = Join-Path $engineRoot "venv"
$toolsRoot = Join-Path $engineRoot "tools"
$pythonRoot = Join-Path $engineRoot "python"
New-Item -ItemType Directory -Path $engineRoot,$toolsRoot,$pythonRoot -Force | Out-Null

function Set-DubProgress {
  param([int]$Progress, [string]$Message)
  if (-not $env:DUB_ENGINE_STATE) { return }
  $status = if ($env:DUB_ENGINE_REPAIR -eq "1") { "repairing" } else { "installing" }
  $payload = @{status=$status;progress=$Progress;message=$Message;log_path=$env:DUB_ENGINE_LOG;updated_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json
  for ($attempt = 0; $attempt -lt 3; $attempt++) {
    try { Set-Content -LiteralPath $env:DUB_ENGINE_STATE -Value $payload -Encoding UTF8; return }
    catch { Start-Sleep -Milliseconds (50 * ($attempt + 1)) }
  }
}

Set-DubProgress 5 "Synchronisation de SubClean"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git est requis pour recuperer SubClean." }
if (Test-Path -LiteralPath (Join-Path $sourceRoot ".git")) {
  & git -C $sourceRoot fetch --all --prune
  & git -C $sourceRoot pull --ff-only
} else {
  & git clone --filter=blob:none https://github.com/YaoFANGUK/video-subtitle-remover.git $sourceRoot
}
if ($LASTEXITCODE -ne 0) { throw "Impossible de recuperer SubClean." }

Set-DubProgress 14 "Preparation de Python 3.12 portable"
$uvExe = Join-Path $toolsRoot "uv.exe"
if (-not (Test-Path -LiteralPath $uvExe)) {
  $env:UV_UNMANAGED_INSTALL = $toolsRoot
  $installer = Invoke-RestMethod "https://astral.sh/uv/install.ps1"
  Invoke-Expression $installer
}
if (-not (Test-Path -LiteralPath $uvExe)) { throw "L'installation portable de uv a echoue." }
$env:UV_PYTHON_INSTALL_DIR = $pythonRoot
$env:UV_CACHE_DIR = if ($env:DUB_ENGINE_CACHE) { $env:DUB_ENGINE_CACHE } else { Join-Path $engineRoot "cache" }
if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) { & $uvExe venv --python 3.12 $venvPath }
$pythonExe = Join-Path $venvPath "Scripts\python.exe"

Set-DubProgress 25 "Selection du profil materiel"
$gpuNames = @(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name)
if (($gpuNames | Where-Object { $_ -match "NVIDIA" }).Count -gt 0) {
  & $uvExe pip install --python $pythonExe torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128
  if ($LASTEXITCODE -ne 0) { throw "L'installation de PyTorch CUDA 12.8 a echoue." }
  # VSR's official Windows CUDA 12.8 build uses Paddle 3.0 CPU for OCR and
  # PyTorch CUDA for neural inpainting. Mixing Paddle cu118 with Torch cu128
  # loads incompatible CUDA runtimes on recent RTX machines.
  & $uvExe pip install --python $pythonExe paddlepaddle==3.0.0
  $profile = "cuda128-torch-paddle-cpu"
} else {
  & $uvExe pip install --python $pythonExe torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cpu
  & $uvExe pip install --python $pythonExe paddlepaddle==3.0.0
  $profile = "cpu"
}
if ($LASTEXITCODE -ne 0) { throw "L'installation du profil de calcul SubClean a echoue." }

Set-DubProgress 55 "Installation des dependances de restauration"
& $uvExe pip install --python $pythonExe -r (Join-Path $sourceRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "L'installation des dependances SubClean a echoue." }

Set-DubProgress 90 "Validation de la CLI SubClean"
& $pythonExe (Join-Path $sourceRoot "backend\main.py") --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "La validation de la CLI SubClean a echoue." }

@{engine_id=$env:DUB_ENGINE_ID;source=$sourceRoot;python=$pythonExe;profile=$profile;self_test="cli-help";models_downloaded=$false;installed_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Encoding UTF8
Set-DubProgress 99 "SubClean pret; les poids seront telecharges a la premiere demande"

