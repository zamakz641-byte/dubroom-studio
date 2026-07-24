$ErrorActionPreference = "Stop"

$engineRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_ENV)
$modelRoot = [System.IO.Path]::GetFullPath($env:DUB_ENGINE_MODELS)
if (-not $env:DUB_MODEL_REPO) { throw "Le dépôt du modèle de traduction n'est pas configuré." }
New-Item -ItemType Directory -Path $engineRoot -Force | Out-Null
New-Item -ItemType Directory -Path $modelRoot -Force | Out-Null

$venvPath = Join-Path $engineRoot "venv"
if (-not (Test-Path -LiteralPath (Join-Path $venvPath "Scripts\python.exe"))) { & python -m venv $venvPath }
$pythonExe = Join-Path $venvPath "Scripts\python.exe"
& $pythonExe -m pip install --upgrade pip
& $pythonExe -m pip install "huggingface-hub>=0.30,<1" sentencepiece
if ($LASTEXITCODE -ne 0) { throw "L'installation du gestionnaire de modèles a échoué." }

if ($env:DUB_MODEL_RUNTIME -eq "llama_cpp") {
  & $pythonExe -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
} elseif ($env:DUB_MODEL_RUNTIME -eq "ctranslate2") {
  & $pythonExe -m pip install "ctranslate2>=4.6,<5" "transformers>=4.51,<5"
} elseif ($env:DUB_MODEL_RUNTIME -eq "transformers") {
  & $pythonExe -m pip install "torch>=2.6" "transformers>=4.51,<5" accelerate safetensors
} elseif ($env:DUB_MODEL_RUNTIME -eq "onnx") {
  & $pythonExe -m pip install "torch>=2.6" "transformers>=4.51,<5" "optimum[onnxruntime]>=1.24" onnx
} else {
  throw "Runtime de traduction inconnu: $($env:DUB_MODEL_RUNTIME)"
}
if ($LASTEXITCODE -ne 0) { throw "L'installation du runtime quantifié a échoué." }

$downloadCode = @'
import json, os
from pathlib import Path
from huggingface_hub import hf_hub_download, snapshot_download
root = Path(os.environ["DUB_ENGINE_MODELS"])
repo = os.environ["DUB_MODEL_REPO"]
file_name = os.environ.get("DUB_MODEL_FILE", "")
runtime = os.environ.get("DUB_MODEL_RUNTIME", "")
if runtime == "onnx":
    from optimum.exporters.onnx import main_export
    output = root / "onnx"
    task = "text2text-generation-with-past" if os.environ.get("DUB_MODEL_KIND") == "seq2seq" else "text-generation-with-past"
    main_export(model_name_or_path=repo, output=output, task=task)
    model_path = output
elif file_name:
    downloaded = hf_hub_download(repo_id=repo, filename=file_name, revision=os.environ.get("DUB_MODEL_REVISION", "main"), local_dir=root)
    model_path = downloaded
else:
    model_path = snapshot_download(repo_id=repo, revision=os.environ.get("DUB_MODEL_REVISION", "main"), local_dir=root / "snapshot")
manifest = {
    "schema_version": 2,
    "engine_id": os.environ["DUB_ENGINE_ID"],
    "repo_id": repo,
    "original_repo_id": os.environ.get("DUB_MODEL_ORIGINAL_REPO", ""),
    "file_name": file_name or None,
    "model_path": str(model_path),
    "runtime": runtime,
    "quantization": os.environ.get("DUB_MODEL_QUANTIZATION", ""),
}
(root / "model.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
'@
& $pythonExe -c $downloadCode
if ($LASTEXITCODE -ne 0) { throw "Le téléchargement ou l'export du modèle a échoué." }
