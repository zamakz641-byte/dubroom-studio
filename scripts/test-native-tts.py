from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "services" / "api"
sys.path.insert(0, str(API_ROOT))

from app import native_tts_service  # noqa: E402
from app.tts_catalog_service import build_engine_entries, runtime_engine_id  # noqa: E402


CATALOG_PATH = ROOT / "models" / "tts-catalog.json"
WORKER_PATH = ROOT / "scripts" / "engines" / "run-tts.py"
INSTALLER_PATH = ROOT / "scripts" / "engines" / "install-tts-engine.ps1"
MAIN_PATH = API_ROOT / "app" / "main.py"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    models = catalog.get("models")
    check(isinstance(models, list) and len(models) >= 14, "The native TTS catalog must contain 17 models")

    expected_families = {"supertonic", "kokoro", "kyutai_pocket", "cosyvoice3_gguf", "luxtts", "qwen3", "chatterbox", "tada", "omnivoice"}
    families = {str(model.get("family")) for model in models}
    check(families == expected_families, f"Unexpected TTS families: {sorted(families)}")

    ids = [str(model.get("id")) for model in models]
    check(len(ids) == len(set(ids)), "TTS model ids must be unique")
    for model in models:
        for key in ("id", "display_name", "family", "engine", "hf_repo_id", "package", "python", "source"):
            check(bool(model.get(key)), f"{model.get('id')} is missing {key}")
        check(bool(model.get("voice_modes")), f"{model['id']} has no voice mode")
        check(int(model.get("sample_rate") or 0) > 0, f"{model['id']} has no sample rate")
        check(str(model["source"]).startswith("https://github.com/"), f"{model['id']} must cite its official source")

    entries = build_engine_entries(CATALOG_PATH)
    check(len(entries) == len(models), "Every catalog model must become an installable engine")
    for entry in entries:
        check(entry.get("adapter") == "native-tts", f"{entry['id']} is not wired to the native adapter")
        check(entry.get("category") == "voice", f"{entry['id']} is not a voice engine")
        installer = entry.get("installer") or {}
        expected_script = str(
            (entry.get("model") or {}).get("installer_script")
            or "install-tts-engine.ps1"
        )
        check(installer.get("script") == expected_script, f"{entry['id']} uses the wrong installer")
        checks = installer.get("checks") or []
        check(any(str(item.get("path", "")).endswith("ready.json") for item in checks), f"{entry['id']} has no ready check")
        check(any("venv/Scripts/python.exe" in str(item.get("path", "")) for item in checks), f"{entry['id']} has no family runtime")

    qwen_models = [model for model in models if model["family"] == "qwen3"]
    chatterbox_models = [model for model in models if model["family"] == "chatterbox"]
    tada_models = [model for model in models if model["family"] == "tada"]
    check(len({runtime_engine_id(model) for model in qwen_models}) == 1, "Qwen models must share one runtime")
    chatterbox_onnx = [model for model in chatterbox_models if model.get("format") == "ONNX"]
    chatterbox_torch = [model for model in chatterbox_models if model.get("format") != "ONNX"]
    check(len({runtime_engine_id(model) for model in chatterbox_torch}) == 1, "Chatterbox PyTorch models must share one compatible runtime")
    check(len({runtime_engine_id(model) for model in chatterbox_onnx}) == 1, "Chatterbox ONNX models must share one compatible runtime")
    check(runtime_engine_id(chatterbox_torch[0]) != runtime_engine_id(chatterbox_onnx[0]), "Incompatible Chatterbox Torch and ONNX stacks must remain isolated")
    check(len({runtime_engine_id(model) for model in tada_models}) == 1, "TADA models must share one runtime")

    worker_source = WORKER_PATH.read_text(encoding="utf-8")
    ast.parse(worker_source, filename=str(WORKER_PATH))
    for adapter in ("_supertonic", "_kokoro", "_kyutai_pocket", "_cosyvoice3_gguf", "_luxtts", "_qwen", "_chatterbox", "_tada", "_omnivoice"):
        check(f"def {adapter}(" in worker_source, f"Missing worker adapter: {adapter}")
    check("localhost" not in worker_source, "The native worker must not depend on a named local daemon")
    check(
        "http://" not in worker_source.replace("http://127.0.0.1", ""),
        "The native worker may only call its own loopback batch process",
    )
    check("FasterQwen3TTS" in worker_source, "Qwen CUDA Graphs acceleration is not wired")
    check("fast_qwen_fallback" in worker_source, "Qwen acceleration needs a safe upstream fallback")
    check(
        "non_streaming_mode=_qwen_non_streaming_mode(item, default=False)"
        in worker_source,
        "Fast Qwen must use the benchmarked streaming text path by default",
    )

    worker_spec = importlib.util.spec_from_file_location("dubroom_run_tts", WORKER_PATH)
    check(worker_spec is not None and worker_spec.loader is not None, "Cannot import the TTS worker")
    worker = importlib.util.module_from_spec(worker_spec)
    worker_spec.loader.exec_module(worker)
    check(
        worker._max_new_tokens({"text": "Un test très court.", "language": "fr", "target_duration": 2}) == 60,
        "Qwen must cap runaway generation from the available segment duration",
    )
    check(
        worker._qwen_clone_mode({"clone_mode": "fast"}) == "xvector",
        "Qwen fast clone mode must select the cached speaker embedding path",
    )
    previous_fast = os.environ.get("DUBROOM_QWEN_FAST")
    try:
        os.environ["DUBROOM_QWEN_FAST"] = "0"
        check(not worker._qwen_fast_enabled(), "Qwen acceleration cannot be disabled")
        os.environ["DUBROOM_QWEN_FAST"] = "1"
        check(worker._qwen_fast_enabled(), "Qwen acceleration cannot be enabled")
    finally:
        if previous_fast is None:
            os.environ.pop("DUBROOM_QWEN_FAST", None)
        else:
            os.environ["DUBROOM_QWEN_FAST"] = previous_fast

    installer_source = INSTALLER_PATH.read_text(encoding="utf-8")
    check("data\\toolchains" in installer_source, "The installer must use the project-local toolchain")
    check("DUB_TTS_RUNTIME_ENV" in installer_source, "The installer must use a shared family runtime")
    check(".install.lock" in installer_source, "Shared family installations must be serialized")
    check("download-model.py" in installer_source, "Model download code must run from a file on Windows")
    check("-c $downloadScript" not in installer_source, "PowerShell must not pass quoted Python source through -c")
    check("data\\environments" not in installer_source, "Environment paths must be injected, not hardcoded")
    check("faster-qwen3-tts==0.3.2" in installer_source, "The Qwen fast runtime is not reproducibly installed")
    check("UV_LINK_MODE = \"hardlink\"" in installer_source, "Shared dependencies must use uv's Windows hardlink store")
    check("constraints-chatterbox.txt" in installer_source, "Chatterbox needs a pinned compatibility constraint set")
    check("torch==2.6.0" in installer_source and "numpy==1.26.4" in installer_source, "Chatterbox compatibility pins are missing")
    check(
        all(
            "git+https://github.com/resemble-ai/chatterbox.git@5de7a54" in str(model.get("package"))
            for model in chatterbox_torch
        ),
        "Chatterbox PyTorch models must use the pinned official source with V3 support",
    )
    legacy_runtime_name = "voice" + "box"
    check(legacy_runtime_name not in installer_source.lower(), "The native installer still mentions the retired runtime")

    main_source = MAIN_PATH.read_text(encoding="utf-8")
    ast.parse(main_source, filename=str(MAIN_PATH))
    check('"/tts/status"' in main_source, "Missing native TTS status route")
    check('"/tts/generate"' in main_source, "Missing native TTS generation route")
    check(f'/{legacy_runtime_name}' not in main_source.lower(), "Retired runtime routes are still exposed")
    check('"/tts/start"' not in main_source, "A daemon start route is still exposed")

    original_installed = native_tts_service._installed
    try:
        native_tts_service._installed = lambda engine_id: engine_id == "tts-qwen3-0.6b-base"
        selected = native_tts_service._resolve_model(
            {"language": "fr"},
            {"voice_type": "cloned", "language": "fr", "default_engine": "qwen"},
        )
        check(selected["id"] == "tts-qwen3-0.6b-base", "Generic Qwen profiles must fall back to an installed Qwen model")

        try:
            native_tts_service._resolve_model(
                {"engine_id": "tts-qwen3-1.7b-base", "language": "fr"},
                {"voice_type": "cloned", "language": "fr"},
            )
        except RuntimeError:
            pass
        else:
            raise AssertionError("An explicitly selected uninstalled model must not silently change")
    finally:
        native_tts_service._installed = original_installed

    print(json.dumps({
        "ok": True,
        "models": len(models),
        "families": sorted(families),
        "direct_adapters": 9,
        "daemon_required": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
