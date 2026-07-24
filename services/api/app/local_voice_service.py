from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from .config import PATHS
    from . import voicebox_service
except ImportError:
    from config import PATHS
    import voicebox_service


ROOT = PATHS.data / "voice-profiles"
INDEX_PATH = ROOT / "profiles.json"


def _read() -> list[dict[str, Any]]:
    if not INDEX_PATH.exists():
        return []
    try:
        value = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write(items: list[dict[str, Any]]) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = INDEX_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(INDEX_PATH)


def profiles() -> list[dict[str, Any]]:
    return _read()


def get(profile_id: str) -> dict[str, Any] | None:
    return next((item for item in _read() if item.get("id") == profile_id), None)


def create_profile(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ValueError("profile.name_required")
    voice_type = str(payload.get("voice_type") or "cloned")
    if voice_type not in {"cloned", "preset", "designed"}:
        raise ValueError("profile.invalid_type")
    now = datetime.now(timezone.utc).isoformat()
    profile = {
        "id": f"local-{uuid4().hex}",
        "name": name,
        "description": payload.get("description"),
        "language": str(payload.get("language") or "en"),
        "voice_type": voice_type,
        "preset_engine": payload.get("preset_engine"),
        "preset_voice_id": payload.get("preset_voice_id"),
        "design_prompt": payload.get("design_prompt"),
        "default_engine": payload.get("default_engine"),
        "personality": payload.get("personality"),
        "effects_chain": payload.get("effects_chain") or [],
        "sample_count": 0,
        "generation_count": 0,
        "samples": [],
        "remote_id": None,
        "origin": "dubroom-local",
        "created_at": now,
        "updated_at": now,
    }
    items = _read()
    items.insert(0, profile)
    _write(items)
    return profile


def add_sample(profile_id: str, file_path: str, reference_text: str) -> dict[str, Any]:
    source = Path(file_path).expanduser().resolve()
    if not source.is_file():
        raise ValueError("profile.sample_missing")
    if source.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("profile.sample_too_large")
    items = _read()
    profile = next((item for item in items if item.get("id") == profile_id), None)
    if not profile:
        raise ValueError("profile.not_found")
    sample_id = uuid4().hex
    sample_dir = ROOT / profile_id / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    destination = sample_dir / f"{sample_id}{source.suffix.lower() or '.wav'}"
    shutil.copy2(source, destination)
    sample = {"id": sample_id, "path": str(destination), "reference_text": reference_text.strip()}
    profile.setdefault("samples", []).append(sample)
    profile["sample_count"] = len(profile["samples"])
    profile["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write(items)
    return {"profile": profile, "sample": sample}


def merged_profiles() -> list[dict[str, Any]]:
    local = profiles()
    try:
        remote = voicebox_service.profiles()
    except RuntimeError:
        remote = []
    synced_ids = {item.get("remote_id") for item in local if item.get("remote_id")}
    return local + [item for item in remote if item.get("id") not in synced_ids]


def ensure_remote_profile(profile_id: str) -> str:
    items = _read()
    profile = next((item for item in items if item.get("id") == profile_id), None)
    if not profile:
        return profile_id
    remote_id = profile.get("remote_id")
    if remote_id:
        return str(remote_id)
    payload = {key: profile.get(key) for key in (
        "name", "description", "language", "voice_type", "preset_engine", "preset_voice_id",
        "design_prompt", "default_engine", "personality",
    ) if profile.get(key) is not None}
    remote = voicebox_service.create_profile(payload)
    remote_id = str(remote.get("id") or "")
    if not remote_id:
        raise RuntimeError("profile.voicebox_sync_failed")
    for sample in profile.get("samples") or []:
        voicebox_service.add_profile_sample(remote_id, str(sample.get("path")), str(sample.get("reference_text") or ""))
    profile["remote_id"] = remote_id
    profile["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write(items)
    return remote_id
