from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import PATHS, VOICEBOX_SOURCE


REGISTRY_PATH = PATHS.workspace / "models" / "registry.json"
WHISPER_CATALOG_PATH = PATHS.workspace / "models" / "whisper-catalog.json"
TRANSLATION_CATALOG_PATH = PATHS.workspace / "models" / "translation-catalog.json"
BRAND_CATALOG_PATH = PATHS.workspace / "models" / "brand-catalog.json"
INSTALL_STATE_ROOT = PATHS.data / "engine-state"
_install_processes: dict[str, subprocess.Popen[str]] = {}
_install_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {"schema_version": 3, "engines": []}
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload.get("engines"), list):
        raise ValueError("Engine registry must contain an engines array")
    # Voicebox is the single TTS orchestration layer. Legacy standalone voice
    # adapters remain on disk only for migration and are not exposed to users.
    payload["engines"] = [item for item in payload["engines"] if item.get("id") != "supertonic-local"]
    if WHISPER_CATALOG_PATH.exists():
        catalog = json.loads(WHISPER_CATALOG_PATH.read_text(encoding="utf-8"))
        payload["engines"] = [item for item in payload["engines"] if not str(item.get("id", "")).startswith("faster-whisper-")]
        for model in catalog.get("models", []):
            engine_id = str(model["id"])
            size = float(model.get("download_gb", 0))
            model_name = str(model.get("model_name", "whisper"))
            family = "Distil Whisper" if model_name.startswith("distil-") else "Whisper"
            payload["engines"].append({
                "id": engine_id,
                "display_name": model["label"],
                "category": "asr",
                "tagline": "Multilingual transcription model" if model.get("languages") == "multilingual" else "English-optimized transcription model",
                "description": "Installable Faster Whisper model with isolated runtime, word timestamps and automatic hardware fallback.",
                "installable": True,
                "source": "https://github.com/SYSTRAN/faster-whisper",
                "license": "MIT runtime · model weights retain their own terms",
                "capabilities": ["transcription", "language-detection", "word-timestamps"],
                "languages": [model.get("languages", "multilingual")],
                "requirements": {"disk_space_gb": round(size * 1.35 + 0.35, 2), "download_size_gb": size, "minimum_ram_gb": 4 if model.get("vram_gb", 1) <= 2 else 8, "recommended_vram_gb": model.get("vram_gb", 1)},
                "model": {"repo_id": model["repo_id"], "revision": "main", "model_name": model.get("model_name"), "parameters_m": model.get("parameters_m"), "quality_rank": model.get("quality_rank"), "speed_rank": model.get("speed_rank"), "optimized": bool(model.get("optimized")), "recommended": bool(model.get("recommended")), "family": family, "family_id": f"asr-{family.lower().replace(' ', '-')}", "format": "CTranslate2", "variant": model.get("label"), "runtime": "ctranslate2", "quantization": "INT8 / FP16 runtime"},
                "installer": {"script": "install-huggingface-asr.ps1", "steps": ["Create isolated Python environment", "Install Faster Whisper", "Download and verify model", "Run load test"], "checks": [{"root": "models_root", "path": f"{engine_id}/model.json"}, {"root": "environments_root", "path": f"{engine_id}/venv/Scripts/python.exe"}]},
            })
            quantized_engine = payload["engines"][-1]
            raw_repo = str(model.get("original_repo_id") or "")
            if not raw_repo:
                raw_repo = f"openai/whisper-{model_name}" if not model_name.startswith("distil-") else str(model["repo_id"]).replace("Systran/faster-", "distil-whisper/").removesuffix("-ct2")
            for suffix, runtime, model_format, multiplier in (("raw", "transformers", "Transformers", 2.35), ("onnx", "onnx", "ONNX", 2.6)):
                variant_id = f"{engine_id}-{suffix}"
                alternate = json.loads(json.dumps(quantized_engine))
                alternate.update({
                    "id": variant_id,
                    "display_name": f"{model['label']} · {'Brut' if suffix == 'raw' else 'ONNX'}",
                    "tagline": f"{model_format} · {'poids originaux' if suffix == 'raw' else 'graphe portable CPU/GPU'}",
                    "description": "Original Transformers weights with full precision and maximum compatibility." if suffix == "raw" else "Exported ONNX graph for portable inference with ONNX Runtime.",
                    "source": f"https://huggingface.co/{raw_repo}",
                    "requirements": {**alternate["requirements"], "disk_space_gb": round(max(size * multiplier, 0.5) + 1.5, 2), "download_size_gb": round(max(size * multiplier, 0.4), 2), "recommended_vram_gb": max(int(model.get("vram_gb", 1) * (1.7 if suffix == "raw" else 1.25)), 2)},
                    "model": {**alternate["model"], "repo_id": raw_repo, "original_repo_id": raw_repo, "runtime": runtime, "format": model_format, "quantization": "FP16 / FP32" if suffix == "raw" else "ONNX Runtime", "variant": f"{model['label']} · {model_format}"},
                    "installer": {"script": "install-huggingface-asr.ps1", "steps": ["Create isolated Python environment", f"Install {model_format} runtime", "Download original weights" if suffix == "raw" else "Export verified ONNX graph", "Write runtime manifest"], "checks": [{"root": "models_root", "path": f"{variant_id}/model.json"}, {"root": "environments_root", "path": f"{variant_id}/venv/Scripts/python.exe"}]},
                })
                payload["engines"].append(alternate)
    if TRANSLATION_CATALOG_PATH.exists():
        catalog = json.loads(TRANSLATION_CATALOG_PATH.read_text(encoding="utf-8"))
        payload["engines"] = [item for item in payload["engines"] if not str(item.get("id", "")).startswith("translation-")]
        expanded_translation_bases: set[str] = set()
        for model in catalog.get("models", []):
            engine_id = str(model["id"])
            size = float(model.get("download_gb", 0))
            payload["engines"].append({
                "id": engine_id,
                "display_name": model["label"],
                "category": "translation",
                "tagline": f"{model.get('quantization', 'local')} · {model.get('tier', 'local').title()} · {model.get('languages', 'multilingual')}",
                "description": "Quantized local translation model. The selected artifact, runtime, provenance and license are recorded in a portable manifest.",
                "installable": True,
                "source": f"https://huggingface.co/{model['repo_id']}",
                "license": model.get("license", "See model card"),
                "capabilities": ["translation", str(model.get("quantization", "quantized")), "context-adaptation", "duration-adaptation"] if model.get("kind") == "causal" else ["translation", str(model.get("quantization", "INT8")), "many-to-many", "low-resource-languages"],
                "languages": [model.get("languages", "multilingual")],
                "requirements": {"disk_space_gb": round(size * 1.25 + 1.2, 2), "download_size_gb": size, "minimum_ram_gb": 8 if model.get("vram_gb", 2) <= 4 else 16, "recommended_vram_gb": model.get("vram_gb", 2)},
                "model": {"repo_id": model["repo_id"], "revision": "main", "family_id": f"translation-{str(model.get('family', engine_id)).lower().replace(' ', '-').replace('.', '-')}", "format": "GGUF" if model.get("runtime") == "llama_cpp" else "CTranslate2", "variant": model.get("label"), **model},
                "installer": {"script": "install-huggingface-translation.ps1", "steps": ["Create isolated translation runtime", f"Install {model.get('runtime', 'local')} backend", f"Download only {model.get('quantization', 'selected')} weights", "Write provenance and verified local manifest"], "checks": [{"root": "models_root", "path": f"{engine_id}/model.json"}, {"root": "environments_root", "path": f"{engine_id}/venv/Scripts/python.exe"}]},
            })
            original_repo = str(model.get("original_repo_id") or model["repo_id"])
            base_key = f"{original_repo}:{model.get('parameters_b', '')}"
            if base_key in expanded_translation_bases:
                continue
            expanded_translation_bases.add(base_key)
            quantized_engine = payload["engines"][-1]
            base_id = engine_id.rsplit("-", 1)[0]
            parameters = float(model.get("parameters_b", 1))
            for suffix, runtime, model_format in (("raw", "transformers", "Transformers"), ("onnx", "onnx", "ONNX")):
                variant_id = f"{base_id}-{suffix}"
                alternate = json.loads(json.dumps(quantized_engine))
                disk = round(parameters * (2.25 if suffix == "raw" else 2.5) + 2.0, 2)
                alternate.update({
                    "id": variant_id,
                    "display_name": f"{model.get('family', model['label'])} {parameters:g}B · {'Brut' if suffix == 'raw' else 'ONNX'}",
                    "tagline": f"{model_format} · {model.get('languages', 'multilingual')} · poids originaux",
                    "description": "Original model weights for maximum quality and fine-tuning compatibility." if suffix == "raw" else "Portable ONNX export optimized for local inference providers.",
                    "source": f"https://huggingface.co/{original_repo}",
                    "requirements": {**alternate["requirements"], "disk_space_gb": disk, "download_size_gb": round(disk - 1.2, 2), "minimum_ram_gb": max(8, int(parameters * 3)), "recommended_vram_gb": max(2, int(parameters * (2.2 if suffix == "raw" else 1.65)))},
                    "model": {**alternate["model"], "repo_id": original_repo, "original_repo_id": original_repo, "file_name": "", "runtime": runtime, "format": model_format, "quantization": "BF16 / FP16" if suffix == "raw" else "ONNX Runtime", "variant": f"{model.get('family', model['label'])} {parameters:g}B · {model_format}"},
                    "installer": {"script": "install-huggingface-translation.ps1", "steps": ["Create isolated translation runtime", f"Install {model_format} backend", "Download original weights" if suffix == "raw" else "Export verified ONNX graph", "Write provenance and local manifest"], "checks": [{"root": "models_root", "path": f"{variant_id}/model.json"}, {"root": "environments_root", "path": f"{variant_id}/venv/Scripts/python.exe"}]},
                })
                payload["engines"].append(alternate)
    return payload


