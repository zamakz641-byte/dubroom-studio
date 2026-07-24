import base64
import json
import os
import platform
import shutil
import subprocess
import time
import wave
from array import array
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
from re import search, sub
from typing import Any

try:
    import psutil
    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

try:
    from .tts_service import TTSService
    from .config import API_HOST, API_PORT, PATHS, load_runtime_config
    from .engine_service import cancel_install, get_engine, installation_preview, list_engines, load_registry, queue_install, run_install, validate_model_source
    from . import activity_service, export_service, library_service, local_voice_service, rvc_service, subclean_service, voicebox_service, youtube_service
except ImportError:
    from tts_service import TTSService
    from config import API_HOST, API_PORT, PATHS, load_runtime_config
    from engine_service import cancel_install, get_engine, installation_preview, list_engines, load_registry, queue_install, run_install, validate_model_source
    import activity_service, export_service, library_service, local_voice_service, rvc_service, subclean_service, voicebox_service, youtube_service


class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: str


class MediaProbeRequest(BaseModel):
    path: str


class VideoStream(BaseModel):
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None


class AudioStream(BaseModel):
    codec: str | None = None
    channels: int | None = None
    sample_rate: int | None = None


class MediaProbeResponse(BaseModel):
    path: str
    file_name: str
    duration_seconds: float | None = None
    size_bytes: int | None = None
    format_name: str | None = None
    video: VideoStream | None = None
    audio: AudioStream | None = None


class MediaPrepareRequest(BaseModel):
    path: str
    project_name: str | None = None
    source_language: str | None = None
    target_language: str | None = None


class YouTubeUrlRequest(BaseModel):
    url: str


class YouTubeDownloadRequest(BaseModel):
    url: str
    title: str | None = None


class RvcModelImportRequest(BaseModel):
    model_path: str
    index_path: str | None = None
    name: str
    author: str | None = None
    license: str | None = None
    authorized: bool = False


class RvcConversionRequest(BaseModel):
    source_path: str
    model_id: str
    pitch: int = 0
    f0_method: str = "rmvpe"
    index_rate: float = 0.75
    protect: float = 0.33


class SubCleanRequest(BaseModel):
    source_path: str
    mode: str = "sttn-auto"
    areas: list[list[int]] = Field(default_factory=list)


class ProjectDerivedSourceRequest(BaseModel):
    path: str
    kind: str = "subclean"


class MediaPrepareResponse(BaseModel):
    project_id: str
    project_dir: str
    audio_path: str
    manifest_path: str
    waveform: list[float]
    media: MediaProbeResponse


class ProjectCreateRequest(BaseModel):
    name: str
    source_language: str | None = None
    target_language: str | None = None
    performance_profile: str | None = None


class LibraryAssetRequest(BaseModel):
    kind: str
    name: str
    path: str | None = None
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectRecord(BaseModel):
    id: str
    name: str
    status: str
    project_dir: str
    source_path: str | None = None
    original_source_path: str | None = None
    derived_sources: list[dict[str, str]] = Field(default_factory=list)
    media_manifest_path: str | None = None
    source_language: str | None = None
    target_language: str | None = None
    performance_profile: str | None = None
    created_at: str
    updated_at: str


class SpeakerRecord(BaseModel):
    name: str
    role: str
    duration: str
    color: str
    level: int
    voice_profile_id: str | None = None
    voice_engine: str | None = None
    voice_model: str | None = None
    voice_instruct: str | None = None
    effects_chain: list[dict[str, Any]] = Field(default_factory=list)


class SegmentRecord(BaseModel):
    id: str
    left: float
    width: float
    lane: int
    speaker: str
    label: str
    color: str
    start: str
    end: str
    sourceText: str
    translatedText: str
    adaptedText: str
    emotion: str
    intensity: int
    pace: int
    fit: int
    locked: bool


class MixSettings(BaseModel):
    voice_volume: float = 1.0
    original_volume: float = 0.32
    music_volume: float = 0.5
    voice_muted: bool = False
    original_muted: bool = False
    music_muted: bool = False
    normalize: bool = True
    ducking: bool = True
    music_path: str | None = None


class ProjectAnalysisState(BaseModel):
    speakers: list[SpeakerRecord]
    segments: list[SegmentRecord]
    updated_at: str
    source_language: str | None = None
    target_language: str | None = None
    mix: MixSettings = Field(default_factory=MixSettings)


class JobCreateRequest(BaseModel):
    type: str
    options: dict[str, Any] = Field(default_factory=dict)


class ExportPlanRequest(BaseModel):
    options: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float | None = None


class TimelineProjectState(BaseModel):
    version: int = 3
    markers: list[dict[str, Any]] = Field(default_factory=list)
    export_regions: list[dict[str, Any]] = Field(default_factory=list)
    edit_initialized: bool = False
    edit_clips: list[dict[str, Any]] = Field(default_factory=list)
    in_point: float | None = None
    out_point: float | None = None
    track_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    preferences: dict[str, Any] = Field(default_factory=dict)
    updated_at: str | None = None


class EngineInstallRequest(BaseModel):
    repair: bool = False
    dry_run: bool = False
    credentials: dict[str, str] = Field(default_factory=dict)


class VoiceboxModelRequest(BaseModel):
    model_name: str


class VoiceboxGenerateRequest(BaseModel):
    profile_id: str
    text: str
    language: str = "en"
    engine: str | None = None
    model_size: str | None = None
    instruct: str | None = None
    personality: bool = False
    max_chunk_chars: int = 800
    crossfade_ms: int = 50
    normalize: bool = True
    effects_chain: list[dict[str, Any]] | None = None


class VoiceboxProfileRequest(BaseModel):
    name: str
    description: str | None = None
    language: str = "en"
    voice_type: str = "cloned"
    preset_engine: str | None = None
    preset_voice_id: str | None = None
    design_prompt: str | None = None
    default_engine: str | None = None
    personality: str | None = None


class VoiceboxSampleRequest(BaseModel):
    path: str
    reference_text: str


class VoiceboxRecordedSampleRequest(BaseModel):
    data_url: str
    reference_text: str
    file_name: str = "voice-sample.webm"


class JobRecord(BaseModel):
    id: str
    project_id: str
    type: str
    status: str
    progress: int
    message: str
    created_at: str
    updated_at: str
    artifacts: dict[str, str] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


WORKSPACE_ROOT = PATHS.workspace
PROJECTS_ROOT = PATHS.projects
TRASH_ROOT = PROJECTS_ROOT / ".trash"
MODELS_ROOT = PATHS.models
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v"}
EXPORT_CANCEL_REQUESTS: set[str] = set()

app = FastAPI(title="Dub Studio Local API", version="0.1.0")


@app.on_event("startup")
def reconcile_interrupted_activity() -> None:
    activity_service.reconcile_interrupted()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("DUBSTUDIO_CORS_ORIGINS", "http://127.0.0.1:5173,http://127.0.0.1:4173,null").split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="dub-studio-api",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/activities")
def global_activities(limit: int = Query(default=100, ge=1, le=250)) -> dict[str, Any]:
    items = activity_service.list_activities(limit)
    return {
        "activities": items,
        "active_count": len([item for item in items if item["status"] in {"queued", "running"}]),
        "failed_count": len([item for item in items if item["status"] in {"failed", "interrupted"}]),
    }


@app.post("/activities/simulate")
def simulate_global_activity(background_tasks: BackgroundTasks) -> dict[str, Any]:
    simulation = activity_service.create_simulation()
    background_tasks.add_task(activity_service.run_simulation, simulation["run_id"])
    return simulation


@app.delete("/activities/simulations")
def clear_activity_simulations() -> dict[str, Any]:
    return {"deleted": activity_service.clear_simulations()}


@app.post("/activities/{activity_id}/cancel")
def cancel_global_activity(activity_id: str) -> dict[str, Any]:
    try:
        activity = activity_service.get_activity(activity_id)
        kind = activity["kind"]
        source_id = activity["source_id"]
        if kind == "project" and activity.get("project_id"):
            result = cancel_project_job(str(activity["project_id"]), source_id)
            return {"status": result.status, "activity_id": activity_id}
        if kind == "youtube":
            result = youtube_service.cancel(source_id)
        elif kind == "rvc":
            result = rvc_service.cancel(source_id)
        elif kind == "subclean":
            result = subclean_service.cancel(source_id)
        elif kind == "engine":
            result = cancel_install(source_id)
        elif kind == "simulation":
            result = activity_service.cancel_simulation(source_id)
        else:
            raise RuntimeError("This activity cannot be cancelled")
        return {"status": result.get("status", "cancelled"), "activity_id": activity_id}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Activity not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/activities/{activity_id}/retry")
