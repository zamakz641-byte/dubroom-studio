from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import PATHS
from . import local_voice_service, resource_scheduler


ENGINE_ID = "tts-omnivoice-hq"
LIBRARY_ROOT = PATHS.data / "voice-library" / "omnivoice"
CONFIG_PATH = PATHS.installers / "omnivoice-voice-library.json"
BUILDER_PATH = PATHS.installers / "create-omnivoice-voice-library.py"
STATE_PATH = LIBRARY_ROOT / "build-state.json"
CATALOG_PATH = LIBRARY_ROOT / "voice_catalog.json"
LAST_BUILD_PATH = LIBRARY_ROOT / "last_build.json"
LOG_PATH = LIBRARY_ROOT / "build.log"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_PROCESS: subprocess.Popen[str] | None = None
_CANCEL = threading.Event()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _config() -> dict[str, Any]:
    value = _read_json(CONFIG_PATH, {})
    return value if isinstance(value, dict) else {}


def _runtime() -> dict[str, Any]:
    ready_path = PATHS.environments / ENGINE_ID / "ready.json"
    ready = _read_json(ready_path, {})
    python_path = Path(
        str(
            ready.get("python")
            or PATHS.environments
            / ENGINE_ID
            / "venv"
            / "Scripts"
            / "python.exe"
        )
    )
    model_manifest = _read_json(PATHS.models / ENGINE_ID / "model.json", {})
    model_value = str(model_manifest.get("model_path") or "").strip()
    model_path = Path(model_value) if model_value else PATHS.models / ENGINE_ID / ".missing"
    return {
        "ready": bool(
            python_path.is_file()
            and BUILDER_PATH.is_file()
            and CONFIG_PATH.is_file()
            and model_path.is_dir()
        ),
        "python": str(python_path),
        "model_path": str(model_path),
        "device": "cuda" if ready.get("cuda") else "cpu",
        "torch": ready.get("torch"),
        "cuda": ready.get("cuda_version"),
        "local_only": bool(ready.get("local_only", True)),
    }


def _saved_state() -> dict[str, Any]:
    value = _read_json(STATE_PATH, {})
    if not isinstance(value, dict):
        value = {}
    return {
        "status": str(value.get("status") or "idle"),
        "progress": int(value.get("progress") or 0),
        "message": str(value.get("message") or "Voice Library ready to build"),
        "error": value.get("error"),
        "selected": list(value.get("selected") or []),
        "generated": list(value.get("generated") or []),
        "failed": list(value.get("failed") or []),
        "full_tests": bool(value.get("full_tests", False)),
        "started_at": value.get("started_at"),
        "updated_at": value.get("updated_at"),
        "completed_at": value.get("completed_at"),
        "log_path": str(LOG_PATH),
    }


def _update_state(**changes: Any) -> dict[str, Any]:
    with _LOCK:
        state = _saved_state()
        state.update(changes)
        state["updated_at"] = _now()
        _write_json(STATE_PATH, state)
        return state


def _generated_records() -> dict[str, dict[str, Any]]:
    catalog = _read_json(CATALOG_PATH, {})
    voices = catalog.get("voices") if isinstance(catalog, dict) else {}
    return voices if isinstance(voices, dict) else {}


def _template_records() -> list[dict[str, Any]]:
    config = _config()
    profiles = config.get("profiles")
    return [dict(item) for item in profiles] if isinstance(profiles, list) else []


def _primary_casting_role(roles: list[str]) -> str:
    lowered = {str(role).strip().lower() for role in roles}
    if "narrator" in lowered:
        return "narrator"
    if lowered.intersection({"protagonist", "hero", "main character", "mc"}):
        return "mc"
    if lowered.intersection({"heroine", "female lead", "waifu"}):
        return "female_lead"
    if lowered.intersection({"antagonist", "villain", "rival"}):
        return "antagonist"
    if lowered.intersection({"child", "kid"}):
        return "child"
    if lowered.intersection({"secondary", "supporting", "mentor", "parent"}):
        return "supporting"
    return "other"


