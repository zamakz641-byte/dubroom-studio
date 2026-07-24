$ErrorActionPreference = "Stop"

$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$cacheRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_CACHE)
$packages = @($env:DUB_ENGINE_PACKAGES -split ';' | Where-Object { $_.Trim() })
if (-not $engineRoot -or -not $cacheRoot -or $packages.Count -eq 0) {
  throw "Configuration d'installation incomplète."
}

New-Item -ItemType Directory -Path $engineRoot -Force | Out-Null
New-Item -ItemType Directory -Path $cacheRoot -Force | Out-Null
$venvPath = Join-Path $engineRoot "venv"
if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) {
  & python -m venv $venvPath
}
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install @packages
if ($LASTEXITCODE -ne 0) { throw "L'installation Python a échoué." }

if ($env:DUB_MODEL_REPO) {
  & $pythonExe -m pip install huggingface-hub
  if ($LASTEXITCODE -ne 0) { throw "L'installation du client de modèles a échoué." }
  $modelRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_MODELS)
  New-Item -ItemType Directory -Path $modelRoot -Force | Out-Null
  $downloadCode = @'
import json, os
from pathlib import Path
from huggingface_hub import snapshot_download
target = Path(os.environ["DUB_ENGINE_MODELS"])
snapshot = snapshot_download(
    repo_id=os.environ["DUB_MODEL_REPO"],
    revision=os.environ.get("DUB_MODEL_REVISION", "main"),
    local_dir=target / "snapshot",
    token=os.environ.get("HF_TOKEN") or None,
)
(target / "model.json").write_text(json.dumps({
    "engine_id": os.environ["DUB_ENGINE_ID"],
    "repo_id": os.environ["DUB_MODEL_REPO"],
    "snapshot": snapshot,
}, indent=2), encoding="utf-8")
'@
  & $pythonExe -c $downloadCode
  if ($LASTEXITCODE -ne 0) { throw "Le téléchargement du modèle a échoué. Vérifiez le jeton et les conditions d'accès." }
}

$ready = @{engine_id=$env:DUB_ENGINE_ID; packages=$packages; installed_at=(Get-Date).ToUniversalTime().ToString("o")} | ConvertTo-Json
Set-Content -LiteralPath (Join-Path $engineRoot "ready.json") -Value $ready -Encoding UTF8
