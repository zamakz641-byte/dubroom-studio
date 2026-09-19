from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from . import (
    local_voice_service,
    resource_scheduler,
    voice_library_service,
    voice_cleanup_service,
    voice_reference_service,
)
from .config import PATHS
from .open_source_policy import is_open_source_license
from .tts_catalog_service import runtime_engine_id


CATALOG_PATH = PATHS.models / "tts-catalog.json"
DATA_ROOT = PATHS.data / "tts"
GENERATIONS_ROOT = DATA_ROOT / "generations"
AUDIO_ROOT = DATA_ROOT / "audio"
PROFILE_ROOT = PATHS.data / "voice-profiles"
WORKER_PATH = PATHS.installers / "run-tts.py"
_threads: dict[str, threading.Thread] = {}
_design_threads: dict[str, threading.Thread] = {}
_design_locks: dict[str, threading.Lock] = {}
_lock = threading.Lock()


class TTSBatchCancelled(RuntimeError):
    """Raised after the active native TTS worker has been stopped."""


def _stop_worker(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        # Some native engines keep a resident child server. Killing the whole
        # worker tree makes Cancel immediate and prevents a hidden model from
        # continuing to use CPU/GPU after the UI has stopped the job.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return
    try:
        process.terminate()
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError:
            pass


ENGINE_ALIASES = {
    "omnivoice": "tts-omnivoice-hq",
    "omnivoice_hq": "tts-omnivoice-hq",
    "supertonic": "tts-supertonic-3",
    "kokoro": "tts-kokoro-82m",
    "kyutai_pocket": "tts-kyutai-pocket-fr",
    "cosyvoice3": "tts-cosyvoice3-gguf",
    "cosyvoice3_gguf": "tts-cosyvoice3-gguf",
    "luxtts": "tts-luxtts",
    # The 0.6B CUDA-graph runtime is the production-speed default. Explicit
    # 1.7B ids remain available for premium-quality takes.
    "qwen": "tts-qwen3-0.6b-base",
    "qwen_fast": "tts-qwen3-0.6b-base",
    "qwen_custom_voice": "tts-qwen3-0.6b-custom",
    "qwen_voice_design": "tts-qwen3-1.7b-design",
    "chatterbox_nano": "tts-chatterbox-nano",
    "chatterbox_turbo": "tts-chatterbox-turbo-onnx-fp16",
    "chatterbox_turbo_onnx": "tts-chatterbox-turbo-onnx-fp16",
    "chatterbox_turbo_onnx_fp16": "tts-chatterbox-turbo-onnx-fp16",
    "chatterbox_turbo_onnx_q4f16": "tts-chatterbox-turbo-onnx-q4f16",
    "chatterbox_turbo_pytorch": "tts-chatterbox-turbo",
    "chatterbox": "tts-chatterbox-multilingual-v3",
    "chatterbox_multilingual": "tts-chatterbox-multilingual-v3",
    "chatterbox_multilingual_v3": "tts-chatterbox-multilingual-v3",
    "chatterbox_mtl": "tts-chatterbox-multilingual-v3",
    "tada": "tts-tada-1b",
}



DEFAULT_DESIGN_REFERENCE_TEXTS = {
    "fr": (
        "Personne ne comprenait pourquoi il restait aussi calme. Pourtant, lorsqu'il releva les yeux, "
        "tout le monde comprit que la bataille avait dÃ©jÃ  commencÃ©. Sa voix resta claire, posÃ©e et "
        "assurÃ©e, mÃªme lorsque le danger se rapprocha. Puis il ajouta, avec une lÃ©gÃ¨re ironie, que le "
        "vÃ©ritable problÃ¨me ne faisait que commencer."
    ),
    "en": (
        "Nobody understood why he remained so calm. Yet when he finally looked up, everyone realized "
        "the battle had already begun. His voice stayed clear, controlled, and confident as the danger "
        "moved closer. Then, with a trace of irony, he explained that the real problem was only beginning."
    ),
    "es": (
        "Nadie entendÃ­a por quÃ© seguÃ­a tan tranquilo. Sin embargo, cuando levantÃ³ la mirada, todos "
        "comprendieron que la batalla ya habÃ­a comenzado. Su voz permaneciÃ³ clara, firme y segura, "
        "incluso cuando el peligro se acercÃ³. Entonces aÃ±adiÃ³, con una ligera ironÃ­a, que el verdadero "
        "problema apenas estaba empezando."
    ),
}

def _tts_model_allowed(model: dict[str, Any] | None) -> bool:
    # Keep the strict policy, except models explicitly tagged local-only/non-commercial.
    if not model:
        return False
    if is_open_source_license(str(model.get("license") or "")):
        return True
    return bool(
        model.get("local_only")
        and model.get("local_only_noncommercial")
        and model.get("commercial_use") is False
    )


PRESET_VOICES = {
    "kyutai_pocket": [
        {"voice_id": "estelle", "name": "Estelle", "gender": "female", "language": "fr"},
    ],
    "kokoro": [
        {"voice_id": "af_heart", "name": "Heart", "gender": "female", "language": "en"},
        {"voice_id": "af_bella", "name": "Bella", "gender": "female", "language": "en"},
        {
            "voice_id": "am_liam",
            "name": "Liam",
            "gender": "male",
            "language": "en",
            # Kokoro separates text phonemization from the speaker embedding.
            # Liam is intentionally exposed for French dubbing even though the
            # original voice pack is English.
            "cross_language": True,
        },
        {"voice_id": "bf_emma", "name": "Emma", "gender": "female", "language": "en"},
        {"voice_id": "bm_george", "name": "George", "gender": "male", "language": "en"},
        {"voice_id": "ef_dora", "name": "Dora", "gender": "female", "language": "es"},
        {"voice_id": "em_alex", "name": "Alex", "gender": "male", "language": "es"},
        {"voice_id": "ff_siwis", "name": "Siwis", "gender": "female", "language": "fr"},
        {"voice_id": "hf_alpha", "name": "Alpha", "gender": "female", "language": "hi"},
        {"voice_id": "if_sara", "name": "Sara", "gender": "female", "language": "it"},
        {"voice_id": "jf_alpha", "name": "Alpha JP", "gender": "female", "language": "ja"},
        {"voice_id": "pf_dora", "name": "Dora PT", "gender": "female", "language": "pt"},
        {"voice_id": "zf_xiaobei", "name": "Xiaobei", "gender": "female", "language": "zh"},
    ],
    "supertonic": [
        *[
            {"voice_id": f"M{index}", "name": f"Male {index}", "gender": "male", "language": "multi"}
            for index in range(1, 6)
        ],
        *[
            {"voice_id": f"F{index}", "name": f"Female {index}", "gender": "female", "language": "multi"}
            for index in range(1, 6)
        ],
    ],
    "qwen_custom_voice": [
        {"voice_id": "Vivian", "name": "Vivian", "gender": "female", "language": "zh"},
        {"voice_id": "Serena", "name": "Serena", "gender": "female", "language": "zh"},
        {"voice_id": "Uncle_Fu", "name": "Uncle Fu", "gender": "male", "language": "zh"},
        {"voice_id": "Dylan", "name": "Dylan", "gender": "male", "language": "zh"},
        {"voice_id": "Eric", "name": "Eric", "gender": "male", "language": "zh"},
        {"voice_id": "Ryan", "name": "Ryan", "gender": "male", "language": "en"},
        {"voice_id": "Aiden", "name": "Aiden", "gender": "male", "language": "en"},
        {"voice_id": "Ono_Anna", "name": "Ono Anna", "gender": "female", "language": "ja"},
        {"voice_id": "Sohee", "name": "Sohee", "gender": "female", "language": "ko"},
    ],
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()



def _language_code(value: Any) -> str:
    return str(value or "en").lower().split("-", 1)[0]


def _default_design_reference_text(language: str) -> str:
    code = _language_code(language)
    return DEFAULT_DESIGN_REFERENCE_TEXTS.get(code, DEFAULT_DESIGN_REFERENCE_TEXTS["en"])


def _profile_design_lock(profile_id: str) -> threading.Lock:
    with _lock:
        return _design_locks.setdefault(profile_id, threading.Lock())


def _catalog_model(model_id: str) -> dict[str, Any] | None:
    return next((item for item in _catalog() if str(item.get("id")) == model_id), None)


def _profile_qwen_size(profile: dict[str, Any]) -> str:
    values = [
        profile.get("clone_engine_id"),
        profile.get("design_engine_id"),
        profile.get("default_engine"),
        profile.get("preset_engine"),
    ]
    joined = " ".join(str(value or "").lower() for value in values)
    return "0.6b" if "0.6b" in joined else "1.7b"


def _design_model_for_profile(profile: dict[str, Any]) -> dict[str, Any]:
    language = _language_code(profile.get("language"))
    preferred = str(profile.get("design_engine_id") or profile.get("default_engine") or "")
    preferred = ENGINE_ALIASES.get(preferred, preferred)
    if preferred.endswith("-base"):
        preferred = preferred[:-5] + "-design"
    exact = _catalog_model(preferred) if preferred else None
    if (
        exact
        and str(exact.get("engine")) in {"qwen_voice_design", "omnivoice"}
        and _tts_model_allowed(exact)
        and _installed(str(exact["id"]))
    ):
        return exact
    size = _profile_qwen_size(profile)
    candidates = [
        model
        for model in _catalog()
        if str(model.get("engine")) in {"qwen_voice_design", "omnivoice"}
        and _tts_model_allowed(model)
        and _installed(str(model["id"]))
        and language in (model.get("languages") or [])
    ]
    candidates.sort(
        key=lambda model: (
            size not in str(model.get("id") or "").lower(),
            not bool(model.get("recommended")),
        )
    )
    if not candidates:
        raise RuntimeError(
            "Aucun moteur Voice Design compatible n'est installÃ© pour prÃ©parer cette voix."
        )
    return candidates[0]


def _clone_model_for_profile(profile: dict[str, Any], design_model: dict[str, Any] | None = None) -> dict[str, Any]:
    language = _language_code(profile.get("language"))
    preferred = str(profile.get("clone_engine_id") or "")
    if not preferred and design_model:
        preferred = str(design_model.get("id") or "").replace("-design", "-base")
    if not preferred:
        default_engine = ENGINE_ALIASES.get(
            str(profile.get("default_engine") or ""),
            str(profile.get("default_engine") or ""),
        )
        preferred = default_engine.replace("-design", "-base")
    exact = _catalog_model(preferred) if preferred else None
    if (
        exact
        and str(exact.get("engine")) in {"qwen", "omnivoice"}
        and _tts_model_allowed(exact)
        and _installed(str(exact["id"]))
    ):
        return exact
    size = _profile_qwen_size(profile)
    candidates = [
        model
        for model in _catalog()
        if str(model.get("engine")) in {"qwen", "omnivoice"}
        and _tts_model_allowed(model)
        and _installed(str(model["id"]))
        and language in (model.get("languages") or [])
    ]
    candidates.sort(
        key=lambda model: (
            size not in str(model.get("id") or "").lower(),
            not bool(model.get("recommended")),
        )
    )
    if not candidates:
        raise RuntimeError(
            "La voix Voice Design a besoin du modÃ¨le Qwen Base correspondant pour Ãªtre verrouillÃ©e et rÃ©utilisÃ©e. "
            "Installe Qwen3-TTS Base 1.7B (ou 0.6B correspondant) depuis Engines."
        )
    return candidates[0]


def _worker_environment(*, device: str, engine_id: str = "") -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "HF_HOME": str(PATHS.cache / "huggingface"),
            "TORCH_HOME": str(PATHS.cache / "torch"),
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
            "DUBROOM_DEVICE": device,
        }
    )
    if device == "cuda" and os.name != "nt":
        environment.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    if device == "cuda" and os.name == "nt" and engine_id == "tts-omnivoice-hq":
        # Transformers v5 async materialization has been observed to crash
        # this Windows CUDA runtime in torch.storage.__getitem__.
        environment["HF_DEACTIVATE_ASYNC_LOAD"] = "1"
        environment["HF_ENABLE_PARALLEL_LOADING"] = "false"
    if device == "cuda":
        environment.setdefault("DUBROOM_QWEN_FAST", "1")
        environment.setdefault(
            "DUBROOM_QWEN_FAST_MAX_SEQ",
            "512",
        )
    return environment