def _age_group(age: Any) -> str:
    value = str(age or "").strip().lower().replace("-", " ")
    if "child" in value:
        return "child"
    if "teen" in value:
        return "teen"
    if "young" in value:
        return "young_adult"
    if any(token in value for token in ("senior", "elder", "old")):
        return "elderly"
    return "adult"


def sync_generated_profiles() -> list[dict[str, Any]]:
    """Expose completed OmniVoice prompts through DubRoom's native profiles."""
    synced: list[dict[str, Any]] = []
    # CASTING_R4_FINAL_TEMPLATE_METADATA
    template_by_id = {
        str(item.get("id") or "").strip().upper(): item
        for item in _template_records()
        if str(item.get("id") or "").strip()
    }
    for voice_id, catalog_voice in _generated_records().items():
        template_voice = template_by_id.get(str(voice_id).strip().upper()) or {}
        voice_dir = LIBRARY_ROOT / "voices" / str(voice_id)
        profile_payload = _read_json(voice_dir / "profile.json", {})
        if not isinstance(profile_payload, dict):
            profile_payload = {}
        reference_path = voice_dir / "reference.wav"
        prompt_path = voice_dir / "prompt.pt"
        if not reference_path.is_file() or not prompt_path.is_file():
            continue
        traits = list(profile_payload.get("traits") or catalog_voice.get("traits") or template_voice.get("traits") or [])
        roles = list(profile_payload.get("roles") or catalog_voice.get("roles") or template_voice.get("roles") or [])
        voice_archetype = str(
            profile_payload.get("voice_archetype")
            or catalog_voice.get("voice_archetype")
            or template_voice.get("voice_archetype")
            or ""
        ).strip().upper()
        casting_tags = [
            str(value).strip().lower()
            for value in (
                profile_payload.get("casting_tags")
                or catalog_voice.get("casting_tags")
                or template_voice.get("casting_tags")
                or []
            )
            if str(value).strip()
        ]
        tests = profile_payload.get("tests") if isinstance(profile_payload.get("tests"), dict) else {}
        external_id = f"omnivoice-{voice_id}"
        synced.append(
            local_voice_service.upsert_external_profile(
                external_id,
                {
                    "name": str(catalog_voice.get("name") or voice_id),
                    "description": ", ".join([*traits, *roles]),
                    "language": "fr",
                    "voice_type": "cloned",
                    "voice_source": "designed-library",
                    "default_engine": ENGINE_ID,
                    "preset_engine": "omnivoice",
                    "provider_profile_id": str(voice_id),
                    "speaker_mode": "single-speaker",
                    "multi_speaker_compatible": True,
                    "gender": catalog_voice.get("gender") or template_voice.get("gender"),
                    "age": catalog_voice.get("age") or template_voice.get("age"),
                    "age_group": _age_group(catalog_voice.get("age") or template_voice.get("age")),
                    "pitch": catalog_voice.get("pitch") or template_voice.get("pitch"),
                    "traits": traits,
                    "roles": roles,
                    "primary_role": _primary_casting_role(roles),
                    "voice_archetype": voice_archetype or None,
                    "casting_tags": casting_tags,
                    "usage_scope": "both",
                    "personality": ", ".join(traits),
                    "locked": bool(catalog_voice.get("locked", False)),
                    "enabled": bool(catalog_voice.get("enabled", True)),
                    "official_expressive_controls": list(
                        profile_payload.get("official_expressive_controls") or []
                    ),
                    "library_tests": tests,
                    "samples": [
                        {
                            "id": f"omnivoice-{voice_id}-reference",
                            "path": str(reference_path.resolve()),
                            "reference_text": str(profile_payload.get("reference_text") or ""),
                            "prompt_cache_path": str(prompt_path.resolve()),
                            "source": "omnivoice-designed-library",
                        }
                    ],
                },
                origin="dubroom-omnivoice-library",
            )
        )
    return synced


