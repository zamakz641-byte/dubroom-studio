$ErrorActionPreference = "Stop"
$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$modelRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_MODELS)
New-Item -ItemType Directory -Path $engineRoot -Force | Out-Null
New-Item -ItemType Directory -Path $modelRoot -Force | Out-Null
$venvPath = Join-Path $engineRoot "venv"
if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) { & python -m venv $venvPath }
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install supertonic
if ($LASTEXITCODE -ne 0) { throw "L'installation de Supertonic a échoué." }
$validation = @'
import json, os
from pathlib import Path
from supertonic import TTS
root = Path(os.environ["DUB_ENGINE_MODELS"])
TTS(model_dir=root / "model", auto_download=True)
(root / "model.json").write_text(json.dumps({"engine_id": os.environ["DUB_ENGINE_ID"], "status": "ready"}, indent=2), encoding="utf-8")
'@
& $pythonExe -c $validation
if ($LASTEXITCODE -ne 0) { throw "Le téléchargement ou la validation de Supertonic a échoué." }
