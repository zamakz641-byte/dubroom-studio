$ErrorActionPreference = "Stop"

$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$modelRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_MODELS)
if (-not $env:DUB_MODEL_REPO) { throw "Le dépôt du modèle n'est pas configuré." }
New-Item -ItemType Directory -Path $engineRoot -Force | Out-Null
New-Item -ItemType Directory -Path $modelRoot -Force | Out-Null

$venvPath = Join-Path $engineRoot "venv"
if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) {
  & python -m venv $venvPath
}
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
& $pythonExe -m pip install --upgrade pip
$runtime = if ($env:DUB_MODEL_RUNTIME) { $env:DUB_MODEL_RUNTIME } else { "ctranslate2" }
if ($runtime -eq "ctranslate2") {
  & $pythonExe -m pip install faster-whisper huggingface-hub
} elseif ($runtime -eq "transformers") {
  & $pythonExe -m pip install "torch>=2.6" "transformers>=4.51,<5" accelerate librosa soundfile huggingface-hub
} elseif ($runtime -eq "onnx") {
  & $pythonExe -m pip install "torch>=2.6" "transformers>=4.51,<5" "optimum[onnxruntime]>=1.24" onnx librosa soundfile huggingface-hub
} else { throw "Runtime ASR inconnu: $runtime" }
if ($LASTEXITCODE -ne 0) { throw "L'installation du runtime ASR a échoué." }

$downloadCode = @'
import json, os
from pathlib import Path
from huggingface_hub import snapshot_download
target = Path(os.environ["DUB_ENGINE_MODELS"])
target.mkdir(parents=True, exist_ok=True)
repo = os.environ["DUB_MODEL_REPO"]
runtime = os.environ.get("DUB_MODEL_RUNTIME", "ctranslate2")
if runtime == "onnx":
    from optimum.exporters.onnx import main_export
    snapshot = target / "onnx"
    main_export(model_name_or_path=repo, output=snapshot, task="automatic-speech-recognition")
else:
    snapshot = snapshot_download(repo_id=repo, revision=os.environ.get("DUB_MODEL_REVISION", "main"), local_dir=target / "snapshot")
(target / "model.json").write_text(json.dumps({
    "engine_id": os.environ["DUB_ENGINE_ID"],
    "repo_id": repo,
    "runtime": runtime,
    "model_path": str(snapshot),
    "snapshot": str(snapshot),
}, indent=2), encoding="utf-8")
'@
& $pythonExe -c $downloadCode
if ($LASTEXITCODE -ne 0) { throw "Le téléchargement ou la validation du modèle a échoué." }
