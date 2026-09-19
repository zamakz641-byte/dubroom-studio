from __future__ import annotations

import json
from pathlib import Path
from typing import Any


RUNTIME_ENGINE_BY_FAMILY = {
    "omnivoice": "tts-omnivoice-hq",
    "supertonic": "tts-supertonic-3",
    "kokoro": "tts-kokoro-82m",
    "kyutai_pocket": "tts-kyutai-pocket",
    "cosyvoice3_gguf": "tts-cosyvoice3-gguf",
    "luxtts": "tts-luxtts",
    "qwen3": "tts-qwen3-0.6b-base",
    "chatterbox": "tts-chatterbox-turbo",
    "tada": "tts-tada-1b",
}


def runtime_engine_id(model: dict[str, Any]) -> str:
    explicit = str(model.get("runtime_engine_id") or "").strip()
    if explicit:
        return explicit
    family = str(model.get("family") or "")
    return RUNTIME_ENGINE_BY_FAMILY.get(family, str(model["id"]))


def build_engine_entries(catalog_path: Path) -> list[dict[str, Any]]:
    if not catalog_path.is_file():
        return []
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    result: list[dict[str, Any]] = []
    for model in payload.get("models", []):
        engine_id = str(model["id"])
        runtime_id = runtime_engine_id(model)
        size_mb = int(model.get("size_mb") or 0)
        gated = bool(model.get("gated"))
        packages = model.get("packages")
        if not isinstance(packages, list):
            packages = [model.get("package")] if model.get("package") else []
        installer_script = str(model.get("installer_script") or "install-tts-engine.ps1")
        model_format = str(model.get("format") or ("ONNX" if model.get("family") == "supertonic" else "PyTorch"))
        entry = {
            "id": engine_id,
            "display_name": model["display_name"],
            "category": "voice",
            "tagline": str(model.get("tagline") or f"{model.get('tier', 'local').title()} · {len(model.get('languages') or [])} languages · direct local inference"),
            "description": str(model.get("description") or "Native TTS engine. DubRoom calls the official Python API directly and reuses one isolated runtime per model family."),
            "installable": True,
            "source": model["source"],
            "license": model["license"],
            "adapter": "native-tts",
            "capabilities": [
                "speech-synthesis",
                "local-inference",
                "shared-family-runtime",
                *(str(item) for item in model.get("voice_modes") or []),
                *(str(item) for item in model.get("capabilities") or []),
            ],
            "languages": model.get("languages") or [],
            "requirements": {
                "disk_space_gb": round(size_mb / 1024 * 1.35 + 1.2, 2),
                "download_size_gb": round(size_mb / 1024, 2),
                "minimum_ram_gb": model.get("minimum_ram_gb", 8),
                "recommended_vram_gb": model.get("recommended_vram_gb", 0),
            },
            "model": {
                **model,
                "repo_id": model.get("hf_repo_id"),
                "revision": "main",
                "runtime": "dubroom-native-tts",
                "runtime_id": runtime_id,
                "family_id": f"tts-{model.get('family')}",
                "format": model_format,
                "variant": model.get("display_name"),
            },
            "installer": {
                "script": installer_script,
                "packages": packages,
                "steps": list(model.get("install_steps") or [
                    f"Create or reuse the shared {model.get('family')} Python {model.get('python', '3.12')} environment",
                    f"Install the selected {model_format} runtime",
                    "Download only the selected precision files into the project disk",
                    "Validate the native DubRoom worker and write a local manifest",
                ]),
                "checks": [
                    {"root": "models_root", "path": f"{engine_id}/model.json"},
                    {"root": "environments_root", "path": f"{engine_id}/ready.json"},
                    {"root": "environments_root", "path": f"{runtime_id}/venv/Scripts/python.exe"},
                ],
            },
        }
        if gated:
            entry["credentials"] = [{
                "id": "hf_token",
                "label": "Hugging Face token",
                "secret": True,
                "required": True,
                "help_url": "https://huggingface.co/settings/tokens",
            }]
        result.append(entry)
    return result