def retry_global_activity(activity_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    try:
        activity = activity_service.get_activity(activity_id)
        kind = activity["kind"]
        source_id = activity["source_id"]
        if kind == "project" and activity.get("project_id"):
            project_dir = _require_project_dir(str(activity["project_id"]))
            previous = _read_job(project_dir, source_id)
            if not previous:
                raise KeyError(source_id)
            result = create_project_job(
                str(activity["project_id"]),
                JobCreateRequest(type=previous.type, options=previous.options or {}),
                background_tasks,
            )
            return {"status": result.status, "source_id": result.id}
        if kind == "engine":
            state = queue_install(source_id, repair=True)
            background_tasks.add_task(run_install, source_id, True, {})
            return {"status": state["status"], "source_id": source_id}
        if kind == "youtube":
            previous = youtube_service.get(source_id)
            state = youtube_service.start(str(previous["url"]), str(previous.get("title") or "YouTube video"))
            background_tasks.add_task(youtube_service.run, state["id"])
            return {"status": state["status"], "source_id": state["id"]}
        if kind == "rvc":
            previous = rvc_service.get(source_id)
            state = rvc_service.start(
                previous["source_path"], previous["model_id"], previous.get("pitch", 0),
                previous.get("f0_method", "rmvpe"), previous.get("index_rate", 0.75), previous.get("protect", 0.33),
            )
            background_tasks.add_task(rvc_service.run, state["id"])
            return {"status": state["status"], "source_id": state["id"]}
        if kind == "subclean":
            previous = subclean_service.get(source_id)
            state = subclean_service.start(previous["source_path"], previous.get("mode", "sttn-auto"), previous.get("areas", []))
            background_tasks.add_task(subclean_service.run, state["id"])
            return {"status": state["status"], "source_id": state["id"]}
        if kind == "simulation":
            simulation = activity_service.create_simulation()
            background_tasks.add_task(activity_service.run_simulation, simulation["run_id"])
            return {"status": "queued", "source_id": simulation["run_id"]}
        raise RuntimeError("This activity cannot be retried")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Activity not found") from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/runtime/status")
def runtime_status() -> dict[str, Any]:
    engines = list_engines()
    def capability(category: str) -> str:
        candidates = [engine for engine in engines if engine.get("category") == category]
        if any((engine.get("verification") or {}).get("usable") for engine in candidates):
            return "ready"
        if any(engine.get("installation", {}).get("status") == "ready" for engine in candidates):
            return "verify"
        return "not-installed"

    voicebox = voicebox_service.status()
    rvc = rvc_service.status()
    subclean = subclean_service.status()
    ffmpeg_ready = _tool_available("ffmpeg")
    ffprobe_ready = _tool_available("ffprobe")
    return {
        "status": "ready",
        "workspace_root": str(WORKSPACE_ROOT),
        "projects_root": str(PROJECTS_ROOT),
        "supported_video_extensions": sorted(SUPPORTED_VIDEO_EXTENSIONS),
        "tools": {
            "ffmpeg": _tool_available("ffmpeg"),
            "ffprobe": _tool_available("ffprobe"),
            "nvidia_smi": _tool_available("nvidia-smi"),
        },
        "models": {"asr": [engine for engine in engines if engine.get("category") == "asr"]},
        "hardware": _runtime_hardware(),
        "pipeline": {
            "probe": "ready" if ffprobe_ready else "not-installed",
            "prepare_audio": "ready" if ffmpeg_ready else "not-installed",
            "subtitle_cleanup": "ready" if subclean["runtime_ready"] else "not-installed",
            "asr": capability("asr"),
            "diarization": capability("diarization"),
            "translation": capability("translation"),
            "tts": "ready" if voicebox["online"] else "available" if voicebox["runtime_ready"] else "not-installed",
            "rvc": "ready" if rvc["runtime_ready"] and rvc["worker_ready"] else "not-installed",
            "export": "ready" if ffmpeg_ready else "not-installed",
        },
    }


@app.get("/config")
def application_config() -> dict[str, Any]:
    return load_runtime_config()


@app.get("/library/assets")
def library_assets(kind: str | None = None) -> dict[str, Any]:
    try:
        return {"assets": library_service.list_assets(kind)}
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/library/assets")
def library_create_asset(request: LibraryAssetRequest) -> dict[str, Any]:
    try:
        return library_service.create_asset(request.model_dump())
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/library/assets/{asset_id}")
def library_delete_asset(asset_id: str) -> dict[str, bool]:
    return {"deleted": library_service.delete_asset(asset_id)}


@app.get("/projects")
def list_projects() -> dict[str, list[ProjectRecord]]:
    return {"projects": _list_project_records()}


@app.post("/projects", response_model=ProjectRecord)
def create_project(request: ProjectCreateRequest) -> ProjectRecord:
    project_id = _make_project_id(request.name)
    project_dir = PROJECTS_ROOT / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    record = ProjectRecord(
        id=project_id,
        name=request.name,
        status="draft",
        project_dir=str(project_dir),
        source_language=request.source_language,
        target_language=request.target_language,
        performance_profile=request.performance_profile,
        created_at=now,
        updated_at=now,
    )
    _write_project_record(project_dir, record)
    return record


@app.get("/projects/trash")
def list_project_trash() -> dict[str, list[dict[str, Any]]]:
    TRASH_ROOT.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for trash_dir in TRASH_ROOT.iterdir():
        if not trash_dir.is_dir():
            continue
        metadata = _read_json(trash_dir / "trash.json")
        project = _read_project_record(trash_dir)
        if project:
            items.append({
                "trash_id": trash_dir.name,
                "deleted_at": str(metadata.get("deleted_at") or project.updated_at),
                "original_id": str(metadata.get("original_id") or project.id),
                "project": project.model_dump(mode="json"),
            })
    items.sort(key=lambda item: item["deleted_at"], reverse=True)
    return {"projects": items}


@app.delete("/projects/{project_id}")
def trash_project(project_id: str) -> dict[str, Any]:
    project_dir = _require_project_dir(project_id)
    active = [job for job in _list_jobs(project_dir) if job.status in {"queued", "running"}]
    if active:
        raise HTTPException(status_code=409, detail="project.active_job")
    record = _read_project_record(project_dir)
    if not record:
        raise HTTPException(status_code=404, detail="project.not_found")
    TRASH_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc)
    trash_id = f"{project_id}-{stamp.strftime('%Y%m%d-%H%M%S-%f')}"
    destination = (TRASH_ROOT / trash_id).resolve()
    if TRASH_ROOT.resolve() not in destination.parents:
        raise HTTPException(status_code=400, detail="project.invalid_id")
    shutil.move(str(project_dir), str(destination))
    (destination / "trash.json").write_text(json.dumps({
        "trash_id": trash_id,
        "original_id": project_id,
        "deleted_at": stamp.isoformat(),
    }, indent=2), encoding="utf-8")
    return {"trash_id": trash_id, "deleted_at": stamp.isoformat(), "project": record.model_dump(mode="json")}


@app.post("/projects/trash/{trash_id}/restore", response_model=ProjectRecord)
def restore_project_from_trash(trash_id: str) -> ProjectRecord:
    trash_dir = _require_trash_dir(trash_id)
    metadata = _read_json(trash_dir / "trash.json")
    original_id = str(metadata.get("original_id") or trash_id.rsplit("-", 3)[0])
    destination = (PROJECTS_ROOT / original_id).resolve()
    if PROJECTS_ROOT.resolve() not in destination.parents or destination.parent == TRASH_ROOT.resolve():
        raise HTTPException(status_code=400, detail="project.invalid_id")
    if destination.exists():
        raise HTTPException(status_code=409, detail="project.restore_conflict")
    (trash_dir / "trash.json").unlink(missing_ok=True)
    shutil.move(str(trash_dir), str(destination))
    record = _read_project_record(destination)
    if not record:
        raise HTTPException(status_code=422, detail="project.invalid_record")
    record.project_dir = str(destination)
    record.updated_at = datetime.now(timezone.utc).isoformat()
    _write_project_record(destination, record)
    return record


@app.delete("/projects/trash/{trash_id}")
def permanently_delete_project(trash_id: str) -> dict[str, bool]:
    trash_dir = _require_trash_dir(trash_id)
    shutil.rmtree(trash_dir)
    return {"deleted": True}


@app.get("/projects/{project_id}", response_model=ProjectRecord)
def get_project(project_id: str) -> ProjectRecord:
    project_dir = PROJECTS_ROOT / project_id
    record = _read_project_record(project_dir)
    if not record:
        raise HTTPException(status_code=404, detail="Project not found")
    return record


@app.get("/projects/{project_id}/analysis/state", response_model=ProjectAnalysisState)
def get_project_analysis(project_id: str) -> ProjectAnalysisState:
    project_dir = _require_project_dir(project_id)
    return _read_or_create_analysis_state(project_dir)