def classify_model(model: dict[str, Any]) -> dict[str, Any]:
    capabilities = [str(item) for item in model.get("capabilities") or []]
    modes = [str(item) for item in model.get("voice_modes") or []]
    native_multi = any(item in {"multi-speaker", "multi-speaker-native"} for item in capabilities)
    expressive = any(
        token in item
        for item in capabilities
        for token in ("emotion", "expressive", "paralinguistic", "instruct")
    )
    return {
        "speaker_mode": "multi-speaker-native" if native_multi else "single-speaker",
        "multi_speaker_compatible": True,
        "voice_sources": modes,
        "supports_preset": "preset" in modes,
        "supports_cloning": "cloned" in modes,
        "supports_design": "designed" in modes,
        "supports_expression": expressive,
        "supports_streaming": "streaming" in capabilities,
        "local_only": "local-only" in capabilities or bool(model.get("downloaded")),
    }


def classify_profile(
    profile: dict[str, Any],
    models: list[dict[str, Any]],
) -> dict[str, Any]:
    requested = str(profile.get("default_engine") or profile.get("preset_engine") or "")
    model = next(
        (
            item
            for item in models
            if requested
            in {
                str(item.get("id") or ""),
                str(item.get("engine") or ""),
                str(item.get("family") or ""),
            }
        ),
        None,
    )
    classification = classify_model(model or {})
    return {
        **classification,
        "speaker_mode": str(profile.get("speaker_mode") or classification["speaker_mode"]),
        "multi_speaker_compatible": bool(
            profile.get("multi_speaker_compatible", classification["multi_speaker_compatible"])
        ),
        "engine_family": (model or {}).get("family"),
        "engine_display_name": (model or {}).get("display_name"),
        "voice_source": str(profile.get("voice_source") or profile.get("voice_type") or "preset"),
    }


def catalog(models: list[dict[str, Any]]) -> dict[str, Any]:
    sync_generated_profiles()
    generated = _generated_records()
    last_build = _read_json(LAST_BUILD_PATH, {})
    failed_ids = {
        str(item.get("id"))
        for item in (last_build.get("failed") or [])
        if isinstance(item, dict)
    }
    templates: list[dict[str, Any]] = []
    for profile in _template_records():
        voice_id = str(profile.get("id") or "")
        voice_dir = LIBRARY_ROOT / "voices" / voice_id
        ready = (voice_dir / "reference.wav").is_file() and (voice_dir / "prompt.pt").is_file()
        templates.append(
            {
                **profile,
                "status": "ready" if ready else "failed" if voice_id in failed_ids else "not_generated",
                "profile_id": f"omnivoice-{voice_id}" if ready else None,
                "speaker_mode": "single-speaker",
                "multi_speaker_compatible": True,
            }
        )
    return {
        "runtime": _runtime(),
        "build": _saved_state(),
        "summary": {
            "configured": len(templates),
            "generated": sum(1 for item in templates if item["status"] == "ready"),
            "single_speaker": len(templates),
            "multi_speaker_assignable": len(templates),
        },
        "templates": templates,
        "engines": [
            {
                "id": model.get("id"),
                "display_name": model.get("display_name"),
                "family": model.get("family"),
                "downloaded": bool(model.get("downloaded")),
                "languages": list(model.get("languages") or []),
                **classify_model(model),
            }
            for model in models
        ],
        "catalog_path": str(CATALOG_PATH),
    }


