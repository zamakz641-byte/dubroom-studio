from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import PATHS
from .tts_catalog_service import build_engine_entries, runtime_engine_id as tts_runtime_engine_id


REGISTRY_PATH = PATHS.workspace / "models" / "registry.json"
WHISPER_CATALOG_PATH = PATHS.workspace / "models" / "whisper-catalog.json"
TRANSLATION_CATALOG_PATH = PATHS.workspace / "models" / "translation-catalog.json"
BRAND_CATALOG_PATH = PATHS.workspace / "models" / "brand-catalog.json"
INSTALL_STATE_ROOT = PATHS.data / "engine-state"
TTS_CATALOG_PATH = PATHS.workspace / "models" / "tts-catalog.json"
_install_processes: dict[str, subprocess.Popen[str]] = {}
_install_lock = threading.Lock()

TRANSLATION_RUNTIME_IDS = {
    "llama_cpp": "translation-qwen3-0.6b-q8",
    "ctranslate2": "translation-nllb-600m-int8",
    "transformers": "translation-runtime-transformers",
    "onnx": "translation-runtime-onnx",
}


def translation_runtime_id(model: dict[str, Any]) -> str:
    runtime = str(model.get("runtime") or "transformers")
    return TRANSLATION_RUNTIME_IDS.get(runtime, f"translation-runtime-{runtime.replace('_', '-')}")