@app.put("/projects/{project_id}/analysis/state", response_model=ProjectAnalysisState)
def update_project_analysis(project_id: str, state: ProjectAnalysisState) -> ProjectAnalysisState:
    project_dir = _require_project_dir(project_id)
    existing = _read_or_create_analysis_state(project_dir)
    state.source_language = state.source_language or existing.source_language
    state.target_language = state.target_language or existing.target_language
    state.updated_at = datetime.now(timezone.utc).isoformat()
    _write_analysis_state(project_dir, state)
    _touch_project_record(project_dir, state.updated_at)
    return state


@app.get("/projects/{project_id}/timeline/state", response_model=TimelineProjectState)
def get_timeline_state(project_id: str) -> TimelineProjectState:
    project_dir = _require_project_dir(project_id)
    path = project_dir / "analysis" / "timeline-v2.json"
    if not path.exists():
        return TimelineProjectState()
    try:
        return TimelineProjectState.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return TimelineProjectState()


@app.put("/projects/{project_id}/timeline/state", response_model=TimelineProjectState)
def save_timeline_state(project_id: str, state: TimelineProjectState) -> TimelineProjectState:
    project_dir = _require_project_dir(project_id)
    state.version = 3
    state.updated_at = datetime.now(timezone.utc).isoformat()
    path = project_dir / "analysis" / "timeline-v2.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.model_dump(mode="json"), indent=2), encoding="utf-8")
    return state


@app.post("/projects/{project_id}/exports/plan")
def create_export_plan(project_id: str, request: ExportPlanRequest) -> dict[str, Any]:
    project_dir = _require_project_dir(project_id)
    manifest = _read_json(project_dir / "analysis" / "media_manifest.json")
    duration = request.duration_seconds if request.duration_seconds is not None else _manifest_duration_seconds(manifest)
    analysis = _read_or_create_analysis_state(project_dir)
    segment_times = {
        segment.id: (_timestamp_seconds(segment.start), _timestamp_seconds(segment.end))
        for segment in analysis.segments
    }
    try:
        return export_service.plan_export(duration, request.options, segment_times)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/projects/{project_id}/jobs")
def list_project_jobs(project_id: str) -> dict[str, list[JobRecord]]:
    project_dir = _require_project_dir(project_id)
    return {"jobs": _list_jobs(project_dir)}


@app.post("/projects/{project_id}/jobs", response_model=JobRecord)
def create_project_job(project_id: str, request: JobCreateRequest, background_tasks: BackgroundTasks) -> JobRecord:
    project_dir = _require_project_dir(project_id)
    now = datetime.now(timezone.utc).isoformat()
    job_type = request.type.strip().lower()
    if job_type not in {"asr", "diarization", "translation", "voice_generation", "preview", "export"}:
        raise HTTPException(status_code=400, detail="Unsupported job type")
    options = request.options
    if job_type == "export":
        try:
            options = export_service.normalise_options(options)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    job = _create_queued_job(project_id, job_type, now, options)
    _write_job(project_dir, job)
    background_tasks.add_task(_execute_project_job, project_id, job.id, job_type, options)
    return job