def _build_command(options: dict[str, Any]) -> tuple[list[str], list[str]]:
    runtime = _runtime()
    if not runtime["ready"]:
        raise RuntimeError(
            "The local OmniVoice runtime/model is incomplete. No download was attempted."
        )
    configured = {str(item.get("id") or "").upper() for item in _template_records()}
    requested = [str(item).strip().upper() for item in options.get("voices") or [] if str(item).strip()]
    selected = list(dict.fromkeys(requested or sorted(configured)))
    unknown = sorted(set(selected) - configured)
    if unknown:
        raise ValueError(f"Unknown OmniVoice profiles: {', '.join(unknown)}")
    command = [
        str(runtime["python"]),
        str(BUILDER_PATH),
        "--config",
        str(CONFIG_PATH),
        "--library-root",
        str(LIBRARY_ROOT),
        "--model-path",
        str(runtime["model_path"]),
        "--device",
        "auto",
        "--voices",
        ",".join(selected),
    ]
    if options.get("full_tests"):
        command.append("--full-tests")
    if options.get("regenerate"):
        command.append("--regenerate")
    if options.get("tests_only"):
        command.append("--tests-only")
    return command, selected


def _run_build(command: list[str], selected: list[str], options: dict[str, Any]) -> None:
    global _PROCESS
    runtime = _runtime()
    environment = os.environ.copy()
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_DATASETS_OFFLINE": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    try:
        with resource_scheduler.model_slot(
            "OmniVoice Voice Library",
            device=str(runtime.get("device") or "cpu"),
            on_wait=lambda message: _update_state(message=message),
            is_cancelled=_CANCEL.is_set,
        ):
            _update_state(status="running", progress=3, message="Loading local OmniVoice model")
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = subprocess.Popen(
                command,
                cwd=str(PATHS.workspace),
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creation_flags,
            )
            with _LOCK:
                _PROCESS = process
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as log_file:
                log_file.write(f"\n[{_now()}] {' '.join(command)}\n")
                assert process.stdout is not None
                for line in process.stdout:
                    log_file.write(line)
                    log_file.flush()
                    match = re.search(r"Voice\s+(\d+)/(\d+):\s*(\S+)", line)
                    if match:
                        index = int(match.group(1))
                        total = max(1, int(match.group(2)))
                        _update_state(
                            progress=min(94, 5 + round((index - 1) / total * 89)),
                            message=f"Generating {match.group(3)} ({index}/{total})",
                        )
                    if _CANCEL.is_set():
                        process.terminate()
                        break
            return_code = process.wait(timeout=30)
            if _CANCEL.is_set():
                _update_state(
                    status="cancelled",
                    message="Voice Library generation cancelled",
                    completed_at=_now(),
                )
                return
            if return_code != 0:
                raise RuntimeError(f"OmniVoice Voice Library builder exited with code {return_code}")
            synced = sync_generated_profiles()
            summary = _read_json(LAST_BUILD_PATH, {})
            _update_state(
                status="ready",
                progress=100,
                message=f"{len(synced)} OmniVoice profiles available in DubRoom",
                generated=list(summary.get("generated") or selected),
                failed=list(summary.get("failed") or []),
                error=None,
                completed_at=_now(),
            )
    except Exception as exc:
        _update_state(
            status="failed",
            message="Voice Library generation failed",
            error=str(exc)[-4000:],
            completed_at=_now(),
        )
    finally:
        with _LOCK:
            _PROCESS = None


def start_build(options: dict[str, Any]) -> dict[str, Any]:
    global _THREAD
    command, selected = _build_command(options)
    with _LOCK:
        if _THREAD and _THREAD.is_alive():
            raise ValueError("Voice Library generation is already running")
        _CANCEL.clear()
        state = _update_state(
            status="queued",
            progress=0,
            message="Voice Library generation queued",
            error=None,
            selected=selected,
            generated=[],
            failed=[],
            full_tests=bool(options.get("full_tests")),
            started_at=_now(),
            completed_at=None,
        )
        _THREAD = threading.Thread(
            target=_run_build,
            args=(command, selected, dict(options)),
            daemon=True,
            name="dubroom-omnivoice-library",
        )
        _THREAD.start()
        return state


def cancel_build() -> dict[str, Any]:
    _CANCEL.set()
    with _LOCK:
        if _PROCESS and _PROCESS.poll() is None:
            _PROCESS.terminate()
    return _update_state(message="Cancelling Voice Library generation")