def list_engines() -> list[dict[str, Any]]:
    return [engine_snapshot(engine) for engine in load_registry()["engines"]]


def get_engine(engine_id: str) -> dict[str, Any]:
    engine = next((item for item in load_registry()["engines"] if item.get("id") == engine_id), None)
    if not engine:
        raise KeyError(engine_id)
    return engine_snapshot(engine)


def engine_snapshot(engine: dict[str, Any]) -> dict[str, Any]:
    state = _read_state(engine["id"])
    detected = _checks_pass(engine)
    if state.get("status") in {"queued", "installing", "repairing", "failed", "cancelled"}:
        status = state["status"]
    elif detected:
        status = "ready"
    else:
        status = "not_installed"
    verification = _capability_verification(engine, detected)
    return {
        **engine,
        "brand": _brand_for_engine(engine),
        "installation": {
            "status": status,
            "progress": int(state.get("progress", 100 if detected else 0)),
            "message": state.get("message", "Validated locally" if detected else "Available to install"),
            "updated_at": state.get("updated_at"),
            "log_path": state.get("log_path"),
        },
        "verification": verification,
    }


def _brand_for_engine(engine: dict[str, Any]) -> dict[str, Any]:
    catalog: dict[str, Any] = {}
    if BRAND_CATALOG_PATH.exists():
        try:
            catalog = json.loads(BRAND_CATALOG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            catalog = {}
    source = str(engine.get("source", "")).lower()
    engine_id = str(engine.get("id", "")).lower()
    model = engine.get("model") or {}
    family = str(model.get("family") or model.get("family_id") or "").lower()
    candidates = {
        "demucs": "demucs", "pyannote": "pyannote",
        "qwen": "qwen", "aya": "aya", "cohere": "aya", "phi": "phi",
        "nllb": "nllb", "facebook": "nllb", "whisper": "whisper",
        "systran": "whisper", "voicebox": "voicebox", "rvc": "rvc",
        "ffmpeg": "ffmpeg", "subtitle": "vsr", "yaofanguk": "vsr",
        "yt-dlp": "youtube", "youtube": "youtube",
    }
    haystack = f"{engine_id} {source} {family}"
    brand_id = next((value for token, value in candidates.items() if token in haystack), "dubroom")
    brands = catalog.get("brands") if isinstance(catalog.get("brands"), dict) else {}
    return brands.get(brand_id) or {
        "id": "dubroom", "name": "Dubroom adapter", "owner": "Dubroom",
        "official_url": source, "license": str(engine.get("license", "See project")),
        "asset": "/brands/dubroom.svg", "accent": "#c98554", "checksum": None,
    }


def _capability_verification(engine: dict[str, Any], installed: bool) -> dict[str, Any]:
    """Describe whether an installed artifact is actually callable by Dubroom.

    File checks alone only prove that an installer produced files. This contract
    deliberately separates installation, adapter availability and a recorded
    smoke test so the UI never advertises a decorative engine as usable.
    """
    engine_id = str(engine.get("id", ""))
    category = str(engine.get("category", ""))
    adapter = str(engine.get("adapter") or "")
    adapter_path: Path | None = None
    adapter_name = adapter
    if engine_id == "ffmpeg-system":
        adapter_name = "ffmpeg"
        adapter_ready = _system_command_exists("ffmpeg") and _system_command_exists("ffprobe")
    elif engine_id == "yt-dlp":
        adapter_name = "youtube"
        adapter_path = PATHS.workspace / "services" / "api" / "app" / "youtube_service.py"
        adapter_ready = adapter_path.is_file()
    elif engine_id == "voicebox-runtime":
        adapter_name = "voicebox"
        adapter_path = PATHS.workspace / "services" / "api" / "app" / "voicebox_service.py"
        adapter_ready = adapter_path.is_file()
    elif adapter == "rvc":
        adapter_path = PATHS.workspace / "services" / "api" / "app" / "rvc_service.py"
        adapter_ready = adapter_path.is_file() and (PATHS.installers / "run-rvc.py").is_file()
    elif adapter == "subclean":
        adapter_path = PATHS.workspace / "services" / "api" / "app" / "subclean_service.py"
        adapter_ready = adapter_path.is_file()
    elif category == "asr":
        adapter_name = "asr-worker"
        adapter_path = PATHS.installers / "run-asr.py"
        adapter_ready = adapter_path.is_file()
    elif category == "translation":
        adapter_name = "translation-worker"
        adapter_path = PATHS.workspace / "services" / "api" / "app" / "translation_worker.py"
        adapter_ready = adapter_path.is_file()
    else:
        adapter_name = ""
        adapter_ready = False

    manifest_path = PATHS.environments / engine_id / "ready.json"
    smoke_test = False
    smoke_label = "not-run"
    if engine_id == "ffmpeg-system":
        smoke_test = adapter_ready
        smoke_label = "command-version" if smoke_test else "failed"
    elif manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
            smoke_label = str(manifest.get("self_test") or "installer-validation")
            smoke_test = True
        except (json.JSONDecodeError, OSError):
            smoke_label = "invalid-manifest"

    usable = bool(installed and adapter_ready and smoke_test)
    if not installed:
        status = "not-installed"
        message = "Runtime or model is not installed"
    elif not adapter_ready:
        status = "adapter-missing"
        message = "Installed files exist, but no executable Dubroom adapter is enabled"
    elif not smoke_test:
        status = "untested"
        message = "Adapter found; run a repair to record a smoke test"
    else:
        status = "usable"
        message = "Installed, connected and validated locally"
    return {
        "status": status,
        "usable": usable,
        "installed": bool(installed),
        "adapter": adapter_name or None,
        "adapter_ready": bool(adapter_ready),
        "smoke_test": smoke_test,
        "smoke_test_label": smoke_label,
        "message": message,
    }


def installation_preview(engine_id: str) -> dict[str, Any]:
    engine = get_engine(engine_id)
    installer = engine.get("installer") or {}
    return {
        "engine_id": engine_id,
        "display_name": engine.get("display_name", engine_id),
        "disk_space_gb": engine.get("requirements", {}).get("disk_space_gb"),
        "steps": installer.get("steps", []),
        "script": installer.get("script"),
        "environment_root": str(PATHS.environments / engine_id),
        "models_root": str(PATHS.models / engine_id),
        "cache_root": str(PATHS.cache / engine_id),
        "credentials": engine.get("credentials", []),
    }


def validate_model_source(engine_id: str) -> dict[str, Any]:
    """Validate a Hugging Face model source without downloading its weights."""
    engine = get_engine(engine_id)
    model = engine.get("model") or {}
    repo_id = str(model.get("repo_id") or "").strip()
    file_name = str(model.get("file_name") or "").strip()
    if not repo_id:
        return {
            "engine_id": engine_id,
            "has_model": False,
            "reachable": True,
            "repo_id": None,
            "file_name": None,
            "file_found": None,
            "revision": None,
            "message": "Runtime-only engine: no model artifact is downloaded by this installer",
        }
    encoded_repo = "/".join(urllib.parse.quote(part, safe="") for part in repo_id.split("/"))
    request = urllib.request.Request(
        f"https://huggingface.co/api/models/{encoded_repo}",
        headers={"User-Agent": "Dubroom/0.1 model-source-validator"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {
            "engine_id": engine_id,
            "has_model": True,
            "reachable": False,
            "repo_id": repo_id,
            "file_name": file_name or None,
            "file_found": False if file_name else None,
            "revision": None,
            "message": f"Model source returned HTTP {exc.code}",
        }
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "engine_id": engine_id,
            "has_model": True,
            "reachable": False,
            "repo_id": repo_id,
            "file_name": file_name or None,
            "file_found": None,
            "revision": None,
            "message": str(exc),
        }
    siblings = {
        str(item.get("rfilename"))
        for item in payload.get("siblings", [])
        if isinstance(item, dict) and item.get("rfilename")
    }
    file_found = file_name in siblings if file_name else None
    reachable = not file_name or bool(file_found)
    return {
        "engine_id": engine_id,
        "has_model": True,
        "reachable": reachable,
        "repo_id": repo_id,
        "file_name": file_name or None,
        "file_found": file_found,
        "revision": payload.get("sha"),
        "gated": bool(payload.get("gated")),
        "private": bool(payload.get("private")),
        "last_modified": payload.get("lastModified"),
        "message": "Model source and selected artifact are reachable" if reachable else "The selected artifact was not found in the model repository",
    }


def queue_install(engine_id: str, repair: bool = False) -> dict[str, Any]:
    engine = get_engine(engine_id)
    installer = engine.get("installer") or {}
    script_name = installer.get("script")
    if not engine.get("installable", False) or not script_name:
        raise ValueError("This engine is managed by the system or has no installer")
    script_path = (PATHS.installers / script_name).resolve()
    installers_root = PATHS.installers.resolve()
    if installers_root not in script_path.parents or not script_path.exists():
        raise ValueError("Installer script is missing or outside the trusted installer directory")

    state = {
        "status": "repairing" if repair else "queued",
        "progress": 1,
        "message": "Installation queued",
        "updated_at": _now(),
    }
    _write_state(engine_id, state)
    return state


def run_install(engine_id: str, repair: bool = False, credentials: dict[str, str] | None = None) -> None:
    engine = get_engine(engine_id)
    script_path = (PATHS.installers / engine["installer"]["script"]).resolve()
    state_root = INSTALL_STATE_ROOT / engine_id
    state_root.mkdir(parents=True, exist_ok=True)
    log_path = state_root / "install.log"
    status = "repairing" if repair else "installing"
    _write_state(engine_id, {"status": status, "progress": 5, "message": "Installer started", "log_path": str(log_path), "updated_at": _now()})
    env = os.environ.copy()
    env.update({
        "DUB_ENGINE_ID": engine_id,
        "DUB_ENGINE_ENV": str(PATHS.environments / engine_id),
        "DUB_ENGINE_MODELS": str(PATHS.models / engine_id),
        "DUB_ENGINE_CACHE": str(PATHS.cache / engine_id),
        "DUB_ENGINE_STATE": str(_state_path(engine_id)),
        "DUB_ENGINE_LOG": str(log_path),
        "DUB_ENGINE_REPAIR": "1" if repair else "0",
        "HF_HOME": str(PATHS.cache / "huggingface"),
        "TORCH_HOME": str(PATHS.cache / "torch"),
        "PIP_CACHE_DIR": str(PATHS.cache / "pip"),
        "DUB_MODEL_REPO": str((engine.get("model") or {}).get("repo_id", "")),
        "DUB_MODEL_REVISION": str((engine.get("model") or {}).get("revision", "main")),
        "DUB_MODEL_FILE": str((engine.get("model") or {}).get("file_name", "")),
        "DUB_MODEL_RUNTIME": str((engine.get("model") or {}).get("runtime", "transformers")),
        "DUB_MODEL_QUANTIZATION": str((engine.get("model") or {}).get("quantization", "")),
        "DUB_MODEL_ORIGINAL_REPO": str((engine.get("model") or {}).get("original_repo_id", "")),
        "DUB_MODEL_KIND": str((engine.get("model") or {}).get("kind", "causal")),
        "DUB_ENGINE_PACKAGES": ";".join((engine.get("installer") or {}).get("packages", [])),
        "DUB_VOICEBOX_SOURCE": str(VOICEBOX_SOURCE),
    })
    credentials = credentials or {}
    if credentials.get("hf_token"):
        env["HF_TOKEN"] = credentials["hf_token"]
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)]
    process: subprocess.Popen[str] | None = None
    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            process = subprocess.Popen(command, env=env, cwd=PATHS.workspace, stdout=log_file, stderr=subprocess.STDOUT, text=True)
            with _install_lock:
                _install_processes[engine_id] = process
            return_code = process.wait()
        if _read_state(engine_id).get("status") == "cancelled":
            return
        if return_code != 0:
            raise RuntimeError(f"Installer exited with code {return_code}")
        if not _checks_pass(engine):
            raise RuntimeError("Installation finished but validation checks did not pass")
        _write_state(engine_id, {"status": "ready", "progress": 100, "message": "Engine ready", "log_path": str(log_path), "updated_at": _now()})
    except Exception as exc:
        if _read_state(engine_id).get("status") != "cancelled":
            _write_state(engine_id, {"status": "failed", "progress": 0, "message": str(exc), "log_path": str(log_path), "updated_at": _now()})
    finally:
        with _install_lock:
            _install_processes.pop(engine_id, None)


