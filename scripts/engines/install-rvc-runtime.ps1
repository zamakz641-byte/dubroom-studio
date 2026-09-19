$ErrorActionPreference = "Stop"

$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$sourceRoot = Join-Path $engineRoot "source"
$venvPath = Join-Path $engineRoot "venv"
$toolsRoot = Join-Path $engineRoot "tools"
$pythonRoot = Join-Path $engineRoot "python"
New-Item -ItemType Directory -Path $engineRoot,$toolsRoot,$pythonRoot -Force | Out-Null

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

function Test-Python312 {
  param([string]$PythonExe)
  if (-not (Test-Path -LiteralPath $PythonExe)) { return $false }
  & $PythonExe -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)"
  return $LASTEXITCODE -eq 0
}

Set-DubProgress 6 "Synchronisation du runtime RVC" "source"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git est requis pour recuperer RVC." }
if (Test-Path -LiteralPath (Join-Path $sourceRoot ".git")) {
  & git -C $sourceRoot fetch --all --prune
  if ($LASTEXITCODE -ne 0) { throw "Impossible de mettre a jour RVC." }
  & git -C $sourceRoot pull --ff-only
} else {
  & git clone --filter=blob:none https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git $sourceRoot
}
if ($LASTEXITCODE -ne 0) { throw "Impossible de recuperer le runtime RVC." }

Set-DubProgress 16 "Preparation de Python 3.12 portable" "venv"
$uvExe = Join-Path $toolsRoot "uv.exe"
if (-not (Test-Path -LiteralPath $uvExe)) {
  $env:UV_UNMANAGED_INSTALL = $toolsRoot
  $installer = Invoke-RestMethod "https://astral.sh/uv/install.ps1"
  Invoke-Expression $installer
}
if (-not (Test-Path -LiteralPath $uvExe)) { throw "L'installation portable de uv a echoue." }
$env:UV_PYTHON_INSTALL_DIR = $pythonRoot
$env:UV_CACHE_DIR = if ($env:DUB_ENGINE_CACHE) { $env:DUB_ENGINE_CACHE } else { Join-Path $engineRoot "cache" }
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
if ((Test-Path -LiteralPath $venvPath) -and -not (Test-Python312 $pythonExe)) {
  $backup = Join-Path $engineRoot ("venv.incompatible-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
  Move-Item -LiteralPath $venvPath -Destination $backup
}
if (-not (Test-Path -LiteralPath $pythonExe)) { & $uvExe venv --python 3.12 $venvPath }
if ($LASTEXITCODE -ne 0) { throw "Impossible de creer Python 3.12 pour RVC." }

Set-DubProgress 25 "Mise a jour des outils Python" "python"
& $uvExe pip install --python $pythonExe --upgrade pip wheel setuptools
if ($LASTEXITCODE -ne 0) { throw "Impossible de preparer Python pour RVC." }

Set-DubProgress 34 "Detection GPU et installation PyTorch" "runtime"
$gpuText = ""
try { $gpuText = (@(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name) -join " ") } catch { $gpuText = "" }
if (-not $gpuText -and (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) { $gpuText = (& nvidia-smi -L) -join " " }
if ($gpuText -match "NVIDIA") {
  & $pythonExe -c "import torch, torchvision, torchaudio; raise SystemExit(0 if torch.cuda.is_available() and str(torch.version.cuda).startswith('12.') else 1)"
  if ($LASTEXITCODE -ne 0) {
    & $uvExe pip install --python $pythonExe torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
  } else {
    Set-DubProgress 44 "Reutilisation du runtime PyTorch CUDA deja installe" "runtime"
  }
  $requirements = Join-Path $sourceRoot "requirments_cu128_py312.txt"
  $profile = "cuda-cu128"
} else {
  & $pythonExe -c "import torch, torchvision, torchaudio; raise SystemExit(0 if not torch.cuda.is_available() else 1)"
  if ($LASTEXITCODE -ne 0) {
    & $uvExe pip install --python $pythonExe torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cpu
  } else {
    Set-DubProgress 44 "Reutilisation du runtime PyTorch CPU deja installe" "runtime"
  }
  $requirements = Join-Path $sourceRoot "requirments_cpu_py312.txt"
  $profile = "cpu"
}
if ($LASTEXITCODE -ne 0) { throw "L'installation de PyTorch pour RVC a echoue." }
if (-not (Test-Path -LiteralPath $requirements)) { throw "Fichier requirements RVC introuvable: $requirements" }
$requirementsText = Get-Content -LiteralPath $requirements -Raw
if ($requirementsText -match "mirrors\.pku\.edu\.cn") {
  $requirementsText.Replace("https://mirrors.pku.edu.cn/pypi/simple", "https://pypi.org/simple") |
    Set-Content -LiteralPath $requirements -Encoding UTF8
}

Set-DubProgress 62 "Installation des dependances RVC" "dependencies"
& $uvExe pip install --python $pythonExe -r $requirements
if ($LASTEXITCODE -ne 0) { throw "L'installation des dependances RVC a echoue." }

Set-DubProgress 91 "Validation de l'adaptateur RVC" "validate"
Push-Location $sourceRoot
try {
  & $pythonExe -c "from configs.config import Config; from infer.vc.modules import VC; print('rvc-adapter-ok')"
  if ($LASTEXITCODE -ne 0) { throw "L'import du moteur RVC a echoue." }
} finally { Pop-Location }

@{engine_id=$env:DUB_ENGINE_ID;source=$sourceRoot;python=$pythonExe;profile=$profile;self_test="adapter-import";models_downloaded=$false;installed_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Encoding UTF8
Set-DubProgress 99 "Runtime RVC pret; importez ensuite un modele autorise" "ready"
