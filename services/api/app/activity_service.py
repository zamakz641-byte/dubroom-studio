from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import PATHS


SIMULATION_ROOT = PATHS.data / "activity-simulations"
ACTIVE_STATUSES = {"queued", "running", "downloading", "processing", "installing", "repairing"}
TERMINAL_STATUSES = {"completed", "ready", "failed", "cancelled", "partial", "interrupted"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalise_status(value: str) -> str:
    status = value.lower().strip()
    if status in {"downloading", "processing", "installing", "repairing"}:
        return "running"
    if status == "ready":
        return "completed"
    return status or "queued"


def _activity(
    *,
    kind: str,
    source_id: str,
    activity_type: str,
    title: str,
    state: dict[str, Any],
    project_id: str | None = None,
    artifact_path: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw_status = str(state.get("status", "queued"))
    status = _normalise_status(raw_status)
    return {
        "id": f"{kind}:{source_id}",
        "source_id": source_id,
        "kind": kind,
        "type": activity_type,
        "title": title,
        "status": status,
        "raw_status": raw_status,
        "progress": max(0, min(100, int(float(state.get("progress", 0) or 0)))),
        "message": str(state.get("message") or ""),
        "error": state.get("error"),
        "project_id": project_id,
        "artifact_path": artifact_path,
        "created_at": str(state.get("created_at") or state.get("updated_at") or _now()),
        "updated_at": str(state.get("updated_at") or state.get("created_at") or _now()),
        "can_cancel": status in {"queued", "running"} and kind in {"project", "youtube", "rvc", "subclean", "engine", "simulation"},
        "can_retry": status in {"failed", "cancelled", "interrupted"},
        "simulation": kind == "simulation",
        "metadata": metadata or {},
    }


def list_activities(limit: int = 100) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for project_dir in PATHS.projects.iterdir() if PATHS.projects.exists() else []:
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue
        for path in (project_dir / "jobs").glob("*.json") if (project_dir / "jobs").exists() else []:
            state = _read_json(path)
            if not state:
                continue
            job_id = str(state.get("id") or path.stem)
            job_type = str(state.get("type") or "job")
            items.append(_activity(
                kind="project",
                source_id=job_id,
                activity_type=job_type,
                title=job_type.replace("_", " ").title(),
                state=state,
                project_id=str(state.get("project_id") or project_dir.name),
                artifact_path=next(iter((state.get("artifacts") or {}).values()), None),
                metadata={"options": state.get("options") or {}},
            ))

    engine_root = PATHS.data / "engine-state"
    for path in engine_root.glob("*/state.json") if engine_root.exists() else []:
        state = _read_json(path)
        if not state or str(state.get("status", "")) not in ACTIVE_STATUSES | TERMINAL_STATUSES:
            continue
        engine_id = path.parent.name
        items.append(_activity(
            kind="engine",
            source_id=engine_id,
            activity_type="model_download" if engine_id.startswith(("faster-whisper-", "translation-")) else "engine_install",
            title=engine_id.replace("-", " ").title(),
            state=state,
            artifact_path=state.get("log_path"),
        ))

    sources = [
        ("youtube", PATHS.data / "youtube-downloads" / "state", "youtube_download", "YouTube import", "path"),
        ("rvc", PATHS.data / "rvc" / "jobs", "rvc", "RVC conversion", "output_path"),
        ("subclean", PATHS.data / "subclean" / "jobs", "subclean", "Subtitle cleanup", "output_path"),
    ]
    for kind, root, activity_type, fallback_title, artifact_key in sources:
        for path in root.glob("*.json") if root.exists() else []:
            state = _read_json(path)
            if not state:
                continue
            source_id = str(state.get("id") or path.stem)
            items.append(_activity(
                kind=kind,
                source_id=source_id,
                activity_type=activity_type,
                title=str(state.get("title") or fallback_title),
                state=state,
                artifact_path=state.get(artifact_key),
                metadata={key: state.get(key) for key in ("url", "source_path", "model_id", "mode") if state.get(key) is not None},
            ))

    for path in SIMULATION_ROOT.glob("*.json") if SIMULATION_ROOT.exists() else []:
        state = _read_json(path)
        if not state:
            continue
        source_id = str(state.get("id") or path.stem)
        items.append(_activity(
            kind="simulation",
            source_id=source_id,
            activity_type=str(state.get("type") or "simulation"),
            title=str(state.get("title") or "Pipeline simulation"),
            state=state,
            metadata={"run_id": state.get("run_id"), "step": state.get("step")},
        ))

    items.sort(key=lambda item: item["updated_at"], reverse=True)
    return items[: max(1, min(limit, 250))]


def get_activity(activity_id: str) -> dict[str, Any]:
    return next((item for item in list_activities(250) if item["id"] == activity_id), None) or (_raise_key(activity_id))


def _raise_key(activity_id: str) -> dict[str, Any]:
    raise KeyError(activity_id)


def reconcile_interrupted() -> int:
    """Turn stale persisted work into an explicit recoverable state on startup."""
    changed = 0
    roots = [
        PATHS.data / "youtube-downloads" / "state",
        PATHS.data / "rvc" / "jobs",
        PATHS.data / "subclean" / "jobs",
        PATHS.data / "engine-state",
        SIMULATION_ROOT,
    ]
    paths: list[Path] = []
    for root in roots:
        if root.name == "engine-state":
            paths.extend(root.glob("*/state.json") if root.exists() else [])
        else:
            paths.extend(root.glob("*.json") if root.exists() else [])
    if PATHS.projects.exists():
        for project_dir in PATHS.projects.iterdir():
            if project_dir.is_dir() and not project_dir.name.startswith("."):
                paths.extend((project_dir / "jobs").glob("*.json") if (project_dir / "jobs").exists() else [])
    for path in paths:
        state = _read_json(path)
        if not state or str(state.get("status", "")).lower() not in ACTIVE_STATUSES:
            continue
        state.update({
            "status": "interrupted",
            "message": "Interrupted when the local runtime stopped",
            "error": "activity.interrupted",
            "updated_at": _now(),
        })
        _write_json(path, state)
        changed += 1
    return changed


PIPELINE_STEPS = [
    ("youtube_download", "Source import"),
    ("asr", "Transcription"),
    ("translation", "Translation and adaptation"),
    ("voice_generation", "Voice generation"),
    ("rvc", "RVC voice conversion"),
    ("mix", "Dialogue mix"),
    ("export", "Final export"),
]


def create_simulation() -> dict[str, Any]:
    run_id = uuid4().hex[:10]
    now = _now()
    for index, (activity_type, title) in enumerate(PIPELINE_STEPS):
        activity_id = f"{run_id}-{index + 1:02d}"
        _write_json(SIMULATION_ROOT / f"{activity_id}.json", {
            "id": activity_id,
            "run_id": run_id,
            "step": index + 1,
            "type": activity_type,
            "title": title,
            "status": "queued",
            "progress": 0,
            "message": "Waiting for the previous stage",
            "error": None,
            "created_at": now,
            "updated_at": now,
        })
    return {"run_id": run_id, "activities": [item for item in list_activities(250) if item.get("metadata", {}).get("run_id") == run_id]}


def run_simulation(run_id: str, step_delay: float = 0.65) -> None:
    paths = sorted(SIMULATION_ROOT.glob(f"{run_id}-*.json"))
    for path in paths:
        state = _read_json(path)
        if not state:
            continue
        for progress, message in ((12, "Preparing local resources"), (46, "Processing without model weights"), (82, "Validating the generated artifact")):
            current = _read_json(path)
            if not current or current.get("status") == "cancelled":
                return
            current.update({"status": "running", "progress": progress, "message": message, "updated_at": _now()})
            _write_json(path, current)
            time.sleep(step_delay)
        current = _read_json(path) or state
        current.update({"status": "completed", "progress": 100, "message": "Simulation stage completed", "updated_at": _now()})
        _write_json(path, current)


def cancel_simulation(source_id: str) -> dict[str, Any]:
    state = _read_json(SIMULATION_ROOT / f"{source_id}.json")
    if not state:
        raise KeyError(source_id)
    run_id = str(state.get("run_id") or "")
    for path in SIMULATION_ROOT.glob(f"{run_id}-*.json"):
        value = _read_json(path)
        if value and _normalise_status(str(value.get("status", ""))) in {"queued", "running"}:
            value.update({"status": "cancelled", "message": "Simulation cancelled", "updated_at": _now()})
            _write_json(path, value)
    return get_activity(f"simulation:{source_id}")


def clear_simulations() -> int:
    removed = 0
    for path in SIMULATION_ROOT.glob("*.json") if SIMULATION_ROOT.exists() else []:
        path.unlink(missing_ok=True)
        removed += 1
    return removed