def cancel_install(engine_id: str) -> dict[str, Any]:
    get_engine(engine_id)
    with _install_lock:
        process = _install_processes.get(engine_id)
    if process and process.poll() is None:
        process.terminate()
    state = _read_state(engine_id)
    log_path = state.get("log_path")
    cancelled = {
        "status": "cancelled",
        "progress": int(state.get("progress", 0)),
        "message": "Installation cancelled",
        "log_path": log_path,
        "updated_at": _now(),
    }
    _write_state(engine_id, cancelled)
    return cancelled


def _checks_pass(engine: dict[str, Any]) -> bool:
    checks = (engine.get("installer") or {}).get("checks", [])
    if not checks:
        return engine.get("category") == "system" and _system_command_exists(engine.get("command"))
    variables = {
        "models_root": PATHS.models,
        "environments_root": PATHS.environments,
        "workspace_root": PATHS.workspace,
    }
    for check in checks:
        root = variables.get(check.get("root"))
        relative = check.get("path")
        if not root or not relative or not (root / relative).exists():
            return False
    return True


def _system_command_exists(command: str | None) -> bool:
    if not command:
        return False
    try:
        return subprocess.run([command, "-version"], capture_output=True, timeout=4, check=False).returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def _state_path(engine_id: str) -> Path:
    return INSTALL_STATE_ROOT / engine_id / "state.json"


def _read_state(engine_id: str) -> dict[str, Any]:
    path = _state_path(engine_id)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_state(engine_id: str, state: dict[str, Any]) -> None:
    path = _state_path(engine_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