@app.get("/projects/{project_id}/jobs/{job_id}", response_model=JobRecord)
def get_project_job(project_id: str, job_id: str) -> JobRecord:
    project_dir = _require_project_dir(project_id)
    job = _read_job(project_dir, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/projects/{project_id}/jobs/{job_id}/cancel", response_model=JobRecord)
def cancel_project_job(project_id: str, job_id: str) -> JobRecord:
    project_dir = _require_project_dir(project_id)
    job = _read_job(project_dir, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in {"queued", "running"}:
        return job
    EXPORT_CANCEL_REQUESTS.add(job_id)
    updated = job.model_copy(update={"message": "Cancellation requested", "updated_at": datetime.now(timezone.utc).isoformat()})
    _write_job(project_dir, updated)
    return updated


@app.get("/exports/capabilities")
def export_capabilities() -> dict[str, Any]:
    return export_service.capabilities()


@app.get("/runtime/profile")
def runtime_profile() -> dict[str, Any]:
    """Return the recommended performance profile for the current machine."""
    hw = _runtime_hardware()
    profile = _select_performance_profile(hw)
    return profile


@app.get("/models/registry")
def model_registry() -> dict[str, Any]:
    try:
        return load_registry()
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="Model registry is not valid JSON") from exc


@app.get("/engines")
def engines_catalog() -> dict[str, Any]:
    return {"engines": list_engines()}


@app.get("/engines/{engine_id}")
def engine_details(engine_id: str) -> dict[str, Any]:
    try:
        return get_engine(engine_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Engine not found") from exc


@app.get("/engines/{engine_id}/install-preview")
def engine_install_preview(engine_id: str) -> dict[str, Any]:
    try:
        return installation_preview(engine_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Engine not found") from exc


@app.get("/engines/{engine_id}/download-check")
def engine_download_check(engine_id: str) -> dict[str, Any]:
    try:
        result = validate_model_source(engine_id)
        if result.get("has_model") and not result.get("reachable"):
            raise HTTPException(status_code=424, detail=result)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Engine not found") from exc


@app.post("/engines/{engine_id}/install")
def install_engine(engine_id: str, request: EngineInstallRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    try:
        preview = installation_preview(engine_id)
        if request.dry_run:
            return {"status": "preview", "preview": preview}
        state = queue_install(engine_id, repair=request.repair)
        engine = get_engine(engine_id)
        missing_credentials = [
            credential.get("id")
            for credential in engine.get("credentials", [])
            if credential.get("required") and not request.credentials.get(str(credential.get("id")))
        ]
        if missing_credentials:
            raise ValueError(f"Required credentials missing: {', '.join(str(item) for item in missing_credentials)}")
        background_tasks.add_task(run_install, engine_id, request.repair, request.credentials)
        return {"status": state["status"], "engine_id": engine_id, "preview": preview}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Engine not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/voicebox/status")
def voicebox_status() -> dict[str, Any]:
    return voicebox_service.status()


@app.post("/voicebox/start")
def voicebox_start() -> dict[str, Any]:
    try:
        return voicebox_service.start()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/voicebox/models")
def voicebox_models() -> dict[str, Any]:
    try:
        return voicebox_service.models()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/voicebox/models/download")
def voicebox_download_model(request: VoiceboxModelRequest) -> dict[str, Any]:
    try:
        return voicebox_service.download_model(request.model_name)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/voicebox/models/download/cancel")
def voicebox_cancel_model(request: VoiceboxModelRequest) -> dict[str, Any]:
    try:
        return voicebox_service.cancel_model_download(request.model_name)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/voicebox/profiles")
def voicebox_profiles() -> dict[str, Any]:
    return {"profiles": local_voice_service.merged_profiles()}


@app.post("/voicebox/profiles")
def voicebox_create_profile(request: VoiceboxProfileRequest) -> dict[str, Any]:
    try:
        return local_voice_service.create_profile(request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/voicebox/profiles/presets/{engine}")
def voicebox_preset_voices(engine: str) -> dict[str, Any]:
    try:
        return voicebox_service.preset_voices(engine)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/voicebox/profiles/{profile_id}/samples")
def voicebox_add_profile_sample(profile_id: str, request: VoiceboxSampleRequest) -> dict[str, Any]:
    try:
        if local_voice_service.get(profile_id):
            return local_voice_service.add_sample(profile_id, request.path, request.reference_text)
        return voicebox_service.add_profile_sample(profile_id, request.path, request.reference_text)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/voicebox/profiles/{profile_id}/samples/recording")
def voicebox_add_recorded_profile_sample(profile_id: str, request: VoiceboxRecordedSampleRequest) -> dict[str, Any]:
    try:
        if "," not in request.data_url:
            raise ValueError("Invalid recording payload")
        header, encoded = request.data_url.split(",", 1)
        if not header.startswith("data:audio/"):
            raise ValueError("Only audio recordings are accepted")
        payload = base64.b64decode(encoded, validate=True)
        if not payload or len(payload) > 50 * 1024 * 1024:
            raise ValueError("Recording must be between 1 byte and 50 MB")
        extension = Path(request.file_name).suffix.lower()
        if extension not in {".webm", ".wav", ".ogg", ".mp3", ".m4a"}:
            extension = ".webm"
        capture_dir = PATHS.data / "voice-captures"
        capture_dir.mkdir(parents=True, exist_ok=True)
        capture_path = capture_dir / f"{uuid4().hex}{extension}"
        capture_path.write_bytes(payload)
        if local_voice_service.get(profile_id):
            return local_voice_service.add_sample(profile_id, str(capture_path), request.reference_text)
        return voicebox_service.add_profile_sample(profile_id, str(capture_path), request.reference_text)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/voicebox/generate")
def voicebox_generate(request: VoiceboxGenerateRequest) -> dict[str, Any]:
    payload = request.model_dump(exclude_none=True)
    try:
        payload["profile_id"] = local_voice_service.ensure_remote_profile(request.profile_id)
        return voicebox_service.generate(payload)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/voicebox/generate/{generation_id}/status")
def voicebox_generation_status(generation_id: str) -> dict[str, Any]:
    try:
        return voicebox_service.generation_status(generation_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/voicebox/generations/{generation_id}")
def voicebox_generation(generation_id: str) -> dict[str, Any]:
    try:
        return voicebox_service.generation(generation_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/voicebox/generations/{generation_id}/audio")
def voicebox_generation_audio(generation_id: str) -> FileResponse:
    try:
        generation = voicebox_service.generation(generation_id)
        audio_path = voicebox_service.resolve_audio_path(generation.get("audio_path"))
        if not audio_path or not audio_path.is_file():
            raise RuntimeError("Generation audio is not available")
        return FileResponse(audio_path, media_type="audio/wav", filename=audio_path.name)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/projects/{project_id}/waveform")
def get_project_waveform(project_id: str) -> dict[str, Any]:
    """Return cached waveform peaks without re-probing the source video."""
    project_dir = _require_project_dir(project_id)
    manifest_path = project_dir / "analysis" / "media_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="No manifest found. Run prepare first.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Corrupt manifest") from exc
    peaks = manifest.get("waveform_peaks", [])
    return {"project_id": project_id, "peaks": peaks, "count": len(peaks)}


@app.get("/projects/{project_id}/export/srt")
def export_srt(project_id: str, lang: str = Query(default="source")) -> PlainTextResponse:
    """
    Export a SubRip (.srt) file from the current analysis state.
    lang=source → sourceText, lang=translated → translatedText, lang=adapted → adaptedText
    """
    project_dir = _require_project_dir(project_id)
    state = _read_or_create_analysis_state(project_dir)
    lines: list[str] = []
    for index, seg in enumerate(state.segments, start=1):
        if lang == "translated":
            text = seg.translatedText or seg.sourceText
        elif lang == "adapted":
            text = seg.adaptedText or seg.translatedText or seg.sourceText
        else:
            text = seg.sourceText
        if not text.strip():
            continue
        lines.append(str(index))
        lines.append(f"{_srt_ts(seg.start)} --> {_srt_ts(seg.end)}")
        lines.append(text.strip())
        lines.append("")
    srt_content = "\n".join(lines)
    return PlainTextResponse(content=srt_content, media_type="text/plain; charset=utf-8")


@app.get("/media/stream")
def stream_media(path: str = Query(...)) -> FileResponse:
    media_path = _validate_video_path(Path(path))
    return FileResponse(
        media_path,
        media_type=_guess_video_media_type(media_path),
        filename=media_path.name,
    )


@app.post("/media/probe", response_model=MediaProbeResponse)
def probe_media(request: MediaProbeRequest) -> MediaProbeResponse:
    return _probe_media_path(Path(request.path))


@app.get("/media/youtube/runtime")
def youtube_runtime() -> dict[str, Any]:
    return {"ready": youtube_service.runtime_ready(), "engine_id": "yt-dlp"}


@app.post("/media/youtube/inspect")
def inspect_youtube(request: YouTubeUrlRequest) -> dict[str, Any]:
    try:
        return youtube_service.inspect(request.url)
    except (RuntimeError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/media/youtube/downloads")
def create_youtube_download(request: YouTubeDownloadRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    try:
        state = youtube_service.start(request.url, request.title)
        background_tasks.add_task(youtube_service.run, state["id"])
        return state
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/media/youtube/downloads/{download_id}")
def youtube_download_status(download_id: str) -> dict[str, Any]:
    try:
        return youtube_service.get(download_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="YouTube download not found") from exc


@app.post("/media/youtube/downloads/{download_id}/cancel")
def cancel_youtube_download(download_id: str) -> dict[str, Any]:
    try:
        return youtube_service.cancel(download_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="YouTube download not found") from exc


@app.get("/rvc/status")
def rvc_runtime_status() -> dict[str, Any]:
    return rvc_service.status()


@app.get("/rvc/models")
def rvc_models() -> dict[str, Any]:
    return {"models": rvc_service.models()}


@app.post("/rvc/models/import")
def import_rvc_model(request: RvcModelImportRequest) -> dict[str, Any]:
    try:
        return rvc_service.import_model(request.model_path, request.index_path, request.name, request.author, request.license, request.authorized)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/rvc/jobs")
def create_rvc_job(request: RvcConversionRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    try:
        state = rvc_service.start(request.source_path, request.model_id, request.pitch, request.f0_method, request.index_rate, request.protect)
        background_tasks.add_task(rvc_service.run, state["id"])
        return state
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/rvc/jobs/{job_id}")
def rvc_job(job_id: str) -> dict[str, Any]:
    try:
        return rvc_service.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RVC job not found") from exc


@app.post("/rvc/jobs/{job_id}/cancel")
def cancel_rvc_job(job_id: str) -> dict[str, Any]:
    try:
        return rvc_service.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RVC job not found") from exc


@app.get("/rvc/jobs/{job_id}/audio")
def rvc_job_audio(job_id: str) -> FileResponse:
    try:
        state = rvc_service.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RVC job not found") from exc
    path = Path(str(state.get("output_path") or "")).resolve()
    output_root = (PATHS.data / "rvc" / "outputs").resolve()
    if state.get("status") != "completed" or not path.is_file() or output_root not in path.parents:
        raise HTTPException(status_code=404, detail="RVC audio is not ready")
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@app.get("/subclean/status")
def subclean_runtime_status() -> dict[str, Any]:
    return subclean_service.status()


@app.post("/subclean/jobs")
def create_subclean_job(request: SubCleanRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
    try:
        state = subclean_service.start(request.source_path, request.mode, request.areas)
        background_tasks.add_task(subclean_service.run, state["id"])
        return state
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/subclean/jobs/{job_id}")
def subclean_job(job_id: str) -> dict[str, Any]:
    try:
        return subclean_service.get(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SubClean job not found") from exc


@app.post("/subclean/jobs/{job_id}/cancel")
def cancel_subclean_job(job_id: str) -> dict[str, Any]:
    try:
        return subclean_service.cancel(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="SubClean job not found") from exc


@app.post("/projects/{project_id}/derived-source", response_model=ProjectRecord)
def apply_project_derived_source(project_id: str, request: ProjectDerivedSourceRequest) -> ProjectRecord:
    project_dir = _require_project_dir(project_id)
    record = _read_project_record(project_dir)
    if not record:
        raise HTTPException(status_code=404, detail="Project not found")
    candidate = Path(request.path).resolve()
    allowed_root = (PATHS.data / "subclean" / "outputs").resolve()
    if not candidate.is_file() or allowed_root not in candidate.parents:
        raise HTTPException(status_code=400, detail="Only a completed SubClean output can become a derived source")
    original = record.original_source_path or record.source_path
    record.original_source_path = original
    record.source_path = str(candidate)
    record.derived_sources.append({"kind": request.kind, "path": str(candidate), "created_at": datetime.now(timezone.utc).isoformat()})
    record.updated_at = datetime.now(timezone.utc).isoformat()
    _write_project_record(project_dir, record)
    return record


@app.post("/projects/{project_id}/restore-source", response_model=ProjectRecord)
def restore_project_original_source(project_id: str) -> ProjectRecord:
    project_dir = _require_project_dir(project_id)
    record = _read_project_record(project_dir)
    if not record:
        raise HTTPException(status_code=404, detail="Project not found")
    if not record.original_source_path:
        raise HTTPException(status_code=409, detail="This project has no derived source to restore")
    original = Path(record.original_source_path).resolve()
    if not original.is_file():
        raise HTTPException(status_code=404, detail="The original source is no longer available")
    record.source_path = str(original)
    record.updated_at = datetime.now(timezone.utc).isoformat()
    _write_project_record(project_dir, record)
    return record


@app.post("/media/prepare", response_model=MediaPrepareResponse)
def prepare_media(request: MediaPrepareRequest) -> MediaPrepareResponse:
    media_path = Path(request.path)
    if not media_path.exists() or not media_path.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")

    media = _probe_media_path(media_path)
    project_id = _make_project_id(request.project_name or media_path.stem)
    project_dir = PROJECTS_ROOT / project_id
    audio_dir = project_dir / "audio"
    analysis_dir = project_dir / "analysis"
    audio_dir.mkdir(parents=True, exist_ok=True)
    analysis_dir.mkdir(parents=True, exist_ok=True)

    audio_path = audio_dir / "source_16k_mono.wav"
    manifest_path = analysis_dir / "media_manifest.json"

    _extract_audio(media_path, audio_path)
    waveform = _build_waveform(audio_path)

    manifest = {
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_video_path": str(media_path),
        "audio_path": str(audio_path),
        "waveform_peaks": waveform,
        "source_language": request.source_language,
        "target_language": request.target_language,
        "media": media.model_dump(mode="json"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_analysis_state(project_dir, _build_initial_analysis_state(project_dir, manifest))
    now = datetime.now(timezone.utc).isoformat()
    _write_project_record(
        project_dir,
        ProjectRecord(
            id=project_id,
            name=request.project_name or media_path.stem,
            status="prepared",
            project_dir=str(project_dir),
            source_path=str(media_path),
            media_manifest_path=str(manifest_path),
            source_language=request.source_language,
            target_language=request.target_language,
            created_at=manifest["created_at"],
            updated_at=now,
        ),
    )

    return MediaPrepareResponse(
        project_id=project_id,
        project_dir=str(project_dir),
        audio_path=str(audio_path),
        manifest_path=str(manifest_path),
        waveform=waveform,
        media=media,
    )


def _probe_media_path(media_path: Path) -> MediaProbeResponse:
    media_path = _validate_video_path(media_path)

    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(media_path),
    ]

    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="ffprobe is not installed") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "ffprobe failed to read this media file"
        raise HTTPException(status_code=422, detail=detail) from exc

    payload = json.loads(completed.stdout)
    media_format: dict[str, Any] = payload.get("format", {})
    streams: list[dict[str, Any]] = payload.get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)

    return MediaProbeResponse(
        path=str(media_path),
        file_name=media_path.name,
        duration_seconds=_to_float(media_format.get("duration")),
        size_bytes=_to_int(media_format.get("size")),
        format_name=media_format.get("format_name"),
        video=_build_video_stream(video_stream) if video_stream else None,
        audio=_build_audio_stream(audio_stream) if audio_stream else None,
    )


def _extract_audio(media_path: Path, audio_path: Path) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(media_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="ffmpeg is not installed") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "ffmpeg failed to extract audio"
        raise HTTPException(status_code=422, detail=detail) from exc


def _build_waveform(audio_path: Path, peak_count: int = 180) -> list[float]:
    with wave.open(str(audio_path), "rb") as wav_file:
        frame_count = wav_file.getnframes()
        sample_width = wav_file.getsampwidth()
        if frame_count <= 0 or sample_width != 2:
            return []

        bucket_size = max(1, frame_count // peak_count)
        peaks: list[float] = []

        while len(peaks) < peak_count:
            frames = wav_file.readframes(bucket_size)
            if not frames:
                break

            samples = array("h")
            samples.frombytes(frames)
            if not samples:
                peaks.append(0)
                continue

            peak = max(abs(sample) for sample in samples) / 32768
            peaks.append(round(min(1, peak), 4))

    return peaks


def _make_project_id(name: str) -> str:
    slug = sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{slug}-{timestamp}"


def _list_project_records() -> list[ProjectRecord]:
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    records = [
        record
        for project_dir in PROJECTS_ROOT.iterdir()
        if project_dir.is_dir() and not project_dir.name.startswith(".")
        for record in [_read_project_record(project_dir)]
        if record is not None
    ]
    return sorted(records, key=lambda record: record.updated_at, reverse=True)


def _require_project_dir(project_id: str) -> Path:
    project_dir = (PROJECTS_ROOT / project_id).resolve()
    if PROJECTS_ROOT.resolve() not in project_dir.parents and project_dir != PROJECTS_ROOT.resolve():
        raise HTTPException(status_code=400, detail="Invalid project id")

    if not project_dir.exists() or not project_dir.is_dir():
        raise HTTPException(status_code=404, detail="Project not found")

    return project_dir


def _require_trash_dir(trash_id: str) -> Path:
    trash_dir = (TRASH_ROOT / trash_id).resolve()
    if TRASH_ROOT.resolve() not in trash_dir.parents:
        raise HTTPException(status_code=400, detail="project.invalid_trash_id")
    if not trash_dir.exists() or not trash_dir.is_dir():
        raise HTTPException(status_code=404, detail="project.trash_not_found")
    return trash_dir


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _read_project_record(project_dir: Path) -> ProjectRecord | None:
    project_file = project_dir / "project.json"
    if project_file.exists():
        try:
            return ProjectRecord.model_validate_json(project_file.read_text(encoding="utf-8"))
        except ValueError:
            return None

    manifest_file = project_dir / "analysis" / "media_manifest.json"
    if not manifest_file.exists():
        return None

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None

    project_id = str(manifest.get("project_id") or project_dir.name)
    created_at = str(manifest.get("created_at") or datetime.fromtimestamp(project_dir.stat().st_ctime, timezone.utc).isoformat())
    return ProjectRecord(
        id=project_id,
        name=project_id.rsplit("-", 2)[0].replace("-", " ").title() or project_id,
        status="prepared",
        project_dir=str(project_dir),
        source_path=manifest.get("source_video_path"),
        media_manifest_path=str(manifest_file),
        created_at=created_at,
        updated_at=created_at,
    )


def _write_project_record(project_dir: Path, record: ProjectRecord) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "project.json").write_text(
        json.dumps(record.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )


def _touch_project_record(project_dir: Path, updated_at: str) -> None:
    record = _read_project_record(project_dir)
    if not record:
        return
    record.updated_at = updated_at
    _write_project_record(project_dir, record)


def _read_or_create_analysis_state(project_dir: Path) -> ProjectAnalysisState:
    state_path = project_dir / "analysis" / "state.json"
    if state_path.exists():
        try:
            state = ProjectAnalysisState.model_validate_json(state_path.read_text(encoding="utf-8"))
            source_language, target_language = _analysis_languages(project_dir, {})
            changed = False
            if not state.source_language and source_language:
                state.source_language = source_language
                changed = True
            if not state.target_language and target_language:
                state.target_language = target_language
                changed = True
            if changed:
                _write_analysis_state(project_dir, state)
            return state
        except ValueError:
            pass

    manifest_path = project_dir / "analysis" / "media_manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}

    state = _build_initial_analysis_state(project_dir, manifest)
    _write_analysis_state(project_dir, state)
    return state


def _write_analysis_state(project_dir: Path, state: ProjectAnalysisState) -> None:
    analysis_dir = project_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "state.json").write_text(
        json.dumps(state.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )


def _build_initial_analysis_state(project_dir: Path, manifest: dict[str, Any]) -> ProjectAnalysisState:
    source_language, target_language = _analysis_languages(project_dir, manifest)
    return ProjectAnalysisState(
        speakers=[],
        segments=[],
        updated_at=datetime.now(timezone.utc).isoformat(),
        source_language=source_language,
        target_language=target_language,
    )


def _analysis_languages(project_dir: Path, manifest: dict[str, Any]) -> tuple[str | None, str | None]:
    source_language = manifest.get("source_language") if isinstance(manifest.get("source_language"), str) else None
    target_language = manifest.get("target_language") if isinstance(manifest.get("target_language"), str) else None

    record = _read_project_record(project_dir)
    if record:
        source_language = source_language or record.source_language
        target_language = target_language or record.target_language

    manifest_path = project_dir / "analysis" / "media_manifest.json"
    if (not source_language or not target_language) and manifest_path.exists():
        try:
            stored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(stored_manifest, dict):
                source_language = source_language or stored_manifest.get("source_language")
                target_language = target_language or stored_manifest.get("target_language")
        except json.JSONDecodeError:
            pass

    return source_language, target_language


def _format_timestamp(seconds: float) -> str:
    milliseconds = int(round((seconds % 1) * 1000))
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    whole_seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _timestamp_seconds(value: str) -> float:
    try:
        parts = [float(part) for part in value.split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        return parts[0]
    except (TypeError, ValueError, IndexError):
        return 0.0


def _srt_ts(timestamp: str) -> str:
    """Convert internal HH:MM:SS.mmm timestamps to SRT format HH:MM:SS,mmm."""
    return timestamp.replace(".", ",") if "." in timestamp else timestamp


def _create_queued_job(project_id: str, job_type: str, timestamp: str, options: dict[str, Any] | None = None) -> JobRecord:
    return JobRecord(
        id=f"{job_type}-{uuid4().hex[:10]}",
        project_id=project_id,
        type=job_type,
        status="queued",
        progress=0,
        message=f"{_job_label(job_type)} queued",
        created_at=timestamp,
        updated_at=timestamp,
        artifacts={},
        options=options or {},
    )


def _execute_project_job(project_id: str, job_id: str, job_type: str, options: dict[str, Any] | None = None) -> None:
    project_dir = PROJECTS_ROOT / project_id
    queued_job = _read_job(project_dir, job_id)
    if not queued_job:
        return

    running_at = datetime.now(timezone.utc).isoformat()
    _write_job(
        project_dir,
        queued_job.model_copy(
            update={
                "status": "running",
                "progress": 8,
                "message": f"{_job_label(job_type)} running",
                "updated_at": running_at,
            }
        )
    )

    try:
        state = _read_or_create_analysis_state(project_dir)
        completed_at = datetime.now(timezone.utc).isoformat()
        def update_progress(progress: int, message: str) -> None:
            current = _read_job(project_dir, job_id) or queued_job
            _write_job(project_dir, current.model_copy(update={
                "status": "running",
                "progress": max(0, min(99, progress)),
                "message": message,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }))

        result = _run_stub_job(project_id, project_dir, state, job_type, completed_at, options or {}, update_progress, lambda: job_id in EXPORT_CANCEL_REQUESTS)
        final_job = result.model_copy(
            update={
                "id": queued_job.id,
                "created_at": queued_job.created_at,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        _write_job(project_dir, final_job)
        _touch_project_record(project_dir, final_job.updated_at)
    except export_service.ExportCancelled:
        cancelled_at = datetime.now(timezone.utc).isoformat()
        current = _read_job(project_dir, job_id) or queued_job
        _write_job(project_dir, current.model_copy(update={
            "status": "cancelled",
            "progress": current.progress,
            "message": "Export cancelled",
            "updated_at": cancelled_at,
        }))
        _touch_project_record(project_dir, cancelled_at)
    except Exception as exc:
        failed_at = datetime.now(timezone.utc).isoformat()
        _write_job(
            project_dir,
            queued_job.model_copy(
                update={
                    "status": "failed",
                    "progress": 100,
                    "message": f"{_job_label(job_type)} failed: {exc}",
                    "updated_at": failed_at,
                    "artifacts": {},
                }
            )
        )
        _touch_project_record(project_dir, failed_at)
    finally:
        EXPORT_CANCEL_REQUESTS.discard(job_id)


def _job_label(job_type: str) -> str:
    return {
        "asr": "ASR",
        "diarization": "Diarization",
        "translation": "Translation",
        "voice_generation": "Voice generation",
        "preview": "Preview",
        "export": "Export",
    }.get(job_type, job_type)


def _run_faster_whisper_asr(project_dir: Path, state: ProjectAnalysisState, timestamp: str) -> dict[str, Any]:
    asr_manifest = project_dir / "analysis" / "asr_manifest.json"
    asr_manifest.parent.mkdir(parents=True, exist_ok=True)
    engine = next(
        (
            candidate
            for candidate in list_engines()
            if candidate.get("category") == "asr"
            and candidate.get("installation", {}).get("status") == "ready"
        ),
        None,
    )
    if not engine:
        asr_manifest.write_text(
            json.dumps(
                {
                    "created_at": timestamp,
                    "status": "engine_required",
                    "message": "Install an ASR engine from the engine catalog before running transcription.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "status": "skipped",
            "message": "ASR unavailable: install a transcription engine from Engines",
            "artifacts": {"asr_manifest": str(asr_manifest)},
        }

    engine_id = str(engine["id"])
    model_manifest = PATHS.models / engine_id / "model.json"
    python_executable = PATHS.environments / engine_id / "venv" / "Scripts" / "python.exe"
    worker_path = PATHS.installers / "run-asr.py"
    if not model_manifest.exists() or not python_executable.exists() or not worker_path.exists():
        raise RuntimeError(f"The {engine.get('display_name', engine_id)} installation is incomplete. Use Repair in Engines.")

    manifest = _read_media_manifest(project_dir)
    audio_path = Path(str(manifest.get("audio_path", "")))
    if not audio_path.exists():
        raise RuntimeError("Prepared audio file is missing. Run Analyze again.")
    source_language = _normalise_asr_language(state.source_language)
    duration_seconds = _manifest_duration_seconds(manifest)
    worker_output = project_dir / "analysis" / "asr_worker_output.json"
    devices = ["cuda", "cpu"] if _tool_available("nvidia-smi") else ["cpu"]
    worker_error = ""
    for device in devices:
        command = [
            str(python_executable), str(worker_path),
            "--manifest", str(model_manifest),
            "--audio", str(audio_path),
            "--output", str(worker_output),
            "--device", device,
        ]
        if source_language:
            command.extend(["--language", source_language])
        completed = subprocess.run(command, cwd=PATHS.workspace, capture_output=True, text=True, check=False)
        if completed.returncode == 0 and worker_output.exists():
            break
        worker_error = (completed.stderr or completed.stdout or f"worker exited with code {completed.returncode}").strip()
    else:
        raise RuntimeError(f"ASR worker failed: {worker_error[-1200:]}")

    result_payload = json.loads(worker_output.read_text(encoding="utf-8"))
    raw_segments = result_payload.get("segments", [])

    transcript_segments: list[dict[str, Any]] = []
    next_segments: list[SegmentRecord] = []
    speaker = state.speakers[0] if state.speakers else SpeakerRecord(
        name="Speaker 1",
        role="ASR — diarisation à effectuer",
        duration="--",
        color="#39c6bd",
        level=68,
    )

    for index, result in enumerate(raw_segments, start=1):
        text = str(result.get("text", "")).strip()
        if not text:
            continue
        start_seconds = max(0.0, float(result.get("start", 0)))
        end_seconds = max(start_seconds + 0.1, float(result.get("end", start_seconds + 0.1)))
        transcript_segments.append(
            {
                "id": f"asr-{index:03d}",
                "start": start_seconds,
                "end": end_seconds,
                "text": text,
                "words": result.get("words", []),
            }
        )
        next_segments.append(
            SegmentRecord(
                id=f"asr-{index:03d}",
                left=round((start_seconds / duration_seconds) * 100, 2),
                width=round(max(2.5, ((end_seconds - start_seconds) / duration_seconds) * 100), 2),
                lane=(index - 1) % 3,
                speaker=speaker.name,
                label=f"ASR {index}",
                color=speaker.color,
                start=_format_timestamp(start_seconds),
                end=_format_timestamp(end_seconds),
                sourceText=text,
                translatedText="",
                adaptedText="",
                emotion="Neutral",
                intensity=35,
                pace=100,
                fit=0,
                locked=False,
            )
        )

    if next_segments:
        if not state.speakers:
            state.speakers = [speaker]
        state.segments = next_segments
        state.updated_at = timestamp
        _write_analysis_state(project_dir, state)

    asr_manifest.write_text(
        json.dumps(
            {
                "created_at": timestamp,
                "status": "completed" if next_segments else "empty",
                "engine_id": engine_id,
                "model_path": str(model_manifest),
                "device": result_payload.get("device"),
                "compute_type": result_payload.get("compute_type"),
                "language": result_payload.get("language", source_language),
                "duration": result_payload.get("duration"),
                "segments": transcript_segments,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    status = "completed" if next_segments else "skipped"
    message = f"ASR completed with {engine.get('display_name', engine_id)}: {len(next_segments)} segments" if next_segments else "ASR found no speech segments"
    return {
        "status": status,
        "message": message,
        "artifacts": {
            "asr_manifest": str(asr_manifest),
            "transcript": str(project_dir / "analysis" / "state.json"),
        },
    }


def _read_media_manifest(project_dir: Path) -> dict[str, Any]:
    manifest_path = project_dir / "analysis" / "media_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def _manifest_duration_seconds(manifest: dict[str, Any]) -> float:
    media = manifest.get("media") if isinstance(manifest.get("media"), dict) else {}
    return _to_float(media.get("duration_seconds")) or 90.0


def _normalise_asr_language(language: str | None) -> str | None:
    if not language:
        return None
    value = _normalise_tts_language(language)
    return {"jp": "ja", "zh": "zh", "gb": "en"}.get(value, value)


def _run_stub_job(
    project_id: str,
    project_dir: Path,
    state: ProjectAnalysisState,
    job_type: str,
    timestamp: str,
    options: dict[str, Any] | None = None,
    on_progress: Any | None = None,
    is_cancelled: Any | None = None,
) -> JobRecord:
    artifacts: dict[str, str] = {}
    message = "Job queued"
    job_status = "completed"
    progress = 100

    if job_type == "asr":
        asr_result = _run_faster_whisper_asr(project_dir, state, timestamp)
        artifacts.update(asr_result["artifacts"])
        message = asr_result["message"]
        job_status = asr_result["status"]
    elif job_type == "diarization":
        engine = next((item for item in list_engines() if item.get("category") == "diarization" and item.get("installation", {}).get("status") == "ready"), None)
        job_status = "skipped"
        message = f"{engine.get('display_name')} is installed; pipeline adapter is not enabled yet" if engine else "Install a diarization engine from Engines"
    elif job_type == "translation":
        engine = next((item for item in list_engines() if item.get("category") == "translation" and item.get("installation", {}).get("status") == "ready"), None)
        if not engine:
            job_status = "skipped"
            message = "Install a quantized translation model from Engines"
        elif not state.segments:
            job_status = "skipped"
            message = "Transcribe the source before translation"
        else:
            engine_id = str(engine["id"])
            manifest_path = PATHS.models / engine_id / "model.json"
            python_executable = PATHS.environments / engine_id / "venv" / "Scripts" / "python.exe"
            worker_path = Path(__file__).with_name("translation_worker.py")
            payload = {
                "source_language": state.source_language or "en",
                "target_language": state.target_language or "fr",
                "segments": [{"id": segment.id, "text": segment.sourceText} for segment in state.segments],
            }
            completed = subprocess.run(
                [str(python_executable), str(worker_path), str(manifest_path)],
                input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True, check=False,
                cwd=PATHS.workspace, timeout=3600,
            )
            if completed.returncode != 0:
                raise RuntimeError(f"Local translation failed: {(completed.stderr or completed.stdout)[-1200:]}")
            translated_payload = json.loads(completed.stdout)
            by_id = {str(item.get("id")): str(item.get("text", "")) for item in translated_payload.get("translations", [])}
            for segment in state.segments:
                if segment.id in by_id:
                    segment.translatedText = by_id[segment.id]
            state.updated_at = timestamp
            _write_analysis_state(project_dir, state)
            artifacts["analysis_state"] = str(project_dir / "analysis" / "state.json")
            message = f"Translated {len(by_id)} segments with {engine.get('display_name', engine_id)}"
    elif job_type == "voice_generation":
        audio_dir = project_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        runtime = voicebox_service.status()
        if not runtime.get("runtime_ready"):
            return JobRecord(
                id=f"{job_type}-{uuid4().hex[:10]}", project_id=project_id, type=job_type,
                status="skipped", progress=100, message="Install Voicebox Runtime from Engines before generating voices",
                created_at=timestamp, updated_at=timestamp, artifacts={},
            )
        if not runtime.get("online"):
            runtime = voicebox_service.start()
        if not runtime.get("online"):
            raise RuntimeError("Voicebox Runtime did not become available")

        target_language = _normalise_tts_language(state.target_language)
        speaker_by_name = {speaker.name: speaker for speaker in state.speakers}

        generated_segments: list[dict[str, Any]] = []
        failed_segments: list[dict[str, str]] = []
        for segment in state.segments:
            text = _segment_tts_text(segment)
            if not text:
                continue
            speaker = speaker_by_name.get(segment.speaker)
            if not speaker or not speaker.voice_profile_id:
                failed_segments.append({"segment_id": segment.id, "reason": f"No Voicebox profile assigned to {segment.speaker}"})
                continue

            payload: dict[str, Any] = {
                "profile_id": speaker.voice_profile_id,
                "text": text,
                "language": target_language,
                "max_chunk_chars": 800,
                "crossfade_ms": 50,
                "normalize": True,
            }
            if speaker.voice_engine:
                payload["engine"] = speaker.voice_engine
            if speaker.voice_model:
                payload["model_size"] = speaker.voice_model
            if speaker.voice_instruct:
                payload["instruct"] = speaker.voice_instruct
            if speaker.effects_chain:
                payload["effects_chain"] = speaker.effects_chain

            try:
                payload["profile_id"] = local_voice_service.ensure_remote_profile(str(payload["profile_id"]))
                queued = voicebox_service.generate(payload)
                generation_id = str(queued.get("id", ""))
                if not generation_id:
                    raise RuntimeError("Voicebox did not return a generation id")
                generation = queued
                deadline = time.monotonic() + 1200
                while generation.get("status") in {"queued", "loading_model", "generating"}:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Voicebox generation timed out after 20 minutes")
                    time.sleep(0.75)
                    generation = voicebox_service.generation(generation_id)
                if generation.get("status") != "completed":
                    raise RuntimeError(str(generation.get("error") or f"Voicebox status: {generation.get('status')}"))
                source_audio = voicebox_service.resolve_audio_path(generation.get("audio_path"))
                if not source_audio or not source_audio.exists():
                    raise RuntimeError("Voicebox completed without a readable audio file")
                output_path = audio_dir / f"{segment.id}.wav"
                shutil.copy2(source_audio, output_path)
                generated_segments.append(
                    {
                        "segment_id": segment.id,
                        "path": str(output_path),
                        "voicebox_generation_id": generation_id,
                        "profile_id": speaker.voice_profile_id,
                        "engine": generation.get("engine") or speaker.voice_engine or "profile-default",
                        "model_size": generation.get("model_size") or speaker.voice_model,
                        "language": target_language,
                    }
                )
            except RuntimeError as exc:
                failed_segments.append(
                    {
                        "segment_id": segment.id,
                        "reason": str(exc)[-600:],
                    }
                )

        attempted_count = len(generated_segments) + len(failed_segments)
        if generated_segments and not failed_segments:
            status = "completed"
        elif generated_segments:
            status = "partial"
        elif attempted_count:
            status = "failed"
        else:
            status = "skipped"
        voice_manifest = audio_dir / "voice_manifest.json"
        voice_manifest.write_text(
            json.dumps(
                {
                    "created_at": timestamp,
                    "status": status,
                    "runtime": "voicebox",
                    "language": target_language,
                    "segments": generated_segments,
                    "failed_segments": failed_segments,
                    "note": f"Generated {len(generated_segments)} of {attempted_count} voice segments.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        artifacts["voice_manifest"] = str(voice_manifest)
        message = f"Voice generation {status}: {len(generated_segments)} generated, {len(failed_segments)} failed"
        job_status = status
    elif job_type == "preview":
        job_status = "skipped"
        message = "Generate at least one voice take before rendering a preview"
    elif job_type == "export":
        record = _read_project_record(project_dir)
        voice_manifest_path = project_dir / "audio" / "voice_manifest.json"
        if not record or not record.source_path or not Path(record.source_path).exists():
            raise RuntimeError("Source video is missing")
        if not voice_manifest_path.exists():
            raise RuntimeError("Generate the voice takes before export")
        voice_manifest = json.loads(voice_manifest_path.read_text(encoding="utf-8"))
        generated = voice_manifest.get("segments", []) if isinstance(voice_manifest, dict) else []
        segment_by_id = {segment.id: segment for segment in state.segments}
        takes = [take for take in generated if Path(str(take.get("path", ""))).exists() and take.get("segment_id") in segment_by_id]
        if not takes:
            raise RuntimeError("No generated voice take is available for export")
        manifest = _read_media_manifest(project_dir)
        duration_seconds = _manifest_duration_seconds(manifest)
        segment_times = {
            segment.id: (_timestamp_seconds(segment.start), _timestamp_seconds(segment.end))
            for segment in state.segments
        }
        PATHS.exports.mkdir(parents=True, exist_ok=True)
        artifacts.update(export_service.execute_export(
            project_id=project_id,
            project_name=record.name,
            source_path=Path(record.source_path),
            output_root=PATHS.exports,
            options=options or {},
            takes=takes,
            segment_times=segment_times,
            duration_seconds=duration_seconds,
            on_progress=on_progress or (lambda _progress, _message: None),
            is_cancelled=is_cancelled or (lambda: False),
        ))
        produced = len([key for key in artifacts if key == "video" or key.startswith("short_") or key == "audio"])
        message = f"Export completed: {produced} deliverable{'s' if produced != 1 else ''}"

    return JobRecord(
        id=f"{job_type}-{uuid4().hex[:10]}",
        project_id=project_id,
        type=job_type,
        status=job_status,
        progress=progress,
        message=message,
        created_at=timestamp,
        updated_at=timestamp,
        artifacts=artifacts,
        options=options or {},
    )


def _list_jobs(project_dir: Path) -> list[JobRecord]:
    jobs_dir = project_dir / "jobs"
    if not jobs_dir.exists():
        return []

    jobs: list[JobRecord] = []
    for job_file in jobs_dir.glob("*.json"):
        try:
            jobs.append(JobRecord.model_validate_json(job_file.read_text(encoding="utf-8")))
        except ValueError:
            continue

    return sorted(jobs, key=lambda job: job.updated_at, reverse=True)


def _read_job(project_dir: Path, job_id: str) -> JobRecord | None:
    job_file = project_dir / "jobs" / f"{job_id}.json"
    if not job_file.exists():
        return None
    try:
        return JobRecord.model_validate_json(job_file.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _write_job(project_dir: Path, job: JobRecord) -> None:
    jobs_dir = project_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / f"{job.id}.json").write_text(
        json.dumps(job.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )


def _tool_available(name: str) -> bool:
    if name == "nvidia-smi":
        return _nvidia_status() is not None
    try:
        subprocess.run(
            [name, "-version"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _cpu_name() -> str:
    """Return a human-readable CPU name without keeping machine-specific state."""
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                candidate = " ".join(str(value).split())
                if candidate:
                    return candidate
        except (ImportError, OSError):
            pass
    return platform.processor() or platform.machine()


def _runtime_hardware() -> dict[str, Any]:
    mem = _memory_status()
    cuda = _nvidia_status()
    return {
        "os": platform.system(),
        "os_detail": platform.platform(),
        "python": platform.python_version(),
        "cpu": _cpu_name(),
        "cpu_threads": os.cpu_count() or 1,
        "ram_gb": round(mem["total_bytes"] / 1_073_741_824, 1) if mem else None,
        "ram_available_gb": round(mem["available_bytes"] / 1_073_741_824, 1) if mem else None,
        "ram_load_percent": mem.get("load_percent") if mem else None,
        "memory": mem,
        "cuda": cuda,
    }


def _memory_status() -> dict[str, int] | None:
    """Cross-platform RAM info — uses psutil."""
    if _PSUTIL_OK:
        vm = psutil.virtual_memory()
        return {
            "total_bytes": vm.total,
            "available_bytes": vm.available,
            "load_percent": int(vm.percent),
        }
    return None


def _nvidia_status() -> dict[str, Any] | None:
    """Query GPU info via nvidia-smi (NVIDIA) or rocm-smi (AMD) if available."""
    # Try NVIDIA first
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free,driver_version",
                "--format=csv,noheader",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
        first_gpu = completed.stdout.strip().splitlines()[0] if completed.stdout.strip() else ""
        parts = [p.strip() for p in first_gpu.split(",")]
        cuda_version = None
        try:
            details = subprocess.run(
                ["nvidia-smi"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
            )
            match = search(r"CUDA Version:\s*([0-9.]+)", details.stdout)
            cuda_version = match.group(1) if match else None
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ):
            pass
        if len(parts) >= 4:
            # Parse VRAM number from e.g. "6144 MiB"
            def _parse_mib(s: str) -> int | None:
                try:
                    return int(s.split()[0])
                except (IndexError, ValueError):
                    return None

            return {
                "vendor": "nvidia",
                "name": parts[0],
                "vram_total_mb": _parse_mib(parts[1]),
                "vram_free_mb": _parse_mib(parts[2]),
                "driver_version": parts[3],
                "cuda_version": cuda_version,
            }
        if first_gpu:
            return {"vendor": "nvidia", "raw": first_gpu}
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    # Try AMD ROCm
    try:
        completed = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--csv"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
        if completed.stdout.strip():
            return {"vendor": "amd_rocm", "raw": completed.stdout.strip().splitlines()[0]}
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass

    return None


def _select_performance_profile(hw: dict[str, Any]) -> dict[str, Any]:
    """
    Automatically select the best performance profile for the detected hardware.
    Rules:
      - CUDA + VRAM >= 8 GB  → gpu_quality
      - CUDA + VRAM >= 4 GB  → gpu_balanced
      - CUDA + VRAM < 4 GB   → gpu_light
      - RAM >= 16 GB, no GPU → cpu_balanced
      - RAM >= 8 GB,  no GPU → cpu_fallback
      - else                 → cpu_minimal
    """
    cuda = hw.get("cuda")
    ram_gb: float = hw.get("ram_gb") or 0.0
    vram_mb: int = (cuda or {}).get("vram_total_mb") or 0
    has_cuda = cuda is not None

    if has_cuda and vram_mb >= 8000:
        profile_id = "gpu_quality"
        label = "GPU Quality"
        reason = f"{cuda['name']} with {vram_mb} MB VRAM — full pipeline enabled."
        allowed_jobs = ["asr", "diarization", "translation", "voice_generation", "preview", "export"]
        recommended_engines = ["faster_whisper_small_medium", "pyannote_community_1", "argos_translate", "llama_cpp_small_llm", "piper_tts", "kokoro_82m_onnx", "supertonic_3", "f5_tts"]
    elif has_cuda and vram_mb >= 4000:
        profile_id = "gpu_balanced"
        label = "GPU Balanced"
        reason = f"{cuda['name']} with {vram_mb} MB VRAM — chunked pipeline, one model at a time."
        allowed_jobs = ["asr", "diarization", "translation", "voice_generation", "preview", "export"]
        recommended_engines = ["faster_whisper_small_medium", "argos_translate", "piper_tts", "kokoro_82m_onnx", "supertonic_3"]
    elif has_cuda:
        profile_id = "gpu_light"
        label = "GPU Light"
        reason = f"{cuda['name']} detected but only {vram_mb} MB VRAM — use small models."
        allowed_jobs = ["asr", "translation", "voice_generation", "export"]
        recommended_engines = ["whisper_cpp_tiny_base", "argos_translate", "piper_tts", "supertonic_3"]
    elif ram_gb >= 16:
        profile_id = "cpu_balanced"
        label = "CPU Balanced"
        reason = f"No GPU. {ram_gb} GB RAM — medium CPU models usable."
        allowed_jobs = ["asr", "translation", "voice_generation", "export"]
        recommended_engines = ["whisper_cpp_tiny_base", "argos_translate", "piper_tts", "kokoro_82m_onnx", "supertonic_3"]
    elif ram_gb >= 6:
        profile_id = "cpu_fallback"
        label = "CPU Fallback"
        reason = f"No GPU. {ram_gb} GB RAM — tiny models only, slower processing."
        allowed_jobs = ["asr", "translation", "export"]
        recommended_engines = ["whisper_cpp_tiny_base", "argos_translate", "piper_tts", "supertonic_3"]
    else:
        profile_id = "cpu_minimal"
        label = "CPU Minimal"
        reason = f"Very limited hardware ({ram_gb} GB RAM, no GPU). Only media prep and manual editing."
        allowed_jobs = ["export"]
        recommended_engines = ["ffmpeg"]

    return {
        "profile": profile_id,
        "label": label,
        "reason": reason,
        "allowed_jobs": allowed_jobs,
        "recommended_engines": recommended_engines,
        "hardware_summary": {
            "ram_gb": ram_gb,
            "cpu_threads": hw.get("cpu_threads"),
            "gpu": cuda.get("name") if cuda else None,
            "vram_mb": vram_mb if has_cuda else None,
            "cuda": has_cuda,
        },
    }


def _select_tts_engine(profile: dict[str, Any]) -> str:
    env_engine = os.getenv("DUB_TTS_ENGINE", "").strip().lower()
    if env_engine in {"edge", "kokoro", "supertonic"}:
        return env_engine

    profile_id = profile.get("profile")
    recommended = set(profile.get("recommended_engines") or [])
    if profile_id in {"gpu_balanced", "gpu_quality"} and "kokoro_82m_onnx" in recommended:
        return "kokoro"
    return "edge"


def _normalise_tts_language(language: str | None) -> str:
    if not language:
        return "en"
    value = language.strip().lower()
    aliases = {
        "english": "en",
        "anglais": "en",
        "french": "fr",
        "francais": "fr",
        "français": "fr",
        "japanese": "jp",
        "japonais": "jp",
        "ja": "jp",
        "chinese": "zh",
        "chinois": "zh",
        "mandarin": "zh",
        "spanish": "es",
        "espagnol": "es",
    }
    if value in aliases:
        return aliases[value]
    if "-" in value:
        value = value.split("-", 1)[0]
    return value[:2] if value else "en"


def _segment_tts_text(segment: SegmentRecord) -> str:
    for value in (segment.adaptedText, segment.translatedText, segment.sourceText):
        text = value.strip()
        if not text:
            continue
        if text.lower() in {"pending transcription.", "translation pending engine integration.", "adaptation pending timing engine."}:
            continue
        return text
    return ""


def _validate_video_path(media_path: Path) -> Path:
    resolved = media_path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Video file not found")

    if resolved.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported video file extension")

    return resolved


def _guess_video_media_type(media_path: Path) -> str:
    extension = media_path.suffix.lower()
    if extension in {".mp4", ".m4v"}:
        return "video/mp4"
    if extension == ".webm":
        return "video/webm"
    if extension == ".mov":
        return "video/quicktime"
    if extension == ".mkv":
        return "video/x-matroska"
    if extension == ".avi":
        return "video/x-msvideo"
    return "application/octet-stream"


def _build_video_stream(stream: dict[str, Any]) -> VideoStream:
    return VideoStream(
        codec=stream.get("codec_name"),
        width=_to_int(stream.get("width")),
        height=_to_int(stream.get("height")),
        fps=_parse_fps(stream.get("avg_frame_rate") or stream.get("r_frame_rate")),
    )


def _build_audio_stream(stream: dict[str, Any]) -> AudioStream:
    return AudioStream(
        codec=stream.get("codec_name"),
        channels=_to_int(stream.get("channels")),
        sample_rate=_to_int(stream.get("sample_rate")),
    )


def _parse_fps(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None

    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_float = _to_float(denominator)
        if not denominator_float:
            return None
        return round((_to_float(numerator) or 0) / denominator_float, 3)

    return _to_float(value)


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
