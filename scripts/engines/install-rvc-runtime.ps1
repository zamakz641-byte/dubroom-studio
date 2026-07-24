$ErrorActionPreference = "Stop"

$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$sourceRoot = Join-Path $engineRoot "source"
$venvPath = Join-Path $engineRoot "venv"
New-Item -ItemType Directory -Path $engineRoot -Force | Out-Null

function Set-DubProgress {
  param([int]$Progress, [string]$Message)
  if (-not $env:DUB_ENGINE_STATE) { return }
  $status = if ($env:DUB_ENGINE_REPAIR -eq "1") { "repairing" } else { "installing" }
  @{status=$status;progress=$Progress;message=$Message;log_path=$env:DUB_ENGINE_LOG;updated_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json | Set-Content -LiteralPath $env:DUB_ENGINE_STATE -Encoding UTF8
}

Set-DubProgress 6 "Synchronisation du runtime RVC"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git est requis pour recuperer RVC." }
if (Test-Path -LiteralPath (Join-Path $sourceRoot ".git")) {
  & git -C $sourceRoot fetch --all --prune
  & git -C $sourceRoot pull --ff-only
} else {
  & git clone --filter=blob:none https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git $sourceRoot
}
if ($LASTEXITCODE -ne 0) { throw "Impossible de recuperer le runtime RVC." }

Set-DubProgress 18 "Creation de l'environnement isole"
if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) { & python -m venv $venvPath }
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
& $pythonExe -m pip install --upgrade pip wheel setuptools
if ($LASTEXITCODE -ne 0) { throw "Impossible de preparer Python pour RVC." }

Set-DubProgress 28 "Installation du calcul local"
$gpuNames = @(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name)
if (($gpuNames | Where-Object { $_ -match "NVIDIA" }).Count -gt 0) {
  & $pythonExe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
  $profile = "cuda"
} else {
  & $pythonExe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
  $profile = "cpu"
}
if ($LASTEXITCODE -ne 0) { throw "L'installation de PyTorch pour RVC a echoue." }

Set-DubProgress 55 "Installation des dependances RVC"
$requirements = Join-Path $sourceRoot "requirements-py311.txt"
if (-not (Test-Path -LiteralPath $requirements)) { $requirements = Join-Path $sourceRoot "requirements.txt" }
& $pythonExe -m pip install -r $requirements
if ($LASTEXITCODE -ne 0) { throw "L'installation des dependances RVC a echoue." }

Set-DubProgress 90 "Validation de l'adaptateur RVC"
Push-Location $sourceRoot
try {
  & $pythonExe -c "from configs.config import Config; from infer.modules.vc.modules import VC; print('rvc-adapter-ok')"
  if ($LASTEXITCODE -ne 0) { throw "L'import du moteur RVC a echoue." }
} finally { Pop-Location }

@{engine_id=$env:DUB_ENGINE_ID;source=$sourceRoot;python=$pythonExe;profile=$profile;self_test="adapter-import";models_downloaded=$false;installed_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Encoding UTF8
Set-DubProgress 99 "Runtime RVC pret; importez ensuite un modele autorise"