def _run_worker_request(
    *,
    engine_id: str,
    request: dict[str, Any],
    workload: str,
    timeout: int = 1200,
) -> dict[str, Any]:
    python_executable = _runtime_python(engine_id)
    if not python_executable.is_file():
        raise RuntimeError(f"Runtime TTS introuvable pour {engine_id}")
    if not WORKER_PATH.is_file():
        raise RuntimeError("installers/run-tts.py est introuvable")
    GENERATIONS_ROOT.mkdir(parents=True, exist_ok=True)
    request_path = GENERATIONS_ROOT / f"prepare-{uuid4().hex}.request.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    family = str(request.get("family") or "").lower()
    light_cpu = family in {"supertonic", "kyutai_pocket"}
    device = "cpu" if light_cpu else ("cuda" if shutil.which("nvidia-smi") else "cpu")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        with resource_scheduler.model_slot(
            workload,
            device=device,
            light=light_cpu,
        ):
            result = subprocess.run(
                [str(python_executable), str(WORKER_PATH), "--request", str(request_path)],
                cwd=PATHS.workspace,
                env=_worker_environment(device=device, engine_id=engine_id),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=flags,
                check=False,
            )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Ã‰chec inconnu du worker TTS").strip()
            raise RuntimeError(detail[-4000:])
        worker_result: dict[str, Any] = {}
        for line in reversed(result.stdout.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                worker_result = value
                break
        return {**worker_result, "device": device}
    finally:
        request_path.unlink(missing_ok=True)


def _designed_profile_ready(profile: dict[str, Any]) -> bool:
    if str(profile.get("voice_type")) != "designed":
        return False
    if str(profile.get("design_status")) != "ready":
        return False
    reference_path = Path(str(profile.get("design_reference_path") or ""))
    if not reference_path.is_file() or reference_path.stat().st_size <= 44:
        return False
    reference_text = str(profile.get("design_reference_text") or "").strip()
    expected = local_voice_service.design_fingerprint(
        profile,
        reference_text=reference_text,
    )
    return expected == str(profile.get("design_fingerprint") or "")


def prepare_designed_profile(
    profile_id: str,
    *,
    force: bool = False,
    reference_text: str | None = None,
    warm_prompt_cache: bool = True,
) -> dict[str, Any]:
    lock = _profile_design_lock(profile_id)
    with lock:
        profile = local_voice_service.get(profile_id)
        if not profile:
            raise ValueError("profile.not_found")
        if str(profile.get("voice_type")) != "designed":
            raise ValueError("profile.not_designed")
        prompt = str(profile.get("design_prompt") or "").strip()
        if not prompt:
            raise ValueError("profile.design_prompt_required")
        language = _language_code(profile.get("language"))
        chosen_reference_text = str(
            reference_text
            or profile.get("design_reference_text")
            or _default_design_reference_text(language)
        ).strip()
        fingerprint = local_voice_service.design_fingerprint(
            profile,
            reference_text=chosen_reference_text,
        )
        if (
            not force
            and _designed_profile_ready(profile)
            and str(profile.get("design_fingerprint")) == fingerprint
        ):
            return profile

        try:
            design_model = _design_model_for_profile(profile)
            clone_model = _clone_model_for_profile(profile, design_model)
            local_voice_service.begin_design_preparation(
                profile_id,
                fingerprint=fingerprint,
                reference_text=chosen_reference_text,
            )
            design_dir = PROFILE_ROOT / profile_id / "design"
            prompt_dir = PROFILE_ROOT / profile_id / "prompts"
            design_dir.mkdir(parents=True, exist_ok=True)
            prompt_dir.mkdir(parents=True, exist_ok=True)
            reference_path = design_dir / f"reference-{fingerprint[:20]}.wav"
            clone_cache_tag = hashlib.sha256(
                str(clone_model["id"]).encode("utf-8"),
            ).hexdigest()[:10]
            prompt_cache_path = (
                prompt_dir
                / f"qwen-design-{fingerprint[:20]}-{clone_cache_tag}.pt"
            )
            if force:
                reference_path.unlink(missing_ok=True)
                prompt_cache_path.unlink(missing_ok=True)

            if not reference_path.is_file() or reference_path.stat().st_size <= 44:
                design_request = {
                    "text": chosen_reference_text,
                    "language": language,
                    "family": design_model["family"],
                    "variant": "design",
                    "model_root": str(PATHS.models / str(design_model["id"])),
                    "output_path": str(reference_path),
                    "design_prompt": prompt,
                    "instruct": prompt,
                    "seed": int(profile.get("design_seed") or 42),
                    "normalize": True,
                    "max_chunk_chars": 1200,
                    "crossfade_ms": 0,
                }
                _run_worker_request(
                    engine_id=str(design_model["id"]),
                    request=design_request,
                    workload=f"PrÃ©paration Voice Design Â· {profile.get('name') or profile_id}",
                )
            if not reference_path.is_file() or reference_path.stat().st_size <= 44:
                raise RuntimeError("Voice Design n'a produit aucun fichier audio valide")

            sample = {
                "path": str(reference_path),
                "reference_text": chosen_reference_text,
                "prompt_cache_path": str(prompt_cache_path),
            }
            if warm_prompt_cache and not prompt_cache_path.is_file():
                warmup_path = design_dir / f"cache-warmup-{fingerprint[:20]}.wav"
                warmup_text = "Voix prÃªte." if language == "fr" else "Voice ready."
                clone_request = {
                    "text": warmup_text,
                    "language": language,
                    "family": clone_model["family"],
                    "variant": "clone",
                    "model_root": str(PATHS.models / str(clone_model["id"])),
                    "output_path": str(warmup_path),
                    "voice": None,
                    "design_prompt": None,
                    "sample": sample,
                    "seed": int(profile.get("design_seed") or 42),
                    "normalize": True,
                    "max_chunk_chars": 200,
                    "crossfade_ms": 0,
                }
                try:
                    _run_worker_request(
                        engine_id=str(clone_model["id"]),
                        request=clone_request,
                        workload=f"Verrouillage de la voix Â· {profile.get('name') or profile_id}",
                    )
                finally:
                    warmup_path.unlink(missing_ok=True)

            return local_voice_service.complete_design_preparation(
                profile_id,
                fingerprint=fingerprint,
                reference_text=chosen_reference_text,
                reference_path=str(reference_path),
                prompt_cache_path=str(prompt_cache_path),
                design_engine_id=str(design_model["id"]),
                clone_engine_id=str(clone_model["id"]),
            )
        except Exception as exc:
            try:
                local_voice_service.fail_design_preparation(profile_id, str(exc))
            except Exception:
                pass
            raise


def prepare_designed_profile_async(profile_id: str, *, force: bool = False) -> None:
    def runner() -> None:
        try:
            prepare_designed_profile(profile_id, force=force)
        finally:
            with _lock:
                _design_threads.pop(profile_id, None)

    with _lock:
        current = _design_threads.get(profile_id)
        if current and current.is_alive():
            return
        thread = threading.Thread(
            target=runner,
            daemon=True,
            name=f"dubroom-design-{profile_id[-8:]}",
        )
        _design_threads[profile_id] = thread
        thread.start()


def regenerate_designed_profile(
    profile_id: str,
    *,
    reference_text: str | None = None,
) -> dict[str, Any]:
    local_voice_service.reset_designed_profile(profile_id)
    return prepare_designed_profile(
        profile_id,
        force=True,
        reference_text=reference_text,
    )


def _catalog() -> list[dict[str, Any]]:
    if not CATALOG_PATH.is_file():
        return []
    value = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    models = value.get("models")
    return models if isinstance(models, list) else []


def _runtime_python(engine_id: str) -> Path:
    ready_path = PATHS.environments / engine_id / "ready.json"
    if ready_path.is_file():
        try:
            ready = json.loads(ready_path.read_text(encoding="utf-8-sig"))
            configured = Path(str(ready.get("python") or "")).resolve()
            configured.relative_to(PATHS.environments.resolve())
            if configured.is_file():
                return configured
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    model = next((item for item in _catalog() if str(item.get("id")) == engine_id), {"id": engine_id})
    runtime_id = runtime_engine_id(model)
    return PATHS.environments / runtime_id / "venv" / "Scripts" / "python.exe"


def _installed(engine_id: str) -> bool:
    model = next(
        (item for item in _catalog() if str(item.get("id")) == engine_id),
        {"id": engine_id},
    )
    runtime_id = runtime_engine_id(model)
    model_manifest = PATHS.models / engine_id / "model.json"
    validation_ready = (
        (PATHS.environments / engine_id / "ready.json").is_file()
        or (PATHS.environments / runtime_id / "ready.json").is_file()
    )
    return (
        _runtime_python(engine_id).is_file()
        and validation_ready
        and model_manifest.is_file()
    )


def models() -> dict[str, Any]:
    result = []
    for definition in _catalog():
        engine_id = str(definition["id"])
        state_path = PATHS.data / "engine-state" / engine_id / "state.json"
        state: dict[str, Any] = {}
        if state_path.is_file():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                state = {}
        installed = _installed(engine_id)
        classification = voice_library_service.classify_model(definition)
        result.append({
            **definition,
            **classification,
            "downloaded": installed,
            "downloading": state.get("status") in {"queued", "installing", "repairing"},
            "loaded": False,
            "installation_status": "ready" if installed else str(state.get("status") or "not_installed"),
            "progress": 100 if installed else int(state.get("progress") or 0),
            "message": "Engine ready" if installed else state.get("message"),
        })
    return {"models": result}


def status() -> dict[str, Any]:
    available = models()["models"]
    with _lock:
        active = sum(1 for thread in _threads.values() if thread.is_alive())
        active_designs = sum(1 for thread in _design_threads.values() if thread.is_alive())
    return {
        "ready": CATALOG_PATH.is_file() and WORKER_PATH.is_file(),
        "runtime": "dubroom-native-tts",
        "daemon_required": False,
        "data": str(DATA_ROOT),
        "models": str(PATHS.models),
        "installed_count": sum(1 for item in available if item["downloaded"]),
        "model_count": len(available),
        "active_generations": active,
        "active_voice_designs": active_designs,
    }


def profiles() -> list[dict[str, Any]]:
    voice_library_service.sync_generated_profiles()
    available_models = models()["models"]
    enriched: list[dict[str, Any]] = []
    for profile in local_voice_service.profiles():
        prompt_dir = PROFILE_ROOT / str(profile.get("id") or "") / "prompts"
        prompt_count = (
            sum(1 for _ in prompt_dir.glob("qwen-*.pt"))
            if prompt_dir.is_dir()
            else 0
        )
        designed_reference = Path(str(profile.get("design_reference_path") or ""))
        designed_prompt = Path(str(profile.get("design_prompt_cache_path") or ""))
        sample_prompt_ready = any(
            Path(str(sample.get("prompt_cache_path") or "")).is_file()
            for sample in (profile.get("samples") or [])
            if isinstance(sample, dict) and sample.get("prompt_cache_path")
        )
        classification = voice_library_service.classify_profile(
            profile,
            available_models,
        )
        enriched.append({
            **profile,
            **classification,
            "prompt_ready": prompt_count > 0 or designed_prompt.is_file() or sample_prompt_ready,
            "prompt_count": prompt_count,
            "design_reference_ready": designed_reference.is_file(),
            "design_prompt_cached": designed_prompt.is_file(),
            "design_ready": _designed_profile_ready(profile),
        })
    return enriched


def create_profile(payload: dict[str, Any]) -> dict[str, Any]:
    if str(payload.get("voice_type") or "") == "preset":
        engine = str(payload.get("preset_engine") or payload.get("default_engine") or "")
        voice_id = str(payload.get("preset_voice_id") or "")
        language = str(payload.get("language") or "en").lower().split("-", 1)[0]
        available = PRESET_VOICES.get(engine, [])
        selected = next((voice for voice in available if voice["voice_id"] == voice_id), None)
        if not selected:
            raise ValueError("Choose a valid preset voice for this engine")
        if (
            engine == "kokoro"
            and not bool(selected.get("cross_language"))
            and str(selected.get("language")) not in {language, "multi"}
        ):
            raise ValueError(f"Kokoro voice {voice_id} is not compatible with language {language.upper()}")
    profile = local_voice_service.create_profile(payload)
    if str(profile.get("voice_type")) == "designed":
        prepare_designed_profile_async(str(profile["id"]))
    return profile


def add_profile_sample(profile_id: str, file_path: str, reference_text: str) -> dict[str, Any]:
    profile = local_voice_service.get(profile_id)
    if not profile:
        raise ValueError("profile.not_found")
    transcript = str(reference_text or "").strip()
    transcription: dict[str, Any] | None = None
    if not transcript:
        # The reference recording can be in a different language from the
        # target profile. Let Whisper detect it instead of forcing the target
        # synthesis language.
        transcription = voice_reference_service.transcribe_reference(
            file_path,
            language=None,
        )
        transcript = str(transcription["text"])
    cleanup_root = PATHS.temp / "voice-reference-clean"
    cleanup_root.mkdir(parents=True, exist_ok=True)
    cleanup_path = cleanup_root / f"{uuid4().hex}.wav"
    try:
        cleaned_reference = voice_cleanup_service.prepare_reference(
            file_path,
            cleanup_path,
            reference_text=transcript,
            transcription=transcription,
            mode="balanced",
        )
        result = local_voice_service.add_sample(
            profile_id,
            file_path,
            transcript,
            transcription=transcription,
            cleaned_reference=cleaned_reference,
        )
    finally:
        cleanup_path.unlink(missing_ok=True)
    return {
        **result,
        "reference_text": transcript,
        "reference_text_source": "whisper" if transcription else "manual",
        "transcription": transcription,
        "cleanup": result["sample"].get("cleanup"),
        "clean_path": result["sample"].get("clean_path"),
    }


def preset_voices(engine: str) -> dict[str, Any]:
    value = str(engine or "").strip()
    model = next(
        (
            item
            for item in _catalog()
            if item.get("id") == value
            or item.get("engine") == value
            or item.get("family") == value
            or item.get("model_name") == value
        ),
        None,
    )
    preset_key = str((model or {}).get("engine") or value)
    if preset_key.startswith("qwen"):
        preset_key = "qwen_custom_voice"
    return {"engine": engine, "voices": PRESET_VOICES.get(preset_key, [])}


def _generation_path(generation_id: str) -> Path:
    return GENERATIONS_ROOT / f"{generation_id}.json"


def _write_generation(generation: dict[str, Any]) -> None:
    GENERATIONS_ROOT.mkdir(parents=True, exist_ok=True)
    path = _generation_path(str(generation["id"]))
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(generation, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def generation(generation_id: str) -> dict[str, Any]:
    path = _generation_path(generation_id)
    if not path.is_file():
        raise KeyError(generation_id)
    return json.loads(path.read_text(encoding="utf-8"))


def generation_status(generation_id: str) -> dict[str, Any]:
    return generation(generation_id)


def generations(profile_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    if not GENERATIONS_ROOT.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in GENERATIONS_ROOT.glob("*.json"):
        if path.name.endswith(".request.json"):
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if profile_id and str(record.get("profile_id") or "") != profile_id:
            continue
        records.append(record)
    records.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    return records[: max(1, min(int(limit), 200))]


def resolve_audio_path(storage_path: str | None) -> Path | None:
    if not storage_path:
        return None
    resolved = Path(storage_path).resolve()
    root = AUDIO_ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise RuntimeError("The generated audio path is outside DubRoom TTS storage")
    return resolved


def _profile_sample(profile: dict[str, Any]) -> dict[str, str] | None:
    if _designed_profile_ready(profile):
        reference_path = str(profile.get("design_reference_path") or "")
        reference_text = str(profile.get("design_reference_text") or "")
        prompt_cache_path = str(profile.get("design_prompt_cache_path") or "")
        if not prompt_cache_path:
            fingerprint = str(profile.get("design_fingerprint") or "")[:20]
            clone_cache_tag = hashlib.sha256(
                str(profile.get("clone_engine_id") or "qwen-base").encode("utf-8"),
            ).hexdigest()[:10]
            prompt_cache_path = str(
                PROFILE_ROOT
                / str(profile.get("id") or "unknown")
                / "prompts"
                / f"qwen-design-{fingerprint}-{clone_cache_tag}.pt"
            )
        return {
            "path": reference_path,
            "reference_text": reference_text,
            "prompt_cache_path": prompt_cache_path,
        }

    samples = profile.get("samples") or []
    if not samples:
        return None
    sample = samples[0]
    cleanup = sample.get("cleanup") if isinstance(sample.get("cleanup"), dict) else {}
    clean_path_value = str(sample.get("clean_path") or "")
    source_path_value = str(sample.get("path") or "")
    if (
        clean_path_value
        and int(cleanup.get("version") or 0) < int(voice_cleanup_service.CLEANUP_VERSION)
        and Path(source_path_value).is_file()
    ):
        # Non-destructively upgrade older 16 kHz references the first time they
        # are used. The original recording remains untouched.
        temporary = PATHS.temp / "voice-reference-clean" / f"{uuid4().hex}.wav"
        try:
            refreshed = voice_cleanup_service.prepare_reference(
                source_path_value,
                temporary,
                reference_text=str(sample.get("reference_text") or ""),
                transcription=(sample.get("transcription") if isinstance(sample.get("transcription"), dict) else None),
                mode="balanced",
            )
            attached = local_voice_service.attach_cleaned_sample(
                str(profile.get("id") or ""),
                str(sample.get("id") or ""),
                refreshed,
                transcription=(sample.get("transcription") if isinstance(sample.get("transcription"), dict) else None),
            )
            sample = attached.get("sample") or sample
        finally:
            temporary.unlink(missing_ok=True)
    clean_path = str(sample.get("clean_path") or "")
    sample_path = clean_path if clean_path and Path(clean_path).is_file() else str(sample.get("path") or "")
    selected_reference_text = (
        sample.get("clean_reference_text")
        if sample_path == clean_path
        else sample.get("reference_text")
    )
    reference_text = str(selected_reference_text or "")
    try:
        source_stamp = str(Path(sample_path).stat().st_mtime_ns)
    except OSError:
        source_stamp = "missing"
    cache_key = hashlib.sha256(
        f"{sample_path}\0{reference_text}\0{source_stamp}".encode("utf-8"),
    ).hexdigest()[:20]
    profile_id = str(profile.get("id") or "unknown")
    supplied_prompt_cache = str(sample.get("prompt_cache_path") or "")
    prompt_cache = (
        Path(supplied_prompt_cache)
        if supplied_prompt_cache
        else PROFILE_ROOT / profile_id / "prompts" / f"qwen-{cache_key}.pt"
    )
    return {
        "path": sample_path,
        "reference_text": reference_text,
        "prompt_cache_path": str(prompt_cache),
    }


def _supports_profile(model: dict[str, Any], profile: dict[str, Any]) -> bool:
    voice_type = str(profile.get("voice_type") or "preset")
    if voice_type == "designed" and _designed_profile_ready(profile):
        voice_type = "cloned"
    return voice_type in (model.get("voice_modes") or [])


def _resolve_model(payload: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    full_catalog = _catalog()
    catalog = [
        model
        for model in full_catalog
        if _tts_model_allowed(model)
    ]
    locked_design = str(profile.get("voice_type")) == "designed" and _designed_profile_ready(profile)
    requested = str(
        payload.get("engine_id")
        or payload.get("engine")
        or profile.get("default_engine")
        or profile.get("preset_engine")
        or ""
    ).strip()
    if locked_design:
        resolved_candidate = ENGINE_ALIASES.get(requested, requested)
        if (
            not resolved_candidate
            or resolved_candidate.endswith("-design")
            or requested == "qwen_voice_design"
        ):
            requested = str(profile.get("clone_engine_id") or "")
        if not requested:
            requested = str(_clone_model_for_profile(profile).get("id") or "")
    explicit_model_names = {
        str(model.get("id"))
        for model in catalog
    } | {
        str(model.get("model_name"))
        for model in catalog
    }
    strict_request = requested in explicit_model_names or requested.startswith("tts-")
    requested_model_size = str(payload.get("model_size") or "").lower()
    resolved_request = ENGINE_ALIASES.get(requested, requested)
    if requested_model_size and resolved_request.startswith("tts-qwen3-1.7b"):
        resolved_request = resolved_request.replace("1.7b", requested_model_size.lower())

    blocked_exact = next(
        (
            model
            for model in full_catalog
            if resolved_request
            and resolved_request in {
                str(model.get("id")),
                str(model.get("model_name")),
                str(model.get("engine")),
            }
            and not _tts_model_allowed(model)
        ),
        None,
    )
    if blocked_exact:
        raise RuntimeError(
            f"{blocked_exact['display_name']} is blocked by DubRoom's strict "
            f"open-source policy ({blocked_exact.get('license') or 'missing license'})."
        )

    exact = next(
        (
            model
            for model in catalog
            if resolved_request
            and resolved_request in {
                str(model.get("id")),
                str(model.get("model_name")),
                str(model.get("engine")),
            }
        ),
        None,
    )
    if exact:
        if not _supports_profile(exact, profile):
            raise ValueError(f"{exact['display_name']} does not support {profile.get('voice_type')} profiles")
        if _installed(str(exact["id"])):
            return exact
        if strict_request:
            raise RuntimeError(f"{exact['display_name']} is not installed")

    language = str(payload.get("language") or profile.get("language") or "en").lower().split("-", 1)[0]
    preferred_engine = str((exact or {}).get("engine") or requested)
    family_candidates = [
        model
        for model in catalog
        if _installed(str(model["id"]))
        and _supports_profile(model, profile)
        and language in (model.get("languages") or [])
        and (
            not preferred_engine
            or str(model.get("engine")) == preferred_engine
            or str(model.get("family")) == preferred_engine
        )
    ]
    candidates = [
        model
        for model in catalog
        if _installed(str(model["id"]))
        and _supports_profile(model, profile)
        and language in (model.get("languages") or [])
    ]
    candidates = family_candidates or candidates
    if not candidates:
        raise RuntimeError("No installed native TTS engine supports this voice profile and language")
    candidates.sort(
        key=lambda item: (
            not bool(item.get("recommended")),
            int(item.get("selection_priority") or 100),
            int(item.get("recommended_vram_gb") or 0),
        )
    )
    return candidates[0]


def _variant(model: dict[str, Any]) -> str:
    engine = str(model.get("engine") or "")
    if engine == "omnivoice":
        return "clone"
    if engine == "qwen":
        return "clone"
    if engine == "qwen_custom_voice":
        return "custom"
    if engine == "qwen_voice_design":
        return "design"
    if engine == "chatterbox_nano":
        return "nano"
    if engine == "chatterbox_turbo_onnx_fp16":
        return "turbo_onnx_fp16"
    if engine == "chatterbox_turbo_onnx_q4f16":
        return "turbo_onnx_q4f16"
    if engine == "chatterbox_turbo":
        return "turbo"
    if engine == "chatterbox":
        return "multilingual"
    if engine == "kyutai_pocket":
        return str(model.get("language_model") or "french_24l")
    return ""


def generate(payload: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(payload.get("profile_id") or "").strip()
    profile = local_voice_service.get(profile_id)
    if not profile:
        raise ValueError("profile.not_found")
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("Text is required")

    model: dict[str, Any] | None = None
    needs_design_preparation = (
        str(profile.get("voice_type")) == "designed"
        and not _designed_profile_ready(profile)
    )
    if not needs_design_preparation:
        model = _resolve_model(payload, profile)

    generation_id = uuid4().hex
    generation_record = {
        "id": generation_id,
        "profile_id": profile_id,
        "text": text,
        "language": str(payload.get("language") or profile.get("language") or "en"),
        "audio_path": None,
        "duration": None,
        "seed": payload.get("seed"),
        "instruct": payload.get("instruct"),
        "engine": model.get("engine") if model else None,
        "engine_id": model.get("id") if model else None,
        "model_name": model.get("model_name") if model else None,
        "model_size": model.get("model_size") if model else None,
        "status": "preparing_voice" if needs_design_preparation else "queued",
        "error": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _write_generation(generation_record)
    thread = threading.Thread(
        target=_execute,
        args=(generation_id, payload, profile, model),
        daemon=True,
        name=f"dubroom-tts-{generation_id[:8]}",
    )
    with _lock:
        _threads[generation_id] = thread
    thread.start()
    return generation_record



def _ffmpeg_executable() -> str:
    resolved = shutil.which("ffmpeg")
    if resolved:
        return resolved
    executable = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    managed = PATHS.data / "tools" / "ffmpeg" / "bin" / executable
    return str(managed) if managed.is_file() else "ffmpeg"


def _fallback_text_limit(model: dict[str, Any], payload: dict[str, Any]) -> int:
    family = str(model.get("family") or "").lower()
    engine = str(model.get("engine") or "").lower()
    default_limit = 320
    if family == "qwen3":
        default_limit = 420
    elif family == "chatterbox" or "chatterbox" in engine:
        default_limit = 260
    elif family == "kokoro" or "kokoro" in engine:
        default_limit = 280
    elif family in {"cosyvoice3", "cosyvoice3_gguf"}:
        default_limit = 360
    elif family in {"supertonic", "kyutai_pocket"}:
        default_limit = 300
    requested = payload.get("fallback_chunk_chars")
    try:
        if requested is not None:
            default_limit = int(requested)
    except (TypeError, ValueError):
        pass
    return max(120, min(600, default_limit))


def _split_retry_text(text: str, maximum_chars: int) -> list[str]:
    """Split only inside one TTS segment; timeline anchors remain untouched."""
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return []
    if len(cleaned) <= maximum_chars:
        return [cleaned]

    sentence_parts = [
        part.strip()
        for part in re.split(r"(?<=[.!?â€¦])\s+", cleaned)
        if part.strip()
    ]
    if not sentence_parts:
        sentence_parts = [cleaned]

    atomic: list[str] = []
    for sentence in sentence_parts:
        if len(sentence) <= maximum_chars:
            atomic.append(sentence)
            continue
        clauses = [
            part.strip()
            for part in re.split(r"(?<=[,;:])\s+|\s+[â€”â€“-]\s+", sentence)
            if part.strip()
        ]
        for clause in clauses or [sentence]:
            if len(clause) <= maximum_chars:
                atomic.append(clause)
                continue
            words = clause.split()
            current: list[str] = []
            current_length = 0
            for word in words:
                added = len(word) + (1 if current else 0)
                if current and current_length + added > maximum_chars:
                    atomic.append(" ".join(current))
                    current = [word]
                    current_length = len(word)
                else:
                    current.append(word)
                    current_length += added
            if current:
                atomic.append(" ".join(current))

    chunks: list[str] = []
    current = ""
    for part in atomic:
        candidate = f"{current} {part}".strip() if current else part
        if current and len(candidate) > maximum_chars:
            chunks.append(current)
            current = part
        else:
            current = candidate
    if current:
        chunks.append(current)

    # Avoid a tiny final fragment when it can be safely moved backward.
    if len(chunks) >= 2 and len(chunks[-1]) < 45:
        merged = f"{chunks[-2]} {chunks[-1]}".strip()
        if len(merged) <= round(maximum_chars * 1.15):
            chunks[-2:] = [merged]
    return chunks


def _join_retry_parts(
    parts: list[Path],
    output_path: Path,
    *,
    crossfade_ms: int = 50,
) -> None:
    if not parts:
        raise RuntimeError("No fallback TTS part was generated")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if len(parts) == 1:
        shutil.copy2(parts[0], output_path)
        return

    ffmpeg = _ffmpeg_executable()
    duration = max(0.0, min(0.12, float(crossfade_ms) / 1000.0))
    filters: list[str] = []
    for index in range(len(parts)):
        filters.append(
            f"[{index}:a]aresample=24000,"
            "aformat=sample_fmts=fltp:sample_rates=24000:channel_layouts=mono"
            f"[a{index}]"
        )
    current = "a0"
    for index in range(1, len(parts)):
        output = f"x{index}"
        filters.append(
            f"[{current}][a{index}]acrossfade=d={duration:.4f}:c1=tri:c2=tri[{output}]"
        )
        current = output
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for part in parts:
        command.extend(["-i", str(part)])
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{current}]",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 44:
        output_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Could not join fallback TTS chunks: {(completed.stderr or completed.stdout)[-1200:]}"
        )


def _recover_crashed_omnivoice_groups(
    prepared: list[dict[str, Any]],
    *,
    on_progress: Callable[[int, int, str], None] | None,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    """Recover native OmniVoice crashes without repeatedly loading the model.

    First retry every unfinished OmniVoice line for one engine together after a
    short cooldown. This is specifically important for Windows access-violation
    crashes during CUDA model loading. If the shared retry gets past model load
    but a particular clone/profile still kills the worker, only then isolate the
    remaining lines by speaker profile.
    """
    def is_cancelled_now() -> bool:
        return bool(is_cancelled and is_cancelled())

    def native_crash(item: dict[str, Any]) -> bool:
        error_text = str(item.get("error") or "")
        return bool(
            re.search(
                r"TTS batch worker exited|loading_model|No worker output was produced|3221225477|0xC0000005",
                error_text,
                flags=re.IGNORECASE,
            )
        )

    candidates = [
        item
        for item in prepared
        if item.get("status") != "completed"
        and isinstance(item.get("payload"), dict)
        and isinstance(item.get("model"), dict)
        and isinstance(item.get("profile"), dict)
        and str(item["model"].get("engine") or "").lower() == "omnivoice"
        and native_crash(item)
    ]
    if not candidates:
        return

    total = len(prepared)
    by_engine: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        by_engine.setdefault(str(item["model"].get("id") or ""), []).append(item)

    # A native Windows/CUDA crash may leave the driver/runtime briefly settling.
    # Immediate retries reproduced the same 0xC0000005. Give it a small cooldown
    # and retry the model once for all unfinished profiles together.
    for engine_id, engine_items in by_engine.items():
        if is_cancelled_now():
            raise TTSBatchCancelled("Voice generation cancelled")
        if on_progress:
            done = sum(item.get("status") == "completed" for item in prepared)
            on_progress(
                done,
                total,
                f"OmniVoice native worker stopped during startup; waiting 4 seconds before one shared model restart ({len(engine_items)} remaining line(s))",
            )
        time.sleep(4.0)
        retry_payloads = [dict(item["payload"]) for item in engine_items]
        try:
            retry_results = generate_batch(
                retry_payloads,
                None,
                is_cancelled=is_cancelled,
                _fallback_depth=1,
            )
        except TTSBatchCancelled:
            raise
        except Exception as exc:
            retry_results = [
                {
                    "id": str(item.get("id") or ""),
                    "status": "failed",
                    "error": f"OmniVoice shared restart failed: {str(exc)[-2400:]}",
                }
                for item in engine_items
            ]

        by_id = {str(result.get("id") or ""): result for result in retry_results}
        for item in engine_items:
            result = by_id.get(str(item.get("id") or ""))
            if not result:
                continue
            if result.get("status") == "completed":
                item.update(
                    {
                        "status": "completed",
                        "error": None,
                        "audio_path": result.get("audio_path"),
                        "duration": result.get("duration"),
                        "sample_rate": result.get("sample_rate"),
                        "device": result.get("device"),
                        "engine": result.get("engine"),
                        "engine_id": result.get("engine_id"),
                        "model_name": result.get("model_name"),
                        "model_size": result.get("model_size"),
                        "batch_restart_count": int(item.get("batch_restart_count") or 0) + 1,
                    }
                )
            else:
                previous = str(item.get("error") or "")
                current = str(result.get("error") or "shared OmniVoice restart failed")
                item["error"] = f"{previous[-1400:]} | shared retry: {current[-2200:]}".strip(" |")

    remaining = [
        item
        for item in candidates
        if item.get("status") != "completed" and native_crash(item)
    ]
    if not remaining:
        return

    # Only after the one-model retry fails do we isolate by profile. This keeps
    # one pathological clone from sacrificing the rest while avoiding seven
    # unnecessary model loads in the healthy case.
    by_profile: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in remaining:
        model = item["model"]
        profile = item["profile"]
        key = (str(model.get("id") or ""), str(profile.get("id") or item.get("id") or ""))
        by_profile.setdefault(key, []).append(item)

    for (_, profile_id), group in by_profile.items():
        if is_cancelled_now():
            raise TTSBatchCancelled("Voice generation cancelled")
        if on_progress:
            done = sum(item.get("status") == "completed" for item in prepared)
            on_progress(
                done,
                total,
                f"Isolating remaining OmniVoice speaker {profile_id} after native crash ({len(group)} line(s))",
            )
        time.sleep(2.0)
        retry_payloads = [dict(item["payload"]) for item in group]
        try:
            retry_results = generate_batch(
                retry_payloads,
                None,
                is_cancelled=is_cancelled,
                _fallback_depth=2,
            )
        except TTSBatchCancelled:
            raise
        except Exception as exc:
            retry_results = [
                {
                    "id": str(item.get("id") or ""),
                    "status": "failed",
                    "error": f"OmniVoice isolated restart failed: {str(exc)[-2400:]}",
                }
                for item in group
            ]

        by_id = {str(result.get("id") or ""): result for result in retry_results}
        for item in group:
            result = by_id.get(str(item.get("id") or ""))
            if not result:
                continue
            if result.get("status") == "completed":
                item.update(
                    {
                        "status": "completed",
                        "error": None,
                        "audio_path": result.get("audio_path"),
                        "duration": result.get("duration"),
                        "sample_rate": result.get("sample_rate"),
                        "device": result.get("device"),
                        "engine": result.get("engine"),
                        "engine_id": result.get("engine_id"),
                        "model_name": result.get("model_name"),
                        "model_size": result.get("model_size"),
                        "batch_restart_count": int(item.get("batch_restart_count") or 0) + 1,
                        "isolated_profile_restart": True,
                    }
                )
            else:
                previous = str(item.get("error") or "")
                current = str(result.get("error") or "isolated OmniVoice restart failed")
                item["error"] = f"{previous[-1200:]} | isolated retry: {current[-2200:]}".strip(" |")

def _recover_failed_batch_items(
    prepared: list[dict[str, Any]],
    *,
    on_progress: Callable[[int, int, str], None] | None,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    failed = [
        item
        for item in prepared
        if item.get("status") != "completed"
        and isinstance(item.get("payload"), dict)
        and isinstance(item.get("model"), dict)
    ]
    if not failed:
        return

    total = len(prepared)
    recovered = 0
    for position, item in enumerate(failed, start=1):
        if is_cancelled and is_cancelled():
            raise TTSBatchCancelled("Voice generation cancelled")
        payload = dict(item["payload"])
        model = item["model"]
        text = str(payload.get("text") or "").strip()
        if not text:
            continue
        limit = _fallback_text_limit(model, payload)
        error_text = str(item.get("error") or "")
        looks_length_related = bool(
            len(text) > limit
            or re.search(
                r"length|long|token|sequence|shape|dimension|cuda.*alloc|out of memory",
                error_text,
                flags=re.IGNORECASE,
            )
        )
        fatal_runtime_error = bool(
            re.search(
                r"not installed|profile\.not_found|license|unsupported|no installed|"
                r"modulenotfound|importerror|dll load|runtime is incomplete|worker path",
                error_text,
                flags=re.IGNORECASE,
            )
        )
        short_retry_allowed = len(failed) <= 8 and not fatal_runtime_error
        if not looks_length_related and not short_retry_allowed:
            continue
        # Retry a normal-length line once as an isolated request. Long or
        # suspicious lines are split immediately to avoid repeating the crash.
        chunks = _split_retry_text(text, limit) if looks_length_related else [text]
        if not chunks:
            continue
        original_output = Path(
            str(payload.get("output_path") or AUDIO_ROOT / f"fallback-{item['id']}.wav")
        ).resolve()
        original_output.unlink(missing_ok=True)
        part_paths: list[Path] = []
        retry_payloads: list[dict[str, Any]] = []
        for chunk_index, chunk in enumerate(chunks, start=1):
            part_path = (
                original_output
                if len(chunks) == 1
                else original_output.with_name(
                    f".{original_output.stem}.retry-{chunk_index:03d}.wav"
                )
            )
            part_paths.append(part_path)
            chunk_payload = {
                **payload,
                "id": f"{item['id']}::retry::{chunk_index:03d}",
                "engine_id": str(model.get("id") or ""),
                "text": chunk,
                "output_path": str(part_path),
                "max_chunk_chars": min(limit, int(payload.get("max_chunk_chars") or limit)),
            }
            seed = payload.get("seed")
            if isinstance(seed, int) and len(chunks) > 1:
                chunk_payload["seed"] = seed + chunk_index - 1
            retry_payloads.append(chunk_payload)
        if on_progress:
            on_progress(
                max(0, total - len(failed) + recovered),
                total,
                (
                    f"Retrying failed voice line {position} of {len(failed)} "
                    f"in {len(chunks)} safe chunk(s)"
                ),
            )
        try:
            retry_results = generate_batch(
                retry_payloads,
                None,
                is_cancelled=is_cancelled,
                _fallback_depth=1,
            )
            failed_retry = next(
                (result for result in retry_results if result.get("status") != "completed"),
                None,
            )
            if failed_retry:
                raise RuntimeError(str(failed_retry.get("error") or "Fallback TTS failed"))
            if len(chunks) > 1:
                _join_retry_parts(
                    part_paths,
                    original_output,
                    crossfade_ms=int(payload.get("crossfade_ms") or 50),
                )
            if not original_output.is_file() or original_output.stat().st_size <= 44:
                raise RuntimeError("Fallback TTS did not create a readable WAV file")
            first = retry_results[0] if retry_results else {}
            item.update(
                {
                    "status": "completed",
                    "error": None,
                    "audio_path": str(original_output),
                    "duration": None,
                    "sample_rate": first.get("sample_rate") or model.get("sample_rate"),
                    "device": first.get("device"),
                    "engine": model.get("engine"),
                    "engine_id": model.get("id"),
                    "model_name": model.get("model_name"),
                    "model_size": model.get("model_size"),
                    "fallback_chunk_count": len(chunks),
                    "retry_count": 1,
                    "recovered_from_error": error_text[-1000:],
                }
            )
            recovered += 1
        except TTSBatchCancelled:
            raise
        except Exception as exc:
            item["error"] = (
                f"{error_text[-1800:]} | isolated fallback failed: {str(exc)[-1800:]}"
            ).strip(" |")
        finally:
            if len(chunks) > 1:
                for part_path in part_paths:
                    part_path.unlink(missing_ok=True)
    if on_progress and recovered:
        completed = sum(item.get("status") == "completed" for item in prepared)
        on_progress(completed, total, f"Recovered {recovered} failed TTS line(s)")


def generate_batch(
    payloads: list[dict[str, Any]],
    on_progress: Callable[[int, int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
    _fallback_depth: int = 0,
) -> list[dict[str, Any]]:
    """Generate many project lines while loading each selected model only once."""
    def cancellation_requested() -> bool:
        return bool(is_cancelled and is_cancelled())

    prepared: list[dict[str, Any]] = []
    for index, payload in enumerate(payloads):
        if cancellation_requested():
            raise TTSBatchCancelled("Voice generation cancelled")
        profile_id = str(payload.get("profile_id") or "").strip()
        profile = local_voice_service.get(profile_id)
        if not profile:
            prepared.append(
                {
                    "id": str(payload.get("id") or index),
                    "status": "failed",
                    "error": "profile.not_found",
                }
            )
            continue
        try:
            if (
                str(profile.get("voice_type")) == "designed"
                and not _designed_profile_ready(profile)
            ):
                prepare_designed_profile(profile_id)
                profile = local_voice_service.get(profile_id) or profile
            model = _resolve_model(payload, profile)
        except (RuntimeError, ValueError) as exc:
            prepared.append(
                {
                    "id": str(payload.get("id") or index),
                    "status": "failed",
                    "error": str(exc),
                }
            )
            continue
        prepared.append(
            {
                "id": str(payload.get("id") or index),
                "status": "pending",
                "payload": payload,
                "profile": profile,
                "model": model,
            }
        )

    # Load each selected model only once for the first pass. OmniVoice supports
    # multiple clone prompts inside one batch because run-tts.py caches prompts
    # by reference. Re-loading the same CUDA model once per speaker proved much
    # less stable on Windows (native 0xC0000005 during model loading). If a worker
    # later crashes after the model has loaded, recovery below narrows only the
    # unfinished items to the affected speaker profiles.
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in prepared:
        if item["status"] != "pending":
            continue
        engine_id = str(item["model"]["id"])
        groups.setdefault((engine_id, "*"), []).append(item)

    total = len(prepared)
    completed = sum(item["status"] == "failed" for item in prepared)
    if on_progress and completed:
        on_progress(completed, total, "Voice profiles validated")

    for (engine_id, profile_batch_key), group in groups.items():
        if cancellation_requested():
            raise TTSBatchCancelled("Voice generation cancelled")
        model = group[0]["model"]
        python_executable = _runtime_python(engine_id)
        batch_id = uuid4().hex
        request_path = GENERATIONS_ROOT / f"batch-{batch_id}.request.json"
        dummy_output = AUDIO_ROOT / f"batch-{batch_id}.wav"
        items: list[dict[str, Any]] = []
        for item in group:
            payload = item["payload"]
            profile = item["profile"]
            output_path = Path(
                str(payload.get("output_path") or AUDIO_ROOT / f"{batch_id}-{item['id']}.wav")
            ).resolve()
            items.append(
                {
                    **payload,
                    "id": item["id"],
                    "text": str(payload.get("text") or ""),
                    "language": str(
                        payload.get("language") or profile.get("language") or "en"
                    ),
                    "output_path": str(output_path),
                    "voice": profile.get("preset_voice_id"),
                    "design_prompt": (
                        None
                        if _designed_profile_ready(profile)
                        else profile.get("design_prompt")
                    ),
                    "sample": _profile_sample(profile),
                    "seed": (
                        payload.get("seed")
                        if payload.get("seed") is not None
                        else (
                            int(profile.get("design_seed") or 42)
                            if str(profile.get("voice_type")) == "designed"
                            else None
                        )
                    ),
                }
            )
        request = {
            "family": model["family"],
            "variant": _variant(model),
            "model_root": str(PATHS.models / engine_id),
            "output_path": str(dummy_output),
            "items": items,
        }
        GENERATIONS_ROOT.mkdir(parents=True, exist_ok=True)
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.update(
            {
                "HF_HOME": str(PATHS.cache / "huggingface"),
                "TORCH_HOME": str(PATHS.cache / "torch"),
                "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
            }
        )
        family = str(model.get("family") or "").lower()
        light_cpu = family in {"supertonic", "kyutai_pocket"}
        device = "cpu" if light_cpu else ("cuda" if shutil.which("nvidia-smi") else "cpu")
        environment["DUBROOM_DEVICE"] = device
        if device == "cuda" and os.name != "nt":
            environment.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        if device == "cuda" and os.name == "nt" and engine_id == "tts-omnivoice-hq":
            environment["HF_DEACTIVATE_ASYNC_LOAD"] = "1"
            environment["HF_ENABLE_PARALLEL_LOADING"] = "false"
        if family == "qwen3" and device == "cuda":
            environment.setdefault("DUBROOM_QWEN_FAST", "1")
            environment.setdefault(
                "DUBROOM_QWEN_FAST_MAX_SEQ",
                "512",
            )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        result_by_id: dict[str, dict[str, Any]] = {}
        log_lines: list[str] = []
        worker_phase = "starting"
        batch_log_path = GENERATIONS_ROOT / f"batch-{batch_id}.log"
        cancellation_stop = threading.Event()
        worker_cancelled = threading.Event()
        cancellation_thread: threading.Thread | None = None
        try:
            with resource_scheduler.model_slot(
                f"{model.get('display_name') or model.get('model_name') or family} TTS batch",
                device=device,
                light=light_cpu,
            ):
                process = subprocess.Popen(
                    [str(python_executable), str(WORKER_PATH), "--request", str(request_path)],
                    cwd=PATHS.workspace,
                    env=environment,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=flags,
                )

                def watch_cancellation() -> None:
                    while not cancellation_stop.wait(0.1):
                        if cancellation_requested():
                            worker_cancelled.set()
                            _stop_worker(process)
                            return

                cancellation_thread = threading.Thread(
                    target=watch_cancellation,
                    daemon=True,
                    name=f"dubroom-tts-cancel-{batch_id[:8]}",
                )
                cancellation_thread.start()
                assert process.stdout is not None
                for line in process.stdout:
                    clean = line.strip()
                    if clean:
                        log_lines.append(clean)
                        log_lines = log_lines[-120:]
                    try:
                        event = json.loads(clean)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    if event.get("event") == "loading_model":
                        worker_phase = "loading_model"
                        if on_progress:
                            on_progress(
                                completed,
                                total,
                                f"Loading {model.get('display_name') or engine_id} once for {len(group)} lines",
                            )
                    if event.get("event") == "model_loaded":
                        worker_phase = "model_loaded"
                        if on_progress:
                            on_progress(
                                completed,
                                total,
                                f"{model.get('display_name') or engine_id} loaded; generating {len(group)} line(s)",
                            )
                    if event.get("event") == "loading_fast_qwen" and on_progress:
                        on_progress(
                            completed,
                            total,
                            "Preparing Qwen CUDA Graphs once for accelerated generation",
                        )
                    if event.get("event") == "fast_qwen_fallback" and on_progress:
                        on_progress(
                            completed,
                            total,
                            "CUDA Graphs unavailable on this workload; continuing with Qwen standard",
                        )
                    if event.get("event") == "chatterbox_batch_config" and on_progress:
                        mode = str(event.get("runtime") or "chatterbox").title()
                        on_progress(
                            completed,
                            total,
                            f"Chatterbox {mode}: model loaded once, voice conditioning cached",
                        )
                    if event.get("event") == "chatterbox_voice_conditioned" and on_progress:
                        on_progress(
                            completed,
                            total,
                            f"Chatterbox voice prepared and cached ({int(event.get('cached_profiles') or 1)} profile(s))",
                        )
                    if event.get("event") == "cosyvoice3_batch_config" and on_progress:
                        device = str(event.get("device") or "cpu").upper()
                        on_progress(
                            completed,
                            total,
                            f"CosyVoice 3 {device}: model loaded once, cloned voice cached",
                        )
                    if event.get("event") == "micro_batch_config" and on_progress:
                        runtime = str(event.get("runtime") or "upstream")
                        runtime_label = (
                            "CUDA Graphs"
                            if runtime == "cuda_graphs"
                            else "Qwen standard"
                        )
                        on_progress(
                            completed,
                            total,
                            f"{runtime_label}: "
                            f"{int(event.get('batch_size') or 1)} lines per batch, "
                            f"{int(event.get('voice_groups') or 1)} locked voice profile(s)",
                        )
                    if event.get("event") != "item_completed":
                        continue
                    worker_phase = "generating_items"
                    item_id = str(event.get("id") or "")
                    result_by_id[item_id] = event
                    completed += 1
                    if on_progress:
                        on_progress(
                            completed,
                            total,
                            f"Generated voice line {completed} of {total}",
                        )
                return_code = process.wait()
            if worker_cancelled.is_set() or cancellation_requested():
                raise TTSBatchCancelled("Voice generation cancelled")
            if return_code != 0:
                detail = "\n".join(log_lines[-60:]).strip()
                raise RuntimeError(
                    f"TTS batch worker exited with code {return_code} during {worker_phase}. "
                    f"Engine={engine_id}, profile_batch={profile_batch_key}. "
                    f"Log={batch_log_path}.\n{detail or 'No worker output was produced.'}"
                )
        except TTSBatchCancelled:
            raise
        except Exception as exc:
            detail = str(exc)[-4000:]
            for item in group:
                result_by_id.setdefault(
                    item["id"],
                    {"id": item["id"], "status": "failed", "error": detail},
                )
        finally:
            cancellation_stop.set()
            if cancellation_thread is not None:
                cancellation_thread.join(timeout=1)
            # Keep a small persistent worker log. When a CUDA/native dependency
            # terminates the process without a Python traceback, the exit code
            # and last emitted phase are otherwise the only useful evidence.
            try:
                batch_log_path.write_text(
                    "\n".join(log_lines[-240:]) + ("\n" if log_lines else ""),
                    encoding="utf-8",
                )
            except OSError:
                pass
            request_path.unlink(missing_ok=True)
            dummy_output.unlink(missing_ok=True)

        for item in group:
            result = result_by_id.get(
                item["id"],
                {
                    "id": item["id"],
                    "status": "failed",
                    "error": "The TTS batch returned no result for this line",
                },
            )
            item.update(
                {
                    "status": str(result.get("status") or "failed"),
                    "error": result.get("error"),
                    "audio_path": result.get("output_path"),
                    "duration": result.get("duration"),
                    "sample_rate": result.get("sample_rate") or model.get("sample_rate"),
                    "device": device,
                    "engine": model.get("engine"),
                    "engine_id": model.get("id"),
                    "model_name": model.get("model_name"),
                    "model_size": model.get("model_size"),
                }
            )

    # A native OmniVoice worker can disappear without a Python traceback
    # (Windows/CUDA/DLL level). Retry the affected speaker batch exactly once
    # before falling back to line-level recovery.
    if _fallback_depth == 0:
        _recover_crashed_omnivoice_groups(
            prepared,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )

    # A long or unusually shaped sentence can make one worker item fail even
    # when the model itself is healthy. Retry it outside the original batch and
    # split only inside that segment when necessary. The final result remains
    # one WAV and one timeline anchor.
    if _fallback_depth == 0:
        _recover_failed_batch_items(
            prepared,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )

    return [
        {
            key: value
            for key, value in item.items()
            if key not in {"payload", "profile", "model"}
        }
        for item in prepared
    ]


def _execute(
    generation_id: str,
    payload: dict[str, Any],
    profile: dict[str, Any],
    model: dict[str, Any] | None,
) -> None:
    record = generation(generation_id)
    output_path = AUDIO_ROOT / f"{generation_id}.wav"
    request_path = GENERATIONS_ROOT / f"{generation_id}.request.json"
    try:
        if (
            str(profile.get("voice_type")) == "designed"
            and not _designed_profile_ready(profile)
        ):
            record.update({"status": "preparing_voice", "updated_at": _now()})
            _write_generation(record)
            prepare_designed_profile(str(profile["id"]))
            profile = local_voice_service.get(str(profile["id"])) or profile
            model = None
        if model is None:
            model = _resolve_model(payload, profile)
        record.update(
            {
                "status": "loading_model",
                "engine": model.get("engine"),
                "engine_id": model.get("id"),
                "model_name": model.get("model_name"),
                "model_size": model.get("model_size"),
                "updated_at": _now(),
            }
        )
        _write_generation(record)
        engine_id = str(model["id"])
        python_executable = _runtime_python(engine_id)
        request = {
            **payload,
            "text": record["text"],
            "language": record["language"],
            "family": model["family"],
            "variant": _variant(model),
            "model_root": str(PATHS.models / engine_id),
            "output_path": str(output_path),
            "voice": profile.get("preset_voice_id"),
            "design_prompt": (
                None
                if _designed_profile_ready(profile)
                else profile.get("design_prompt")
            ),
            "sample": _profile_sample(profile),
            "seed": (
                payload.get("seed")
                if payload.get("seed") is not None
                else (
                    int(profile.get("design_seed") or 42)
                    if str(profile.get("voice_type")) == "designed"
                    else None
                )
            ),
        }
        request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        record.update({"status": "generating", "updated_at": _now()})
        _write_generation(record)
        environment = os.environ.copy()
        environment.update({
            "HF_HOME": str(PATHS.cache / "huggingface"),
            "TORCH_HOME": str(PATHS.cache / "torch"),
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
        })
        family = str(model.get("family") or "").lower()
        light_cpu = family in {"supertonic", "kyutai_pocket"}
        device = "cpu" if light_cpu else ("cuda" if shutil.which("nvidia-smi") else "cpu")
        environment["DUBROOM_DEVICE"] = device
        if device == "cuda" and os.name != "nt":
            environment.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
        if device == "cuda" and os.name == "nt" and engine_id == "tts-omnivoice-hq":
            environment["HF_DEACTIVATE_ASYNC_LOAD"] = "1"
            environment["HF_ENABLE_PARALLEL_LOADING"] = "false"
        if family == "qwen3" and device == "cuda":
            environment.setdefault("DUBROOM_QWEN_FAST", "1")
            environment.setdefault(
                "DUBROOM_QWEN_FAST_MAX_SEQ",
                "512",
            )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with resource_scheduler.model_slot(
            f"{model.get('display_name') or model.get('model_name') or family} TTS",
            device=device,
            light=light_cpu,
        ):
            result = subprocess.run(
                [str(python_executable), str(WORKER_PATH), "--request", str(request_path)],
                cwd=PATHS.workspace,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1200,
                creationflags=flags,
                check=False,
            )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Unknown TTS worker failure").strip()
            raise RuntimeError(detail[-4000:])
        worker_result: dict[str, Any] = {}
        for line in reversed(result.stdout.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                worker_result = value
                break
        if not output_path.is_file():
            raise RuntimeError("The native TTS worker completed without an audio file")
        record.update({
            "status": "completed",
            "audio_path": str(output_path),
            "duration": worker_result.get("duration"),
            "sample_rate": worker_result.get("sample_rate") or model.get("sample_rate"),
            "device": device,
            "updated_at": _now(),
        })
        _write_generation(record)
        local_voice_service.record_generation(str(profile["id"]))
    except Exception as exc:
        record.update({"status": "failed", "error": str(exc), "updated_at": _now()})
        _write_generation(record)
    finally:
        request_path.unlink(missing_ok=True)
        with _lock:
            _threads.pop(generation_id, None)