def engine_runtime_id(engine: dict[str, Any]) -> str:
    model = engine.get("model") or {}
    if engine.get("adapter") == "native-tts":
        return tts_runtime_engine_id(model)
    if engine.get("category") == "translation":
        return translation_runtime_id(model)
    return str(engine["id"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_registry() -> dict[str, Any]:
    if not REGISTRY_PATH.exists():
        return {"schema_version": 3, "engines": []}
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload.get("engines"), list):
        raise ValueError("Engine registry must contain an engines array")
    payload["engines"] = [item for item in payload["engines"] if item.get("id") != "supertonic-local" and not str(item.get("id", "")).startswith("tts-")]
    if WHISPER_CATALOG_PATH.exists():
        catalog = json.loads(WHISPER_CATALOG_PATH.read_text(encoding="utf-8"))
        payload["engines"] = [item for item in payload["engines"] if not str(item.get("id", "")).startswith("faster-whisper-")]
        nvidia_runtime_gb = (
            1.2
            if os.name == "nt"
            and _system_command_exists("nvidia-smi")
            and not _shared_cuda_runtime_exists()
            else 0.0
        )
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
                "license": "MIT runtime - model weights retain their own terms",
                "capabilities": ["transcription", "language-detection", "word-timestamps"],
                "languages": [model.get("languages", "multilingual")],
                "requirements": {
                    "disk_space_gb": round(size * 1.35 + 0.35 + nvidia_runtime_gb, 2),
                    "download_size_gb": round(size + nvidia_runtime_gb, 2),
                    "runtime_download_size_gb": nvidia_runtime_gb,
                    "minimum_ram_gb": 4 if model.get("vram_gb", 1) <= 2 else 8,
                    "recommended_vram_gb": model.get("vram_gb", 1),
                },
                "model": {"repo_id": model["repo_id"], "revision": "main", "model_name": model.get("model_name"), "parameters_m": model.get("parameters_m"), "quality_rank": model.get("quality_rank"), "speed_rank": model.get("speed_rank"), "optimized": bool(model.get("optimized")), "recommended": bool(model.get("recommended")), "family": family, "family_id": f"asr-{family.lower().replace(' ', '-')}", "format": "CTranslate2", "variant": model.get("label"), "runtime": "ctranslate2", "quantization": "INT8 / FP16 runtime"},
                "installer": {"script": "install-huggingface-asr.ps1", "steps": ["Create isolated Python environment", "Install Faster Whisper and NVIDIA acceleration when available", "Download and verify model", "Run load test"], "checks": [{"root": "models_root", "path": f"{engine_id}/model.json"}, {"root": "environments_root", "path": f"{engine_id}/venv/Scripts/python.exe"}]},
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
                    "display_name": f"{model['label']} - {'Brut' if suffix == 'raw' else 'ONNX'}",
                    "tagline": f"{model_format} - {'poids originaux' if suffix == 'raw' else 'graphe portable CPU/GPU'}",
                    "description": "Original Transformers weights with full precision and maximum compatibility." if suffix == "raw" else "Exported ONNX graph for portable inference with ONNX Runtime.",
                    "source": f"https://huggingface.co/{raw_repo}",
                    "requirements": {**alternate["requirements"], "disk_space_gb": round(max(size * multiplier, 0.5) + 1.5, 2), "download_size_gb": round(max(size * multiplier, 0.4), 2), "recommended_vram_gb": max(int(model.get("vram_gb", 1) * (1.7 if suffix == "raw" else 1.25)), 2)},
                    "model": {**alternate["model"], "repo_id": raw_repo, "original_repo_id": raw_repo, "runtime": runtime, "format": model_format, "quantization": "FP16 / FP32" if suffix == "raw" else "ONNX Runtime", "variant": f"{model['label']} - {model_format}"},
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
            shared_runtime_id = translation_runtime_id(model)
            payload["engines"].append({
                "id": engine_id,
                "display_name": model["label"],
                "category": "translation",
                "tagline": f"{model.get('quantization', 'local')} - {model.get('tier', 'local').title()} - {model.get('languages', 'multilingual')}",
                "description": "Quantized local translation model. The selected artifact, runtime, provenance and license are recorded in a portable manifest.",
                "installable": True,
                "source": f"https://huggingface.co/{model['repo_id']}",
                "license": model.get("license", "See model card"),
                "capabilities": ["translation", str(model.get("quantization", "quantized")), "context-adaptation", "duration-adaptation"] if model.get("kind") == "causal" else ["translation", str(model.get("quantization", "INT8")), "many-to-many", "low-resource-languages"],
                "languages": [model.get("languages", "multilingual")],
                "requirements": {"disk_space_gb": round(size * 1.25 + 1.2, 2), "download_size_gb": size, "minimum_ram_gb": 8 if model.get("vram_gb", 2) <= 4 else 16, "recommended_vram_gb": model.get("vram_gb", 2)},
                "model": {"repo_id": model["repo_id"], "revision": "main", "runtime_id": shared_runtime_id, "family_id": f"translation-{str(model.get('family', engine_id)).lower().replace(' ', '-').replace('.', '-')}", "format": "GGUF" if model.get("runtime") == "llama_cpp" else "CTranslate2", "variant": model.get("label"), **model},
                "installer": {"script": "install-huggingface-translation.ps1", "steps": ["Create or reuse the shared translation runtime", f"Install {model.get('runtime', 'local')} backend once", f"Download only {model.get('quantization', 'selected')} weights", "Write provenance and verified local manifest"], "checks": [{"root": "models_root", "path": f"{engine_id}/model.json"}, {"root": "environments_root", "path": f"{shared_runtime_id}/venv/Scripts/python.exe"}]},
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
                    "display_name": f"{model.get('family', model['label'])} {parameters:g}B - {'Brut' if suffix == 'raw' else 'ONNX'}",
                    "tagline": f"{model_format} - {model.get('languages', 'multilingual')} - poids originaux",
                    "description": "Original model weights for maximum quality and fine-tuning compatibility." if suffix == "raw" else "Portable ONNX export optimized for local inference providers.",
                    "source": f"https://huggingface.co/{original_repo}",
                    "requirements": {**alternate["requirements"], "disk_space_gb": disk, "download_size_gb": round(disk - 1.2, 2), "minimum_ram_gb": max(8, int(parameters * 3)), "recommended_vram_gb": max(2, int(parameters * (2.2 if suffix == "raw" else 1.65)))},
                    "model": {**alternate["model"], "repo_id": original_repo, "original_repo_id": original_repo, "file_name": "", "runtime": runtime, "runtime_id": translation_runtime_id({"runtime": runtime}), "format": model_format, "quantization": "BF16 / FP16" if suffix == "raw" else "ONNX Runtime", "variant": f"{model.get('family', model['label'])} {parameters:g}B - {model_format}"},
                    "installer": {"script": "install-huggingface-translation.ps1", "steps": ["Create or reuse the shared translation runtime", f"Install {model_format} backend once", "Download original weights" if suffix == "raw" else "Export verified ONNX graph", "Write provenance and local manifest"], "checks": [{"root": "models_root", "path": f"{variant_id}/model.json"}, {"root": "environments_root", "path": f"{translation_runtime_id({'runtime': runtime})}/venv/Scripts/python.exe"}]},
                })
                payload["engines"].append(alternate)
    if TTS_CATALOG_PATH.exists():
        payload["engines"].extend(build_engine_entries(TTS_CATALOG_PATH))
    payload["engines"] = [
        item for item in payload["engines"] if item.get("id") != "asr-funasr-zh"
    ]
    payload["engines"].append({
        "id": "asr-funasr-zh",
        "display_name": "Paraformer-zh · Mandarin CUDA",
        "category": "asr",
        "adapter": "funasr-zh",
        "tagline": "Mandarin production ASR · timestamps · shared CUDA runtime",
        "description": "Chinese-specialized Paraformer with FSMN-VAD. Selected automatically for zh projects; Whisper remains the fallback for other languages.",
        "installable": False,
        "source": "https://huggingface.co/funasr/paraformer-zh",
        "license": "Apache-2.0",
        "capabilities": ["transcription", "mandarin", "timestamps", "vad", "cuda"],
        "languages": ["zh", "zh-CN", "zh-TW"],
        "requirements": {
            "disk_space_gb": 1.1,
            "download_size_gb": 0.83,
            "minimum_ram_gb": 8,
            "recommended_vram_gb": 4
        },
        "model": {
            "repo_id": "funasr/paraformer-zh",
            "revision": "main",
            "runtime": "funasr",
            "format": "PyTorch",
            "family": "Paraformer",
            "variant": "Paraformer-zh + FSMN-VAD",
            "quantization": "CUDA FP32"
        },
        "installer": {
            "steps": ["Reuse shared Torch 2.8 CUDA", "Load Paraformer-zh", "Load FSMN-VAD", "Run Mandarin CUDA smoke test"],
            "checks": [
                {"root": "models_root", "path": "asr-funasr-zh/model.json"},
                {"root": "environments_root", "path": "asr-funasr-zh/venv/Scripts/python.exe"}
            ]
        }
    })
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
    artifacts_present = _model_artifacts_present(engine)
    if state.get("status") in {"queued", "installing", "repairing"}:
        status = state["status"]
    elif detected:
        status = "ready"
    elif artifacts_present:
        status = "needs_repair"
    elif state.get("status") in {"failed", "cancelled"}:
        status = state["status"]
    else:
        status = "not_installed"
    verification = _capability_verification(engine, detected, artifacts_present)
    ready = status == "ready"
    return {
        **engine,
        "brand": _brand_for_engine(engine),
        "installation": {
            "status": status,
            "progress": 100 if ready else int(state.get("progress", 0)),
            "message": "Engine ready" if ready else state.get("message", "Available to install"),
            "updated_at": state.get("updated_at"),
            "log_path": state.get("log_path"),
            "phase": state.get("phase"),
            "downloaded_bytes": state.get("downloaded_bytes"),
            "total_bytes": state.get("total_bytes"),
            "speed_bps": state.get("speed_bps"),
            "eta_seconds": state.get("eta_seconds"),
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
        "systran": "whisper", "rvc": "rvc", "kokoro": "kokoro", "luxtts": "luxtts",
        "qwen3": "qwen", "chatterbox": "chatterbox", "tada": "tada", "supertonic": "supertonic",
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


def _capability_verification(
    engine: dict[str, Any],
    detected: bool,
    artifacts_present: bool = False,
) -> dict[str, Any]:
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
    elif adapter == "rvc":
        adapter_path = PATHS.workspace / "services" / "api" / "app" / "rvc_service.py"
        adapter_ready = adapter_path.is_file() and (PATHS.installers / "run-rvc.py").is_file()
    elif adapter == "subclean":
        adapter_path = PATHS.workspace / "services" / "api" / "app" / "subclean_service.py"
        adapter_ready = adapter_path.is_file()
    elif adapter == "native-tts":
        adapter_name = "native-tts-worker"
        adapter_path = PATHS.installers / "run-tts.py"
        adapter_ready = adapter_path.is_file()
    elif adapter == "funasr-zh":
        adapter_name = "funasr-zh-worker"
        adapter_path = PATHS.installers / "run-funasr-zh.py"
        adapter_ready = adapter_path.is_file()
    elif category == "asr":
        adapter_name = "asr-worker"
        adapter_path = PATHS.installers / "run-asr.py"
        adapter_ready = adapter_path.is_file()
    elif category == "translation":
        adapter_name = "translation-worker"
        adapter_path = PATHS.workspace / "services" / "api" / "app" / "translation_worker.py"
        adapter_ready = adapter_path.is_file()
    elif category == "alignment":
        adapter_name = "whisperx-worker"
        adapter_path = PATHS.installers / "run-whisperx.py"
        adapter_ready = adapter_path.is_file()
    elif category == "separation":
        adapter_name = "audio-separation-worker"
        adapter_path = PATHS.installers / "run-audio-separation.py"
        adapter_ready = adapter_path.is_file()
    elif category == "diarization":
        adapter_name = "speaker-diarization-worker"
        adapter_path = PATHS.installers / "run-speaker-diarization.py"
        adapter_ready = adapter_path.is_file()
    else:
        adapter_name = ""
        adapter_ready = False

    manifest_path = PATHS.environments / engine_id / "ready.json"
    runtime_manifest_path = PATHS.environments / engine_runtime_id(engine) / "ready.json"
    smoke_test = False
    smoke_label = "not-run"
    if engine_id == "ffmpeg-system":
        smoke_test = adapter_ready
        smoke_label = "command-version" if smoke_test else "failed"
    elif manifest_path.is_file() or runtime_manifest_path.is_file():
        selected_manifest = (
            manifest_path if manifest_path.is_file() else runtime_manifest_path
        )
        try:
            manifest = json.loads(selected_manifest.read_text(encoding="utf-8-sig"))
            smoke_label = str(manifest.get("self_test") or "installer-validation")
            smoke_test = True
        except (json.JSONDecodeError, OSError):
            smoke_label = "invalid-manifest"
    elif detected and _read_state(engine_id).get("status") == "ready":
        # Some shared-runtime installers predate per-model ready manifests. A
        # successful installer state plus all current file/runtime checks is the
        # recorded smoke test for those installations.
        smoke_test = True
        smoke_label = "installer-completed"

    installed = bool(detected or artifacts_present)
    usable = bool(detected and adapter_ready and smoke_test)
    if not installed:
        status = "not-installed"
        message = "Runtime or model is not installed"
    elif not detected:
        status = "needs-repair"
        message = "Model files are downloaded, but the runtime needs repair or validation"
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
    runtime_id = engine_runtime_id(engine)
    return {
        "engine_id": engine_id,
        "display_name": engine.get("display_name", engine_id),
        "disk_space_gb": engine.get("requirements", {}).get("disk_space_gb"),
        "steps": installer.get("steps", []),
        "script": installer.get("script"),
        "environment_root": str(PATHS.environments / runtime_id),
        "shared_runtime_id": runtime_id,
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
    engine_model = engine.get("model") or {}
    shared_runtime_id = engine_runtime_id(engine)
    script_path = (PATHS.installers / engine["installer"]["script"]).resolve()
    state_root = INSTALL_STATE_ROOT / engine_id
    state_root.mkdir(parents=True, exist_ok=True)
    log_path = state_root / "install.log"
    status = "repairing" if repair else "installing"
    _write_state(engine_id, {"status": status, "progress": 5, "message": "Installer started", "log_path": str(log_path), "updated_at": _now()})
    env = os.environ.copy()
    base_python = Path(sys.executable).resolve()
    env["PATH"] = f"{base_python.parent}{os.pathsep}{env.get('PATH', '')}"
    env.update({
        "DUB_ENGINE_ID": engine_id,
        "DUB_BASE_PYTHON": str(base_python),
        # Keep the model installation marker separate from the compatibility
        # runtime. Several Qwen or Chatterbox variants can share one Python
        # environment without overwriting each other's ready.json manifest.
        "DUB_ENGINE_ENV": str(PATHS.environments / engine_id),
        "DUB_TTS_RUNTIME_ENV": str(PATHS.environments / shared_runtime_id),
        "DUB_ENGINE_MODELS": str(PATHS.models / engine_id),
        "DUB_ENGINE_CACHE": str(PATHS.cache / engine_id),
        "DUB_ENGINE_STATE": str(_state_path(engine_id)),
        "DUB_ENGINE_LOG": str(log_path),
        "DUB_ENGINE_REPAIR": "1" if repair else "0",
        "HF_HOME": str(PATHS.cache / "huggingface"),
        "HF_HUB_DISABLE_XET": "1",
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
        "DUB_TTS_FAMILY": str((engine.get("model") or {}).get("family", "")),
        "DUB_TTS_PACKAGE": str((engine.get("model") or {}).get("package", "")),
        "DUB_TTS_PYTHON": str((engine.get("model") or {}).get("python", "3.12")),
    })
    credentials = credentials or {}
    if credentials.get("hf_token"):
        env["HF_TOKEN"] = credentials["hf_token"]
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)]
    process: subprocess.Popen[str] | None = None
    try:
        stale_venv = _quarantine_stale_venv(shared_runtime_id)
        with log_path.open("a", encoding="utf-8") as log_file:
            if stale_venv:
                log_file.write(f"Moved non-portable Python environment to {stale_venv}\n")
            process = subprocess.Popen(command, env=env, cwd=PATHS.workspace, stdout=log_file, stderr=subprocess.STDOUT, text=True)
            with _install_lock:
                _install_processes[engine_id] = process
            started_at = time.monotonic()
            last_heartbeat = 0.0
            while process.poll() is None:
                time.sleep(1)
                elapsed = time.monotonic() - started_at
                if elapsed - last_heartbeat >= 10:
                    current_state = _read_state(engine_id)
                    base_message = str(current_state.get("message") or "Installer active").split(" · active ")[0]
                    minutes, seconds = divmod(int(elapsed), 60)
                    current_state.update({
                        "message": f"{base_message} · active {minutes}m {seconds:02d}s",
                        "elapsed_seconds": round(elapsed, 1),
                        "updated_at": _now(),
                    })
                    _write_state(engine_id, current_state)
                    last_heartbeat = elapsed
            return_code = process.returncode
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
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, check=False)
        else:
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
    if engine.get("adapter") == "native-tts":
        engine_id = str(engine.get("id") or "")
        runtime_id = engine_runtime_id(engine)
        model_manifest = PATHS.models / engine_id / "model.json"
        runtime_python = (
            PATHS.environments
            / runtime_id
            / "venv"
            / "Scripts"
            / "python.exe"
        )
        validation_manifest = PATHS.environments / engine_id / "ready.json"
        shared_validation_manifest = PATHS.environments / runtime_id / "ready.json"
        return bool(
            _model_artifacts_present(engine)
            and model_manifest.is_file()
            and _python_runtime_usable(runtime_python)
            and (
                validation_manifest.is_file()
                or shared_validation_manifest.is_file()
            )
        )

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
        candidate = root / relative if root and relative else None
        if not candidate or not candidate.exists():
            return False
        if candidate.name.lower() == "python.exe" and not _python_runtime_usable(candidate):
            return False
    return True


def _model_artifacts_present(engine: dict[str, Any]) -> bool:
    """Detect downloaded weights separately from a healthy executable runtime."""
    engine_id = str(engine.get("id") or "")
    if not engine_id:
        return False
    candidates = [PATHS.models / engine_id / "model.json"]
    if engine_id.startswith("faster-whisper-"):
        candidates.append(
            PATHS.models
            / "asr"
            / "faster-whisper"
            / engine_id
            / "model.json"
        )
    for manifest_path in candidates:
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            continue
        referenced = [
            manifest.get("model_path"),
            manifest.get("snapshot"),
            manifest.get("file_path"),
        ]
        paths = [Path(str(value)) for value in referenced if value]
        if not paths and manifest_path.parent.name == engine_id:
            paths = [
                manifest_path.parent / "model",
                manifest_path.parent / "snapshot",
            ]
        if any(
            path.is_file()
            or (path.is_dir() and any(item.is_file() for item in path.rglob("*")))
            for path in paths
        ):
            return True
    return False


def _python_runtime_usable(python_executable: Path) -> bool:
    try:
        completed = subprocess.run(
            [str(python_executable), "-c", "import sys; print(sys.executable)"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _quarantine_stale_venv(engine_id: str) -> Path | None:
    venv_path = PATHS.environments / engine_id / "venv"
    python_executable = venv_path / "Scripts" / "python.exe"
    if not venv_path.exists() or _python_runtime_usable(python_executable):
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = venv_path.with_name(f"venv.stale-{stamp}")
    counter = 1
    while backup.exists():
        backup = venv_path.with_name(f"venv.stale-{stamp}-{counter}")
        counter += 1
    venv_path.rename(backup)
    return backup


def _system_command_exists(command: str | None) -> bool:
    if not command:
        return False
    resolved = _resolve_system_command(command)
    if not resolved:
        return False
    try:
        version_args = ["-L"] if command.lower().removesuffix(".exe") == "nvidia-smi" else ["-version"]
        return subprocess.run([resolved, *version_args], capture_output=True, timeout=4, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _shared_cuda_runtime_exists() -> bool:
    torch_lib = (
        PATHS.environments
        / "rvc-runtime"
        / "venv"
        / "Lib"
        / "site-packages"
        / "torch"
        / "lib"
    )
    return (torch_lib / "cublas64_12.dll").is_file() and (torch_lib / "cudnn64_9.dll").is_file()


def _resolve_system_command(command: str) -> str | None:
    from shutil import which

    resolved = which(command)
    if resolved:
        return resolved
    if os.name != "nt":
        return None

    executable = command if command.lower().endswith(".exe") else f"{command}.exe"
    candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        try:
            for package_dir in winget_root.glob("Gyan.FFmpeg_*"):
                candidates.extend(package_dir.glob("ffmpeg-*/bin"))
        except OSError:
            pass
    candidates.extend(
        [
            PATHS.data / "bin",
            PATHS.data / "tools" / "ffmpeg" / "bin",
            PATHS.workspace / "bin",
        ]
    )
    for directory in candidates:
        candidate = directory / executable
        if candidate.is_file():
            return str(candidate)
    return None


def _state_path(engine_id: str) -> Path:
    return INSTALL_STATE_ROOT / engine_id / "state.json"


def _read_state(engine_id: str) -> dict[str, Any]:
    path = _state_path(engine_id)
    if not path.exists():
        return {}
    for attempt in range(3):
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, OSError):
            if attempt < 2:
                import time
                time.sleep(0.05 * (attempt + 1))
    return {}


def _write_state(engine_id: str, state: dict[str, Any]) -> None:
    path = _state_path(engine_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(state, indent=2)
    for attempt in range(3):
        try:
            path.write_text(serialized, encoding="utf-8")
            return
        except OSError:
            if attempt < 2:
                import time
                time.sleep(0.05 * (attempt + 1))
    raise OSError(f"Could not update engine state after retries: {path}")
