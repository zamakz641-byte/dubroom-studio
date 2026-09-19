from __future__ import annotations

import hashlib
import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from .config import PATHS
except ImportError:
    from config import PATHS


ROOT = PATHS.data / "voice-profiles"
INDEX_PATH = ROOT / "profiles.json"
_LOCK = threading.RLock()
_DESIGN_STATUSES = {"unprepared", "preparing", "ready", "error"}
_GENDERS = {"female", "male", "neutral", "unspecified"}
_AGE_GROUPS = {"child", "teen", "young_adult", "adult", "senior", "unspecified"}
_CASTING_ROLES = {
    "mc",
    "female_lead",
    "narrator",
    "antagonist",
    "supporting",
    "child",
    "background",
    "other",
}
_USAGE_SCOPES = {"both", "single", "multi"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_unlocked() -> list[dict[str, Any]]:
    if not INDEX_PATH.exists():
        return []
    try:
        value = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _read() -> list[dict[str, Any]]:
    with _LOCK:
        return _read_unlocked()


def _write_unlocked(items: list[dict[str, Any]]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = INDEX_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(INDEX_PATH)


def _write(items: list[dict[str, Any]]) -> None:
    with _LOCK:
        _write_unlocked(items)


def _default_design_fields(profile: dict[str, Any]) -> None:
    voice_type = str(profile.get("voice_type") or "cloned")
    if voice_type != "designed":
        return
    status = str(profile.get("design_status") or "unprepared")
    profile["design_status"] = status if status in _DESIGN_STATUSES else "unprepared"
    profile.setdefault("design_seed", 42)
    profile.setdefault("design_reference_text", "")
    profile.setdefault("design_reference_path", None)
    profile.setdefault("design_prompt_cache_path", None)
    profile.setdefault("design_engine_id", None)
    profile.setdefault("clone_engine_id", None)
    profile.setdefault("design_fingerprint", None)
    profile.setdefault("design_locked_at", None)
    profile.setdefault("design_error", None)


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    profile = dict(item)
    profile.pop("remote_id", None)
    profile.setdefault("origin", "dubroom-native")
    profile.setdefault("samples", [])
    profile.setdefault("gender", "unspecified")
    profile.setdefault("age_group", "adult")
    profile.setdefault("primary_role", "other")
    profile.setdefault("roles", [])
    profile.setdefault("usage_scope", "both")
    profile.setdefault("speaker_mode", "single-speaker")
    profile.setdefault("multi_speaker_compatible", True)
    profile["sample_count"] = len(profile["samples"])
    # CASTING_R4_FINAL_PROFILE_DEFAULTS
    profile.setdefault("gender", "unspecified")
    profile.setdefault("age_group", "adult")
    profile.setdefault("primary_role", "other")
    profile.setdefault("roles", [])
    profile.setdefault("traits", [])
    profile.setdefault("usage_scope", "both")
    profile["voice_archetype"] = str(profile.get("voice_archetype") or "").strip().upper() or None
    profile["casting_tags"] = [
        str(value).strip().lower()
        for value in (profile.get("casting_tags") or [])
        if str(value).strip()
    ]
    profile.setdefault("enabled", True)
    profile.setdefault("locked", False)
    _default_design_fields(profile)
    return profile


def profiles() -> list[dict[str, Any]]:
    with _LOCK:
        source = _read_unlocked()
        items = [_normalize(item) for item in source]
        if items and items != source:
            _write_unlocked(items)
        return items


def get(profile_id: str) -> dict[str, Any] | None:
    return next((item for item in profiles() if item.get("id") == profile_id), None)


def upsert_external_profile(
    profile_id: str,
    payload: dict[str, Any],
    *,
    origin: str,
) -> dict[str, Any]:
    """Create or refresh a stable profile owned by a local library provider."""
    now = _now()
    with _LOCK:
        items = _read_unlocked()
        profile = next((item for item in items if item.get("id") == profile_id), None)
        if profile is None:
            profile = {
                "id": profile_id,
                "created_at": now,
                "generation_count": 0,
                "effects_chain": [],
            }
            items.append(profile)
        if str(profile.get("origin") or origin) != origin:
            raise ValueError("profile.external_id_conflict")
        preserved = {
            "created_at": profile.get("created_at") or now,
            "generation_count": int(profile.get("generation_count") or 0),
            "effects_chain": list(profile.get("effects_chain") or []),
        }
        profile.update(payload)
        profile.update(preserved)
        profile.update({"id": profile_id, "origin": origin, "updated_at": now})
        profile.setdefault("samples", [])
        profile["sample_count"] = len(profile["samples"])
        _write_unlocked(items)
        return _normalize(profile)


def design_fingerprint(
    profile: dict[str, Any],
    *,
    reference_text: str | None = None,
) -> str:
    payload = {
        "profile_id": str(profile.get("id") or ""),
        "language": str(profile.get("language") or "en").lower(),
        "design_prompt": str(profile.get("design_prompt") or "").strip(),
        "design_seed": int(profile.get("design_seed") or 42),
        "reference_text": str(
            reference_text
            if reference_text is not None
            else profile.get("design_reference_text") or ""
        ).strip(),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def profile_fingerprint(profile: dict[str, Any] | None) -> str:
    if not profile:
        return "missing-profile"
    payload = {
        "id": str(profile.get("id") or ""),
        "voice_type": str(profile.get("voice_type") or ""),
        "language": str(profile.get("language") or ""),
        "preset_engine": profile.get("preset_engine"),
        "preset_voice_id": profile.get("preset_voice_id"),
        "default_engine": profile.get("default_engine"),
        "personality": profile.get("personality"),
        "design_status": profile.get("design_status"),
        "design_fingerprint": profile.get("design_fingerprint"),
        "design_reference_path": profile.get("design_reference_path"),
        "design_prompt_cache_path": profile.get("design_prompt_cache_path"),
        "clone_engine_id": profile.get("clone_engine_id"),
        "samples": [
            {
                "path": sample.get("path"),
                "reference_text": sample.get("reference_text"),
                "clean_path": sample.get("clean_path"),
                "clean_reference_text": sample.get("clean_reference_text"),
                "cleanup": sample.get("cleanup"),
            }
            for sample in (profile.get("samples") or [])
            if isinstance(sample, dict)
        ],
        "gender": profile.get("gender"),
        "age_group": profile.get("age_group"),
        "primary_role": profile.get("primary_role"),
        "roles": profile.get("roles"),
        "usage_scope": profile.get("usage_scope"),
        "voice_archetype": profile.get("voice_archetype"),
        "casting_tags": profile.get("casting_tags"),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def create_profile(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("profile.name_required")
    voice_type = str(payload.get("voice_type") or "cloned")
    if voice_type not in {"cloned", "preset", "designed"}:
        raise ValueError("profile.invalid_type")
    design_prompt = str(payload.get("design_prompt") or "").strip()
    if voice_type == "designed" and not design_prompt:
        raise ValueError("profile.design_prompt_required")
    gender = str(payload.get("gender") or "unspecified").strip().lower()
    age_group = str(payload.get("age_group") or "adult").strip().lower()
    primary_role = str(payload.get("primary_role") or "other").strip().lower()
    usage_scope = str(payload.get("usage_scope") or "both").strip().lower()
    if gender not in _GENDERS:
        raise ValueError("profile.invalid_gender")
    if age_group not in _AGE_GROUPS:
        raise ValueError("profile.invalid_age_group")
    if primary_role not in _CASTING_ROLES:
        raise ValueError("profile.invalid_casting_role")
    if usage_scope not in _USAGE_SCOPES:
        raise ValueError("profile.invalid_usage_scope")
    roles = [
        str(role).strip().lower()
        for role in (payload.get("roles") or [])
        if str(role).strip()
    ]
    if primary_role != "other" and primary_role not in roles:
        roles.insert(0, primary_role)
    now = _now()
    profile = {
        "id": f"local-{uuid4().hex}",
        "name": name,
        "description": payload.get("description"),
        "language": str(payload.get("language") or "en"),
        "voice_type": voice_type,
        "preset_engine": payload.get("preset_engine"),
        "preset_voice_id": payload.get("preset_voice_id"),
        "design_prompt": design_prompt or None,
        "design_seed": int(payload.get("design_seed") or 42),
        "design_reference_text": str(payload.get("design_reference_text") or "").strip(),
        "design_reference_path": None,
        "design_prompt_cache_path": None,
        "design_engine_id": None,
        "clone_engine_id": None,
        "design_fingerprint": None,
        "design_status": "unprepared" if voice_type == "designed" else None,
        "design_locked_at": None,
        "design_error": None,
        "default_engine": payload.get("default_engine"),
        "personality": payload.get("personality"),
        "gender": gender,
        "age_group": age_group,
        "primary_role": primary_role,
        "roles": list(dict.fromkeys(roles)),
        "usage_scope": usage_scope,
        "speaker_mode": "single-speaker",
        "multi_speaker_compatible": True,
        "effects_chain": payload.get("effects_chain") or [],
        "sample_count": 0,
        "generation_count": 0,
        "samples": [],
        "origin": "dubroom-native",
        "created_at": now,
        "updated_at": now,
        "gender": payload.get("gender", "unspecified"),
        "age_group": payload.get("age_group", "adult"),
        "primary_role": payload.get("primary_role", "other"),
        "roles": payload.get("roles") or [],
        "usage_scope": payload.get("usage_scope") or "both",
        "voice_archetype": str(payload.get("voice_archetype") or "").strip().upper() or None,
        "casting_tags": [str(value).strip().lower() for value in (payload.get("casting_tags") or []) if str(value).strip()],
        "enabled": bool(payload.get("enabled", True)),
        "locked": bool(payload.get("locked", False)),
    }
    with _LOCK:
        items = _read_unlocked()
        items.insert(0, profile)
        _write_unlocked(items)
    return _normalize(profile)


def update_profile(profile_id: str, changes: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        items = _read_unlocked()
        profile = next((item for item in items if item.get("id") == profile_id), None)
        if not profile:
            raise ValueError("profile.not_found")
        profile.update(changes)
        profile["updated_at"] = _now()
        _default_design_fields(profile)
        _write_unlocked(items)
        return _normalize(profile)


def begin_design_preparation(
    profile_id: str,
    *,
    fingerprint: str,
    reference_text: str,
) -> dict[str, Any]:
    return update_profile(
        profile_id,
        {
            "design_status": "preparing",
            "design_fingerprint": fingerprint,
            "design_reference_text": reference_text,
            "design_error": None,
        },
    )


def complete_design_preparation(
    profile_id: str,
    *,
    fingerprint: str,
    reference_text: str,
    reference_path: str,
    prompt_cache_path: str,
    design_engine_id: str,
    clone_engine_id: str,
) -> dict[str, Any]:
    return update_profile(
        profile_id,
        {
            "design_status": "ready",
            "design_fingerprint": fingerprint,
            "design_reference_text": reference_text,
            "design_reference_path": reference_path,
            "design_prompt_cache_path": prompt_cache_path,
            "design_engine_id": design_engine_id,
            "clone_engine_id": clone_engine_id,
            "design_locked_at": _now(),
            "design_error": None,
        },
    )


def fail_design_preparation(profile_id: str, error: str) -> dict[str, Any]:
    return update_profile(
        profile_id,
        {
            "design_status": "error",
            "design_error": str(error)[-4000:],
        },
    )


def reset_designed_profile(profile_id: str) -> dict[str, Any]:
    profile = get(profile_id)
    if not profile:
        raise ValueError("profile.not_found")
    if str(profile.get("voice_type")) != "designed":
        raise ValueError("profile.not_designed")
    profile_dir = ROOT / profile_id / "design"
    if profile_dir.is_dir():
        shutil.rmtree(profile_dir, ignore_errors=True)
    prompt_dir = ROOT / profile_id / "prompts"
    if prompt_dir.is_dir():
        for path in prompt_dir.glob("qwen-design-*.pt"):
            path.unlink(missing_ok=True)
    return update_profile(
        profile_id,
        {
            "design_status": "unprepared",
            "design_reference_path": None,
            "design_prompt_cache_path": None,
            "design_engine_id": None,
            "clone_engine_id": None,
            "design_fingerprint": None,
            "design_locked_at": None,
            "design_error": None,
        },
    )


def add_sample(
    profile_id: str,
    file_path: str,
    reference_text: str,
    *,
    transcription: dict[str, Any] | None = None,
    cleaned_reference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = Path(file_path).expanduser().resolve()
    if not source.is_file():
        raise ValueError("profile.sample_missing")
    if source.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("profile.sample_too_large")
    with _LOCK:
        items = _read_unlocked()
        profile = next((item for item in items if item.get("id") == profile_id), None)
        if not profile:
            raise ValueError("profile.not_found")
        sample_id = uuid4().hex
        sample_dir = ROOT / profile_id / "samples"
        sample_dir.mkdir(parents=True, exist_ok=True)
        destination = sample_dir / f"{sample_id}{source.suffix.lower() or '.wav'}"
        shutil.copy2(source, destination)
        sample = {
            "id": sample_id,
            "path": str(destination),
            "reference_text": reference_text.strip(),
            "reference_text_source": "whisper" if transcription else "manual",
            "transcription": transcription,
        }
        if cleaned_reference:
            cleaned_source = Path(str(cleaned_reference.get("path") or "")).resolve()
            if not cleaned_source.is_file():
                raise ValueError("profile.cleaned_sample_missing")
            processed_dir = ROOT / profile_id / "processed"
            processed_dir.mkdir(parents=True, exist_ok=True)
            cleaned_destination = processed_dir / f"{sample_id}.clean.wav"
            shutil.copy2(cleaned_source, cleaned_destination)
            sample.update(
                {
                    "clean_path": str(cleaned_destination),
                    "clean_reference_text": str(
                        cleaned_reference.get("reference_text") or reference_text
                    ).strip(),
                    "cleanup": {
                        key: value
                        for key, value in cleaned_reference.items()
                        if key not in {"path", "source_path", "reference_text"}
                    },
                }
            )
        profile.setdefault("samples", []).append(sample)
        profile["sample_count"] = len(profile["samples"])
        profile["updated_at"] = _now()
        _write_unlocked(items)
        return {"profile": _normalize(profile), "sample": sample}


def attach_cleaned_sample(
    profile_id: str,
    sample_id: str,
    cleaned_reference: dict[str, Any],
    *,
    transcription: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach a non-destructive cleaned copy to an existing cloned-voice sample."""
    cleaned_source = Path(str(cleaned_reference.get("path") or "")).resolve()
    if not cleaned_source.is_file():
        raise ValueError("profile.cleaned_sample_missing")
    with _LOCK:
        items = _read_unlocked()
        profile = next((item for item in items if item.get("id") == profile_id), None)
        if not profile:
            raise ValueError("profile.not_found")
        sample = next(
            (item for item in profile.get("samples") or [] if item.get("id") == sample_id),
            None,
        )
        if not sample:
            raise ValueError("profile.sample_not_found")
        processed_dir = ROOT / profile_id / "processed"
        processed_dir.mkdir(parents=True, exist_ok=True)
        destination = processed_dir / f"{sample_id}.clean.wav"
        if cleaned_source != destination.resolve():
            shutil.copy2(cleaned_source, destination)
        sample.update(
            {
                "clean_path": str(destination),
                "clean_reference_text": str(
                    cleaned_reference.get("reference_text")
                    or sample.get("reference_text")
                    or ""
                ).strip(),
                "cleanup": {
                    key: value
                    for key, value in cleaned_reference.items()
                    if key not in {"path", "source_path", "reference_text"}
                },
            }
        )
        if transcription:
            sample["transcription"] = transcription
        profile["updated_at"] = _now()
        _write_unlocked(items)
        return {"profile": _normalize(profile), "sample": sample}


def record_generation(profile_id: str) -> None:
    with _LOCK:
        items = _read_unlocked()
        profile = next((item for item in items if item.get("id") == profile_id), None)
        if not profile:
            return
        profile["generation_count"] = int(profile.get("generation_count") or 0) + 1
        profile["updated_at"] = _now()
        _write_unlocked(items)
