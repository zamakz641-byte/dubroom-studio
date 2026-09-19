import base64
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import threading
import time
import wave
from array import array
from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
from re import search, sub
from typing import Any, Callable

try:
    import psutil
    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import AliasChoices, BaseModel, Field

try:
    from .config import API_HOST, API_PORT, PATHS, load_runtime_config
    from .engine_service import cancel_install, engine_runtime_id, get_engine, installation_preview, list_engines, load_registry, queue_install, run_install, validate_model_source
    from .open_source_policy import is_open_source_engine, require_open_source_engine
    from .segmentation import resegment_for_dubbing
    from . import activity_service, audio_preservation_service, diarization_service, export_service, library_service, local_voice_service, resource_scheduler, rvc_service, subclean_service, native_tts_service, sync_service, terminology_service, transcript_exchange_service, voice_library_service, youtube_service
except ImportError:
    from config import API_HOST, API_PORT, PATHS, load_runtime_config
    from engine_service import cancel_install, engine_runtime_id, get_engine, installation_preview, list_engines, load_registry, queue_install, run_install, validate_model_source
    from open_source_policy import is_open_source_engine, require_open_source_engine
    from segmentation import resegment_for_dubbing
    import activity_service, audio_preservation_service, diarization_service, export_service, library_service, local_voice_service, resource_scheduler, rvc_service, subclean_service, native_tts_service, sync_service, terminology_service, transcript_exchange_service, voice_library_service, youtube_service


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
    output_aspect: str | None = None
    content_type: str = "other"
    dubbing_mode: str = "single"


class YouTubeUrlRequest(BaseModel):
    url: str


class YouTubeDownloadRequest(BaseModel):
    url: str
    title: str | None = None
    media_type: str = "video"
    start_seconds: float | None = Field(default=None, ge=0)
    end_seconds: float | None = Field(default=None, gt=0)


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
    output_aspect: str | None = None
    performance_profile: str | None = None
    content_type: str = "other"
    dubbing_mode: str = "single"


class LibraryAssetRequest(BaseModel):
    kind: str
    name: str
    path: str | None = None
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class TerminologyAnalyseRequest(BaseModel):
    project_id: str
    source_language: str = "en"
    target_language: str = "fr"
    research: bool = False
    research_limit: int = 5


class TerminologyTermRequest(BaseModel):
    source_term: str
    source_language: str = "en"
    target_language: str = "fr"
    project_id: str | None = None
    scope: str | None = None
    category: str = ""
    definition: str = ""
    preferred_translation: str = ""
    alternatives: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    status: str = "suggested"
    confidence: float = 0
    suspicion_score: int = 0
    occurrences: int = 0
    examples: list[str] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)


class TerminologyApproveRequest(BaseModel):
    preferred_translation: str
    apply_globally: bool = False


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
    output_aspect: str | None = None
    performance_profile: str | None = None
    content_type: str = "other"
    dubbing_mode: str = "single"
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
    character_id: str | None = None
    voice_key: str | None = None
    detected_sex: str | None = None
    detected_age_group: str | None = None
    character_id: str | None = None
    character_name: str | None = None
    character_role: str | None = None
    sex: str | None = None
    age_group: str | None = None
    importance: str | None = None
    dedicated_voice: bool | None = None
    voice_archetype: str | None = None
    render_voice_key: str | None = None
    casting_confidence: float | None = None
    casting_status: str | None = None
    identity_locked: bool | None = None
    voice_locked: bool | None = None


class SegmentRecord(BaseModel):
    id: str
    left: float
    width: float
    lane: int
    speaker: str
    acousticSpeaker: str | None = None
    characterId: str | None = None
    characterName: str | None = None
    characterRole: str | None = None
    characterConfidence: float | None = None
    sourceSegmentId: str | None = None
    speechType: str | None = None
    voiceKey: str | None = None
    label: str
    color: str
    start: str
    end: str
    sourceText: str
    subtitleEvidence: list[dict[str, Any]] = Field(
        default_factory=list,
        validation_alias=AliasChoices("subtitleEvidence", "subtitle_evidence"),
    )
    translatedText: str
    adaptedText: str
    rawTranslation: str = ""
    fidelityScore: int | None = None
    fidelityIssues: list[dict[str, Any]] = Field(default_factory=list)
    voiceAudioReady: bool = False
    voiceAudioDuration: float | None = None
    voiceAudioEngine: str | None = None
    voiceAudioStatus: str | None = None
    # Legacy compatibility field. Strict synchronization ignores this flag:
    # every visible transcript segment with text receives its own TTS file.
    voiceSkip: bool = False
    emotion: str
    omnivoiceTag: str | None = None
    omnivoiceEvents: list[dict[str, str]] = Field(default_factory=list)
    intensity: int
    pace: int
    fit: int
    locked: bool


class MixSettings(BaseModel):
    voice_volume: float = 1.0
    original_volume: float = 0.0
    music_volume: float = 0.85
    voice_muted: bool = False
    original_muted: bool = False
    music_muted: bool = False
    normalize: bool = True
    ducking: bool = False
    music_path: str | None = None


class ProjectAnalysisState(BaseModel):
    speakers: list[SpeakerRecord]
    segments: list[SegmentRecord]
    updated_at: str
    source_language: str | None = None
    target_language: str | None = None
    revision: int = 0
    narrative_profile: str = "natural_recap"
    narrative_instructions: str = ""
    subtitle_evidence_revision: str | None = None
    last_operation: str | None = None
    mix: MixSettings = Field(default_factory=MixSettings)


class JobCreateRequest(BaseModel):
    type: str
    options: dict[str, Any] = Field(default_factory=dict)


class ExportPlanRequest(BaseModel):
    options: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float | None = None


class TranscriptExportRequest(BaseModel):
    format: str = "manifest"
    chunk_size: int = Field(default=60, ge=10, le=120)


class TranscriptImportRequest(BaseModel):
    path: str
    revision: int | None = None


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


class TtsGenerateRequest(BaseModel):
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


class TtsProfileRequest(BaseModel):
    name: str
    description: str | None = None
    language: str = "en"
    voice_type: str = "cloned"
    preset_engine: str | None = None
    preset_voice_id: str | None = None
    design_prompt: str | None = None
    design_seed: int = 42
    design_reference_text: str | None = None
    default_engine: str | None = None
    personality: str | None = None
    gender: str = "unspecified"
    age_group: str = "adult"
    primary_role: str = "other"
    roles: list[str] = Field(default_factory=list)
    usage_scope: str = "both"
    voice_archetype: str | None = None
    casting_tags: list[str] = Field(default_factory=list)
    enabled: bool = True
    locked: bool = False


class TtsDesignPrepareRequest(BaseModel):
    reference_text: str | None = None
    warm_prompt_cache: bool = True


class TtsSampleRequest(BaseModel):
    path: str
    reference_text: str = ""


class TtsRecordedSampleRequest(BaseModel):
    data_url: str
    reference_text: str = ""
    file_name: str = "voice-sample.webm"


class VoiceLibraryBuildRequest(BaseModel):
    voices: list[str] = Field(default_factory=list)
    full_tests: bool = False
    regenerate: bool = False
    tests_only: bool = False


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
PROJECT_CANCEL_REQUESTS: set[str] = set()
ANALYSIS_STATE_LOCK = threading.RLock()

app = FastAPI(title="Dub Studio Local API", version="0.1.0")


@app.on_event("startup")
def reconcile_interrupted_activity() -> None:
    activity_service.reconcile_interrupted()
    _reconcile_interrupted_project_jobs()

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

    tts = native_tts_service.status()
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
        "resources": resource_scheduler.status(),
        "pipeline": {
            "probe": "ready" if ffprobe_ready else "not-installed",
            "prepare_audio": "ready" if ffmpeg_ready else "not-installed",
            "subtitle_cleanup": "ready" if subclean["runtime_ready"] else "not-installed",
            "asr": capability("asr"),
            "diarization": capability("diarization"),
            "translation": capability("translation"),
            "tts": "ready" if tts["installed_count"] else "available" if tts["ready"] else "not-installed",
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


@app.get("/terminology/terms")
def terminology_terms(
    project_id: str | None = None,
    source_language: str | None = None,
    target_language: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    return {
        "terms": terminology_service.list_terms(
            project_id, source_language, target_language, status
        )
    }


@app.post("/terminology/terms")
def terminology_create_term(request: TerminologyTermRequest) -> dict[str, Any]:
    try:
        return terminology_service.upsert_term(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/terminology/terms/{term_id}/approve")
def terminology_approve_term(term_id: int, request: TerminologyApproveRequest) -> dict[str, Any]:
    try:
        return terminology_service.approve_term(
            term_id, request.preferred_translation, request.apply_globally
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/terminology/terms/{term_id}/research")
def terminology_research_term(term_id: int) -> dict[str, Any]:
    try:
        return terminology_service.research_term(term_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/terminology/analyse")
def terminology_analyse(request: TerminologyAnalyseRequest) -> dict[str, Any]:
    project_dir = _require_project_dir(request.project_id)
    state = _read_or_create_analysis_state(project_dir)
    report = terminology_service.analyse_transcript(
        request.project_id,
        request.source_language,
        request.target_language,
        [{"id": segment.id, "text": segment.sourceText} for segment in state.segments],
    )
    if request.research:
        report["research"] = terminology_service.research_candidates(
            report, max(1, min(20, request.research_limit))
        )
    return report


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
        output_aspect=request.output_aspect,
        performance_profile=request.performance_profile,
        content_type=request.content_type,
        dubbing_mode=request.dubbing_mode,
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


@app.post("/projects/{project_id}/audio/separate", response_model=JobRecord)
def separate_project_audio(
    project_id: str,
    background_tasks: BackgroundTasks,
) -> JobRecord:
    return create_project_job(
        project_id,
        JobCreateRequest(type="audio_separation"),
        background_tasks,
    )


@app.get("/projects/{project_id}/audio/separation")
def get_project_audio_separation(project_id: str) -> dict[str, Any]:
    project_dir = _require_project_dir(project_id)
    return audio_preservation_service.status(project_dir)


@app.get("/projects/{project_id}/diarization")
def get_project_diarization(project_id: str) -> dict[str, Any]:
    project_dir = _require_project_dir(project_id)
    return diarization_service.status(project_dir)


@app.post("/projects/{project_id}/diarize", response_model=JobRecord)
def diarize_project(
    project_id: str,
    background_tasks: BackgroundTasks,
) -> JobRecord:
    return create_project_job(
        project_id,
        JobCreateRequest(type="diarization"),
        background_tasks,
    )


@app.get("/projects/{project_id}/audio/preservation/{track}")
def get_project_preserved_audio(project_id: str, track: str) -> FileResponse:
    project_dir = _require_project_dir(project_id)
    audio_path = audio_preservation_service.track_path(project_dir, track)
    if not audio_path:
        raise HTTPException(status_code=404, detail="Audio Preservation track not ready")
    return FileResponse(
        audio_path,
        media_type="audio/wav",
        filename=audio_path.name,
    )


@app.get("/projects/{project_id}/audio/{segment_id}")
def get_project_voice_audio(project_id: str, segment_id: str) -> FileResponse:
    project_dir = _require_project_dir(project_id)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", segment_id):
        raise HTTPException(status_code=400, detail="Invalid segment id")
    audio_root = (project_dir / "audio").resolve()
    audio_path = (audio_root / f"{segment_id}.wav").resolve()
    if audio_root not in audio_path.parents or not audio_path.is_file():
        raise HTTPException(status_code=404, detail="Generated voice audio not found")
    return FileResponse(
        audio_path,
        media_type="audio/wav",
        filename=f"{segment_id}.wav",
    )


@app.put("/projects/{project_id}/analysis/state", response_model=ProjectAnalysisState)
def update_project_analysis(project_id: str, state: ProjectAnalysisState) -> ProjectAnalysisState:
    with ANALYSIS_STATE_LOCK:
        return _update_project_analysis_locked(project_id, state)


@app.post("/projects/{project_id}/transcript/export")
def export_project_transcript(
    project_id: str,
    request: TranscriptExportRequest,
) -> dict[str, Any]:
    project_dir = _require_project_dir(project_id)
    state = _read_or_create_analysis_state(project_dir)
    if not state.segments:
        raise HTTPException(status_code=409, detail="Run transcription before exporting")
    project = _read_project_record(project_dir)
    state_payload = state.model_dump(mode="json")
    state_payload["dubbing_mode"] = (
        project.dubbing_mode if project else "single"
    )
    payload = transcript_exchange_service.build_exchange_payload(
        project_id=project_id,
        project_name=(project.name if project else project_id),
        state=state_payload,
        project_dir=project_dir,
    )
    try:
        return transcript_exchange_service.write_export(
            project_dir=project_dir,
            payload=payload,
            export_format=request.format,
            chunk_size=request.chunk_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/projects/{project_id}/transcript/import/preview")
def preview_project_transcript_import(
    project_id: str,
    request: TranscriptImportRequest,
) -> dict[str, Any]:
    project_dir = _require_project_dir(project_id)
    state = _read_or_create_analysis_state(project_dir)
    project = _read_project_record(project_dir)
    try:
        parsed = transcript_exchange_service.parse_import_file(
            Path(request.path)
        )
        preview = transcript_exchange_service.preview_import(
            state=state.model_dump(mode="json"),
            parsed=parsed,
            require_complete_multispeaker=bool(
                project and project.dubbing_mode == "multi"
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return preview


@app.post("/projects/{project_id}/transcript/import")
def import_project_transcript(
    project_id: str,
    request: TranscriptImportRequest,
) -> dict[str, Any]:
    project_dir = _require_project_dir(project_id)
    project = _read_project_record(project_dir)
    source_path = Path(request.path)
    try:
        parsed = transcript_exchange_service.parse_import_file(source_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with ANALYSIS_STATE_LOCK:
        state = _read_or_create_analysis_state_locked(project_dir)
        if request.revision is not None and request.revision != state.revision:
            raise HTTPException(
                status_code=409,
                detail="analysis_conflict: the transcript changed after the import preview",
            )
        preview = transcript_exchange_service.preview_import(
            state=state.model_dump(mode="json"),
            parsed=parsed,
            require_complete_multispeaker=bool(
                project and project.dubbing_mode == "multi"
            ),
        )
        if not preview["can_apply"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "The translated script did not pass import validation",
                    "preview": preview,
                },
            )
        imported_entries = {
            str(entry["id"]): entry for entry in preview["entries"]
        }
        registry_by_character = {
            str(item.get("character_id") or "").strip().upper(): item
            for item in (preview.get("character_registry") or [])
            if isinstance(item, dict) and str(item.get("character_id") or "").strip()
        }
        if any(entry.get("voice_units") for entry in imported_entries.values()):
            expanded_segments, imported_entries = _expand_v3_voice_units(
                state.segments,
                imported_entries,
            )
            state.segments = expanded_segments
        # CASTING_R4_PATCH2B_APPLY
        from . import casting_r4_service as _casting_r4_service
        r4_casting = _casting_r4_service.apply_casting(
            project_dir=project_dir,
            state=state,
            preview=preview,
        )
        imported_by_id = {
            segment_id: str(entry["target_text"]).strip()
            for segment_id, entry in imported_entries.items()
        }
        existing_speakers = {speaker.name: speaker for speaker in state.speakers}
        character_source_speakers: dict[str, set[str]] = {}
        character_metadata: dict[str, dict[str, Any]] = {}
        for segment in state.segments:
            entry = imported_entries.get(segment.id)
            character_id = str((entry or {}).get("character_id") or "")
            if not character_id:
                continue
            acoustic_name = str((entry or {}).get("temporary_cluster") or segment.acousticSpeaker or segment.speaker)
            character_source_speakers.setdefault(character_id, set()).add(acoustic_name)
            if character_id not in character_metadata:
                character_metadata[character_id] = {
                    **registry_by_character.get(character_id, {}),
                    **(entry or {}),
                }
        display_by_character: dict[str, str] = {}
        used_display_names: set[str] = set()
        for character_id, metadata in character_metadata.items():
            base_name = str(metadata.get("character_name") or character_id).strip()
            display_name = base_name
            if display_name.casefold() in used_display_names:
                display_name = f"{base_name} ({character_id})"
            display_by_character[character_id] = display_name
            used_display_names.add(display_name.casefold())
        changed_ids: list[str] = []
        for segment in state.segments:
            entry = imported_entries.get(segment.id)
            translated = imported_by_id.get(segment.id)
            if translated is None:
                continue
            incoming_character_id = str((entry or {}).get("character_id") or "")
            character_changed = bool(
                incoming_character_id
                and (
                    segment.characterId != incoming_character_id
                    or segment.speaker != display_by_character[incoming_character_id]
                )
            )
            if segment.translatedText.strip() != translated or character_changed:
                changed_ids.append(segment.id)
            segment.rawTranslation = translated
            segment.translatedText = translated
            segment.adaptedText = translated
            segment.fidelityScore = None
            segment.fidelityIssues = []
            segment.voiceAudioReady = False
            segment.voiceAudioDuration = None
            segment.voiceAudioEngine = None
            segment.voiceAudioStatus = None
            segment.voiceSkip = False
            segment.emotion = str((entry or {}).get("emotion") or segment.emotion or "neutral")
            segment.intensity = int((entry or {}).get("emotion_intensity") or 0)
            segment.omnivoiceTag = str((entry or {}).get("omnivoice_tag") or "").strip() or None
            segment.omnivoiceEvents = list((entry or {}).get("vocal_events") or [])
            segment.sourceSegmentId = str((entry or {}).get("source_segment_id") or "").strip() or segment.sourceSegmentId
            segment.speechType = str((entry or {}).get("speech_type") or "").strip() or segment.speechType
            segment.voiceKey = str((entry or {}).get("voice_key") or "").strip() or segment.voiceKey
            character_id = incoming_character_id
            if character_id:
                segment.acousticSpeaker = str(
                    (entry or {}).get("temporary_cluster")
                    or segment.acousticSpeaker
                    or segment.speaker
                )
                segment.characterId = character_id
                segment.characterName = str((entry or {}).get("character_name") or "").strip() or None
                segment.characterRole = str((entry or {}).get("character_role") or "").strip() or None
                segment.characterConfidence = (entry or {}).get("character_confidence")
                segment.speaker = display_by_character[character_id]
                segment.label = display_by_character[character_id]
        if character_metadata:
            colors = ["#8B5CF6", "#06B6D4", "#F59E0B", "#EC4899", "#10B981", "#3B82F6"]
            detected_character_traits: dict[str, dict[str, Any]] = {
                character_id: {
                    "sex": str(item.get("sex") or "uncertain").strip().lower(),
                    "age_group": str(item.get("age_group") or "unknown").strip().lower(),
                    "confidence": float(item.get("confidence") or 0),
                }
                for character_id, item in registry_by_character.items()
            }
            for section in preview.get("speaker_sections") or []:
                if not isinstance(section, dict):
                    continue
                for detected in section.get("detected_speakers") or []:
                    if not isinstance(detected, dict):
                        continue
                    detected_character_id = str(
                        detected.get("character_id") or ""
                    ).strip().upper()
                    if not detected_character_id:
                        continue
                    try:
                        detected_confidence = float(detected.get("confidence") or 0)
                    except (TypeError, ValueError):
                        detected_confidence = 0.0
                    previous = detected_character_traits.get(detected_character_id)
                    if previous is None or detected_confidence >= previous["confidence"]:
                        detected_character_traits[detected_character_id] = {
                            "sex": str(detected.get("sex") or "uncertain").strip().lower(),
                            "age_group": str(
                                detected.get("age_group") or "unknown"
                            ).strip().lower(),
                            "confidence": detected_confidence,
                        }
            character_durations: dict[str, float] = {}
            for segment in state.segments:
                if not segment.characterId:
                    continue
                character_durations[segment.characterId] = (
                    character_durations.get(segment.characterId, 0.0)
                    + transcript_exchange_service.segment_duration(
                        segment.model_dump(mode="json")
                    )
                )
            signature_cast = _signature_voice_profiles()
            resolved_speakers: list[SpeakerRecord] = []
            claimed_signature_keys: set[str] = set()
            claimed_profile_ids: set[str] = set()
            cast_profile_by_character: dict[str, str] = {}

            # Lock the four signature roles first. Then reserve gender-matched
            # stock voices before assigning uncertain extras, so a late male
            # character never receives a female voice merely because the male
            # presets were consumed by earlier unknown speakers.
            for character_id, metadata in character_metadata.items():
                voice_key = str(
                    metadata.get("voice_key")
                    or ("narrator" if character_id == "NARRATOR" else "supporting")
                ).strip().lower()
                if voice_key in claimed_signature_keys:
                    continue
                signature_profile_id = signature_cast.get(voice_key)
                if signature_profile_id:
                    cast_profile_by_character[character_id] = signature_profile_id
                    claimed_signature_keys.add(voice_key)
                    claimed_profile_ids.add(signature_profile_id)

            for known_sex_only in (True, False):
                for index, (character_id, metadata) in enumerate(character_metadata.items()):
                    if character_id in cast_profile_by_character:
                        continue
                    detected_traits = detected_character_traits.get(character_id) or {}
                    declared_sex = str(detected_traits.get("sex") or "uncertain")
                    if (declared_sex in {"male", "female"}) != known_sex_only:
                        continue
                    voice_key = str(
                        metadata.get("voice_key")
                        or ("narrator" if character_id == "NARRATOR" else "supporting")
                    ).strip().lower()
                    profile_id = _curated_multispeaker_profile_id(
                        voice_key=voice_key,
                        sex=declared_sex,
                        age_group=str(detected_traits.get("age_group") or "unknown"),
                        ordinal=index,
                        used_profile_ids=claimed_profile_ids,
                    )
                    cast_profile_by_character[character_id] = profile_id
                    claimed_profile_ids.add(profile_id)

            for index, (character_id, metadata) in enumerate(character_metadata.items()):
                source_names = character_source_speakers.get(character_id) or set()
                preserved = existing_speakers.get(next(iter(source_names))) if len(source_names) == 1 else None
                total_seconds = max(0, round(character_durations.get(character_id, 0.0)))
                minutes, seconds = divmod(total_seconds, 60)
                duration_label = f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"
                detected_traits = detected_character_traits.get(character_id) or {}
                voice_key = str(
                    metadata.get("voice_key")
                    or ("narrator" if character_id == "NARRATOR" else "supporting")
                ).strip().lower()
                curated_profile_id = cast_profile_by_character.get(character_id)
                resolved_speakers.append(
                    SpeakerRecord(
                        name=display_by_character[character_id],
                        role=str(metadata.get("character_role") or "Character").strip(),
                        duration=duration_label,
                        color=(preserved.color if preserved else colors[index % len(colors)]),
                        level=(preserved.level if preserved else 82),
                        voice_profile_id=(
                            preserved.voice_profile_id
                            if preserved and preserved.voice_profile_id
                            else curated_profile_id
                        ),
                        voice_engine=(
                            preserved.voice_engine
                            if preserved and preserved.voice_engine
                            else ("tts-omnivoice-hq" if curated_profile_id else None)
                        ),
                        voice_model=(preserved.voice_model if preserved else None),
                        voice_instruct=(preserved.voice_instruct if preserved else None),
                        effects_chain=(list(preserved.effects_chain) if preserved else []),
                        character_id=character_id,
                        voice_key=voice_key,
                        detected_sex=str(detected_traits.get("sex") or "uncertain"),
                        detected_age_group=str(
                            detected_traits.get("age_group") or "unknown"
                        ),
                    )
                )
            state.speakers = resolved_speakers
        state.updated_at = datetime.now(timezone.utc).isoformat()
        state.last_operation = (
            "external_translation_and_speaker_resolution"
            if character_metadata
            else "external_translation_import"
        )
        _write_analysis_state_locked(project_dir, state)
        _sync_project_languages(project_dir, state)

        if character_metadata:
            resolution_path = project_dir / "analysis" / "speaker-resolution.json"
            resolution_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "resolved_at": state.updated_at,
                        "resolver": "translation_gpt",
                        "speaker_sections": preview.get("speaker_sections") or [],
                        "characters": [
                            {
                                "character_id": character_id,
                                "display_name": display_by_character[character_id],
                                "role": str(metadata.get("character_role") or ""),
                                "voice_key": str(
                                    metadata.get("voice_key")
                                    or ("narrator" if character_id == "NARRATOR" else "supporting")
                                ),
                                "sex": str(
                                    (detected_character_traits.get(character_id) or {}).get("sex")
                                    or "uncertain"
                                ),
                                "age_group": str(
                                    (detected_character_traits.get(character_id) or {}).get("age_group")
                                    or "unknown"
                                ),
                                "temporary_clusters": sorted(character_source_speakers.get(character_id) or []),
                            }
                            for character_id, metadata in character_metadata.items()
                        ],
                        "segments": [
                            {
                                "id": segment.id,
                                "temporary_cluster": segment.acousticSpeaker,
                                "character_id": segment.characterId,
                                "character_name": segment.characterName,
                                "confidence": segment.characterConfidence,
                                "emotion": segment.emotion,
                                "emotion_intensity": segment.intensity,
                                "omnivoice_tag": segment.omnivoiceTag,
                            }
                            for segment in state.segments
                            if segment.characterId
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        # The imported text is now the source of truth for TTS. A previous
        # voice_script.json may contain an older timing-adapted translation and
        # would otherwise silently override the text visible in the interface.
        if changed_ids:
            (project_dir / "analysis" / "voice_script.json").unlink(missing_ok=True)
            _mark_voice_manifest_stale(
                project_dir,
                reason="The imported translation changed after voice generation",
                changed_segment_ids=changed_ids,
            )

    audit_path = transcript_exchange_service.write_import_audit(
        project_dir=project_dir,
        source_path=source_path,
        preview=preview,
    )
    return {
        "state": state.model_dump(mode="json"),
        "preview": {
            key: value
            for key, value in preview.items()
            if key != "entries"
        },
        "changed_ids": changed_ids,
        "audit_path": str(audit_path.resolve()),
        "next_stage": "voice_generation",
    }


def _update_project_analysis_locked(
    project_id: str,
    state: ProjectAnalysisState,
) -> ProjectAnalysisState:
    project_dir = _require_project_dir(project_id)
    existing = _read_or_create_analysis_state(project_dir)
    if state.revision != existing.revision:
        raise HTTPException(
            status_code=409,
            detail="analysis_conflict: a newer transcription or translation is available",
        )
    if existing.segments and not state.segments:
        raise HTTPException(
            status_code=409,
            detail="analysis_conflict: the visible script cannot be replaced by an empty state",
        )
    state.source_language = state.source_language or existing.source_language
    state.target_language = state.target_language or existing.target_language
    existing_by_id = {segment.id: segment for segment in existing.segments}
    if state.source_language and state.target_language:
        for segment in state.segments:
            previous = existing_by_id.get(segment.id)
            if (
                previous
                and segment.translatedText.strip()
                and segment.translatedText.strip() != previous.translatedText.strip()
            ):
                terminology_service.remember_approved_translation(
                    project_id,
                    state.source_language,
                    state.target_language,
                    segment.sourceText,
                    segment.translatedText,
                )
    state.updated_at = datetime.now(timezone.utc).isoformat()
    state.last_operation = "manual_edit"
    _write_analysis_state(project_dir, state)
    _sync_project_languages(project_dir, state)
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
    if job_type not in {"audio_separation", "asr", "diarization", "translation", "voice_generation", "preview", "export"}:
        raise HTTPException(status_code=400, detail="Unsupported job type")
    project_record = _read_project_record(project_dir)
    if (
        job_type == "diarization"
        and project_record
        and project_record.dubbing_mode != "multi"
    ):
        raise HTTPException(
            status_code=409,
            detail="Speaker detection is only available for multi-speaker projects",
        )
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
    PROJECT_CANCEL_REQUESTS.add(job_id)
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


@app.get("/tts/status")
def tts_status() -> dict[str, Any]:
    return native_tts_service.status()



@app.get("/tts/models")
def tts_models() -> dict[str, Any]:
    return native_tts_service.models()



@app.get("/tts/profiles")
def tts_profiles() -> dict[str, Any]:
    return {"profiles": native_tts_service.profiles()}


@app.get("/tts/voice-library")
def tts_voice_library() -> dict[str, Any]:
    return voice_library_service.catalog(native_tts_service.models()["models"])


@app.post("/tts/voice-library/omnivoice/build")
def tts_build_omnivoice_library(request: VoiceLibraryBuildRequest) -> dict[str, Any]:
    try:
        return voice_library_service.start_build(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/tts/voice-library/omnivoice/cancel")
def tts_cancel_omnivoice_library() -> dict[str, Any]:
    return voice_library_service.cancel_build()


@app.post("/tts/profiles")
def tts_create_profile(request: TtsProfileRequest) -> dict[str, Any]:
    try:
        return native_tts_service.create_profile(request.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/tts/profiles/{profile_id}/prepare-design")
def tts_prepare_designed_profile(
    profile_id: str,
    request: TtsDesignPrepareRequest = TtsDesignPrepareRequest(),
) -> dict[str, Any]:
    try:
        return native_tts_service.prepare_designed_profile(
            profile_id,
            reference_text=request.reference_text,
            warm_prompt_cache=request.warm_prompt_cache,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/tts/profiles/{profile_id}/regenerate-design")
def tts_regenerate_designed_profile(
    profile_id: str,
    request: TtsDesignPrepareRequest = TtsDesignPrepareRequest(),
) -> dict[str, Any]:
    try:
        return native_tts_service.regenerate_designed_profile(
            profile_id,
            reference_text=request.reference_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/tts/profiles/presets/{engine}")
def tts_preset_voices(engine: str) -> dict[str, Any]:
    try:
        return native_tts_service.preset_voices(engine)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/tts/profiles/{profile_id}/samples")
def tts_add_profile_sample(profile_id: str, request: TtsSampleRequest) -> dict[str, Any]:
    try:
        return native_tts_service.add_profile_sample(profile_id, request.path, request.reference_text)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/tts/profiles/{profile_id}/samples/recording")
def tts_add_recorded_profile_sample(profile_id: str, request: TtsRecordedSampleRequest) -> dict[str, Any]:
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
        return native_tts_service.add_profile_sample(profile_id, str(capture_path), request.reference_text)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/tts/generate")
def tts_generate(request: TtsGenerateRequest) -> dict[str, Any]:
    payload = request.model_dump(exclude_none=True)
    try:
        return native_tts_service.generate(payload)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/tts/generate/{generation_id}/status")
def tts_generation_status(generation_id: str) -> dict[str, Any]:
    try:
        return native_tts_service.generation_status(generation_id)
    except (RuntimeError, KeyError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/tts/generations")
def tts_generations(profile_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    return {"generations": native_tts_service.generations(profile_id, limit)}


@app.get("/tts/generations/{generation_id}")
def tts_generation(generation_id: str) -> dict[str, Any]:
    try:
        return native_tts_service.generation(generation_id)
    except (RuntimeError, KeyError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/tts/generations/{generation_id}/audio")
def tts_generation_audio(generation_id: str) -> FileResponse:
    try:
        generation = native_tts_service.generation(generation_id)
        audio_path = native_tts_service.resolve_audio_path(generation.get("audio_path"))
        if not audio_path or not audio_path.is_file():
            raise RuntimeError("Generation audio is not available")
        return FileResponse(audio_path, media_type="audio/wav", filename=audio_path.name)
    except (RuntimeError, KeyError) as exc:
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
        state = youtube_service.start(
            request.url,
            request.title,
            media_type=request.media_type,
            start_seconds=request.start_seconds,
            end_seconds=request.end_seconds,
        )
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
    target_language = str(request.target_language or "").strip().lower()
    if not target_language:
        raise HTTPException(status_code=422, detail="A target dubbing language is required")
    source_language = str(request.source_language or "").strip().lower() or None
    if source_language == "auto":
        source_language = None
    output_aspect = str(request.output_aspect or "source").strip().lower()
    if output_aspect not in {"source", "16:9", "9:16", "1:1", "4:5"}:
        raise HTTPException(status_code=422, detail="Unsupported project output aspect ratio")
    content_type = str(request.content_type or "other").strip().lower()
    if content_type not in {"anime", "manga_recap", "manhwa_recap", "live_action", "gameplay", "podcast", "other"}:
        raise HTTPException(status_code=422, detail="Unsupported project video type")
    dubbing_mode = str(request.dubbing_mode or "single").strip().lower()
    if dubbing_mode not in {"single", "multi"}:
        raise HTTPException(status_code=422, detail="Unsupported dubbing mode")

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
        "source_language": source_language,
        "target_language": target_language,
        "output_aspect": output_aspect,
        "content_type": content_type,
        "dubbing_mode": dubbing_mode,
        "media": media.model_dump(mode="json"),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    _write_analysis_state(
        project_dir,
        _build_initial_analysis_state(project_dir, manifest),
        allow_empty=True,
    )
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
            source_language=source_language,
            target_language=target_language,
            output_aspect=output_aspect,
            content_type=content_type,
            dubbing_mode=dubbing_mode,
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
    ffprobe = _resolve_system_tool("ffprobe")
    if not ffprobe:
        raise HTTPException(status_code=500, detail="ffprobe is not installed or not visible to DubRoom")

    command = [
        ffprobe,
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
    ffmpeg = _resolve_system_tool("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=500, detail="ffmpeg is not installed or not visible to DubRoom")
    command = [
        ffmpeg,
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


def _sync_project_languages(project_dir: Path, state: ProjectAnalysisState) -> None:
    record = _read_project_record(project_dir)
    if not record:
        return
    record.source_language = state.source_language
    record.target_language = state.target_language
    record.updated_at = state.updated_at
    _write_project_record(project_dir, record)


def _read_or_create_analysis_state(project_dir: Path) -> ProjectAnalysisState:
    with ANALYSIS_STATE_LOCK:
        return _read_or_create_analysis_state_locked(project_dir)


def _read_or_create_analysis_state_locked(project_dir: Path) -> ProjectAnalysisState:
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
            if not state.segments:
                recovered = _recover_analysis_from_artifacts(project_dir, state)
                if recovered:
                    _write_analysis_state(project_dir, recovered)
                    return recovered
            if changed:
                _write_analysis_state(project_dir, state)
            return state
        except ValueError:
            pass

    history_dir = project_dir / "analysis" / "history"
    if history_dir.is_dir():
        fallback_state: ProjectAnalysisState | None = None
        for snapshot in sorted(history_dir.glob("state-r*.json"), reverse=True):
            try:
                state = ProjectAnalysisState.model_validate_json(
                    snapshot.read_text(encoding="utf-8")
                )
                if fallback_state is None:
                    fallback_state = state
                if state.segments:
                    _write_analysis_state(project_dir, state, preserve_current=False)
                    return state
            except (OSError, ValueError):
                continue
        if fallback_state is not None:
            recovered = _recover_analysis_from_artifacts(project_dir, fallback_state)
            if recovered:
                _write_analysis_state(project_dir, recovered, preserve_current=False)
                return recovered
            _write_analysis_state(
                project_dir,
                fallback_state,
                preserve_current=False,
                allow_empty=True,
            )
            return fallback_state

    manifest_path = project_dir / "analysis" / "media_manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}

    state = _build_initial_analysis_state(project_dir, manifest)
    recovered = _recover_analysis_from_artifacts(project_dir, state)
    if recovered:
        _write_analysis_state(project_dir, recovered, preserve_current=False)
        return recovered
    _write_analysis_state(project_dir, state, allow_empty=True)
    return state


def _write_analysis_state(
    project_dir: Path,
    state: ProjectAnalysisState,
    *,
    preserve_current: bool = True,
    allow_empty: bool = False,
) -> None:
    with ANALYSIS_STATE_LOCK:
        _write_analysis_state_locked(
            project_dir,
            state,
            preserve_current=preserve_current,
            allow_empty=allow_empty,
        )


def _write_analysis_state_locked(
    project_dir: Path,
    state: ProjectAnalysisState,
    *,
    preserve_current: bool = True,
    allow_empty: bool = False,
) -> None:
    analysis_dir = project_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    state_path = analysis_dir / "state.json"
    previous_revision = 0
    if state_path.is_file():
        try:
            previous_payload = json.loads(state_path.read_text(encoding="utf-8"))
            previous_revision = max(0, int(previous_payload.get("revision") or 0))
        except (OSError, ValueError, json.JSONDecodeError):
            previous_payload = None
        if (
            not allow_empty
            and not state.segments
            and isinstance(previous_payload, dict)
            and isinstance(previous_payload.get("segments"), list)
            and previous_payload["segments"]
        ):
            raise ValueError(
                "analysis_conflict: refusing to overwrite a populated script with an empty state"
            )
        if preserve_current and isinstance(previous_payload, dict):
            history_dir = analysis_dir / "history"
            history_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = history_dir / f"state-r{previous_revision:08d}.json"
            if not snapshot_path.exists():
                snapshot_path.write_text(
                    json.dumps(previous_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            snapshots = sorted(
                history_dir.glob("state-r*.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for obsolete in snapshots[20:]:
                obsolete.unlink(missing_ok=True)
    state.revision = max(previous_revision, int(state.revision or 0)) + 1
    temporary_path = analysis_dir / f".state-{uuid4().hex}.tmp"
    temporary_path.write_text(
        json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary_path, state_path)
    history_dir = analysis_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    committed_snapshot = history_dir / f"state-r{state.revision:08d}.json"
    committed_snapshot.write_text(
        json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    snapshots = sorted(
        history_dir.glob("state-r*.json"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for obsolete in snapshots[20:]:
        obsolete.unlink(missing_ok=True)


def _build_initial_analysis_state(project_dir: Path, manifest: dict[str, Any]) -> ProjectAnalysisState:
    source_language, target_language = _analysis_languages(project_dir, manifest)
    return ProjectAnalysisState(
        speakers=[],
        segments=[],
        updated_at=datetime.now(timezone.utc).isoformat(),
        source_language=source_language,
        target_language=target_language,
        revision=0,
        narrative_profile="natural_recap",
        narrative_instructions="",
        last_operation="project_created",
    )


def _recover_analysis_from_artifacts(
    project_dir: Path,
    state: ProjectAnalysisState,
) -> ProjectAnalysisState | None:
    """Rebuild a lost visible state from completed ASR/translation artifacts."""
    analysis_dir = project_dir / "analysis"
    asr_path = analysis_dir / "asr_manifest.json"
    if not asr_path.is_file():
        return None
    try:
        asr_payload = json.loads(asr_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw_segments = asr_payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        return None
    duration = max(
        0.1,
        _to_float(asr_payload.get("duration"))
        or max((_to_float(item.get("end")) for item in raw_segments if isinstance(item, dict)), default=90),
    )
    speaker = (
        state.speakers[0]
        if state.speakers
        else SpeakerRecord(
            name="Speaker 1",
            role="ASR — diarisation à effectuer",
            duration="--",
            color="#39c6bd",
            level=68,
        )
    )
    recovered_segments: list[SegmentRecord] = []
    for index, item in enumerate(raw_segments, start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start_seconds = max(0.0, _to_float(item.get("start")))
        end_seconds = max(start_seconds + 0.1, _to_float(item.get("end")))
        recovered_segments.append(
            SegmentRecord(
                id=str(item.get("id") or f"asr-{index:03d}"),
                left=round((start_seconds / duration) * 100, 2),
                width=round(max(0.1, ((end_seconds - start_seconds) / duration) * 100), 2),
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
    if not recovered_segments:
        return None

    translation_path = analysis_dir / "translation_final.json"
    if not translation_path.is_file():
        candidates = sorted(
            analysis_dir.glob("translation_post_edit_*.output.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        translation_path = candidates[0] if candidates else translation_path
    if translation_path.is_file():
        try:
            translation_payload = json.loads(translation_path.read_text(encoding="utf-8"))
            translation_rows = translation_payload.get("translations", [])
            by_id = {
                str(item.get("id")): item
                for item in translation_rows
                if isinstance(item, dict) and item.get("id") is not None
            }
            for segment in recovered_segments:
                result = by_id.get(segment.id)
                if not result:
                    continue
                segment.translatedText = str(result.get("text") or "")
                segment.rawTranslation = str(result.get("raw_text") or "")
                segment.adaptedText = str(result.get("adapted_text") or "")
                score = result.get("fidelity_score")
                segment.fidelityScore = int(score) if score is not None else None
                segment.fidelityIssues = _normalise_fidelity_issues(
                    result.get("fidelity_issues")
                )
        except (OSError, ValueError, json.JSONDecodeError):
            pass

    state.segments = recovered_segments
    state.speakers = state.speakers or [speaker]
    state.source_language = state.source_language or str(asr_payload.get("language") or "") or None
    state.updated_at = datetime.now(timezone.utc).isoformat()
    state.last_operation = "artifact_recovery"
    return state


def _normalise_fidelity_issues(value: Any) -> list[dict[str, Any]]:
    """Keep worker/model audit output compatible with the persisted API schema."""
    if not isinstance(value, list):
        return []
    normalised: list[dict[str, Any]] = []
    for issue in value:
        if isinstance(issue, dict):
            issue_type = str(issue.get("type") or "model_review").strip()
            detail = str(issue.get("detail") or "").strip()
            normalised.append(
                {
                    "type": issue_type or "model_review",
                    **({"detail": detail} if detail else {}),
                }
            )
        elif isinstance(issue, str) and issue.strip():
            normalised.append(
                {"type": "model_review", "detail": issue.strip()}
            )
    return normalised


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


def _translation_library_glossary(source_language: str | None, target_language: str | None) -> dict[str, str]:
    """Load reusable source→target terminology rules from the Library."""
    glossary: dict[str, str] = {}
    for asset in library_service.list_assets("glossaries"):
        metadata = asset.get("metadata") if isinstance(asset.get("metadata"), dict) else {}
        asset_source = str(metadata.get("source_language") or "").lower()
        asset_target = str(metadata.get("target_language") or "").lower()
        if asset_source and source_language and asset_source != source_language.lower():
            continue
        if asset_target and target_language and asset_target != target_language.lower():
            continue
        content = str(asset.get("content") or "").strip()
        if not content:
            continue
        try:
            structured = json.loads(content)
        except json.JSONDecodeError:
            structured = None
        if isinstance(structured, dict):
            for source_term, target_term in structured.items():
                source_text = str(source_term or "").strip()
                target_text = str(target_term or "").strip()
                if source_text and target_text:
                    glossary[source_text] = target_text
            continue
        for line in content.splitlines():
            clean_line = line.strip()
            if not clean_line or clean_line.startswith("#"):
                continue
            match = re.match(r"^(.+?)\s*(?:=>|->|=|\t)\s*(.+)$", clean_line)
            if not match:
                continue
            source_text, target_text = (part.strip() for part in match.groups())
            if source_text and target_text:
                glossary[source_text] = target_text
    return glossary


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


def _run_translation_worker_stage(
    project_dir: Path,
    engine: dict[str, Any],
    payload: dict[str, Any],
    stage_name: str,
    progress_start: int,
    progress_end: int,
    on_progress: Any = None,
    is_cancelled: Any = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    engine_id = str(engine["id"])
    manifest_path = PATHS.models / engine_id / "model.json"
    python_executable = PATHS.environments / engine_runtime_id(engine) / "venv" / "Scripts" / "python.exe"
    worker_path = Path(__file__).with_name("translation_worker.py")
    token = uuid4().hex[:10]
    prefix = f"translation_{stage_name}_{token}"
    input_path = project_dir / "analysis" / f"{prefix}.input.json"
    output_path = project_dir / "analysis" / f"{prefix}.output.json"
    progress_path = project_dir / "analysis" / f"{prefix}.progress.json"
    stdout_path = project_dir / "analysis" / f"{prefix}.log"
    stderr_path = project_dir / "analysis" / f"{prefix}.err.log"
    input_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    runtime = str((engine.get("model") or {}).get("runtime") or "")
    intended_device = "cuda" if _tool_available("nvidia-smi") and runtime in {"llama_cpp", "ctranslate2", "transformers"} else "cpu"
    with resource_scheduler.model_slot(
        f"{engine.get('display_name', engine_id)} · {stage_name}",
        device=intended_device,
        on_wait=(lambda value: on_progress(progress_start, value)) if on_progress else None,
        is_cancelled=is_cancelled,
    ):
        with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
            process = subprocess.Popen(
                [str(python_executable), str(worker_path), str(manifest_path), str(input_path), str(output_path), str(progress_path)],
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                cwd=PATHS.workspace,
            )
            last_payload = ""
            while process.poll() is None:
                if is_cancelled and is_cancelled():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise export_service.ExportCancelled("Translation cancelled")
                if progress_path.exists():
                    try:
                        progress_text = progress_path.read_text(encoding="utf-8")
                        if progress_text != last_payload:
                            worker_progress = json.loads(progress_text)
                            mapped = progress_start + round(
                                int(worker_progress.get("progress", 0))
                                / 99
                                * max(0, progress_end - progress_start)
                            )
                            if on_progress:
                                on_progress(mapped, str(worker_progress.get("message", stage_name)))
                            last_payload = progress_text
                    except (OSError, ValueError, json.JSONDecodeError):
                        pass
                time.sleep(0.4)
            return_code = process.returncode
    if return_code != 0 or not output_path.exists():
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
        raise RuntimeError(f"{stage_name} failed: {(stderr_text or stdout_text)[-1800:]}")
    result = json.loads(output_path.read_text(encoding="utf-8"))
    return result, {
        f"{stage_name}_input": str(input_path),
        f"{stage_name}_result": str(output_path),
        f"{stage_name}_log": str(stderr_path),
    }


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
                "progress": max(current.progress, max(0, min(99, progress))),
                "message": message,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }))

        result = _run_stub_job(project_id, project_dir, state, job_type, completed_at, options or {}, update_progress, lambda: job_id in PROJECT_CANCEL_REQUESTS)
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
            "message": f"{_job_label(job_type)} cancelled",
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
        PROJECT_CANCEL_REQUESTS.discard(job_id)


def _job_label(job_type: str) -> str:
    return {
        "audio_separation": "Audio Preservation",
        "asr": "ASR",
        "diarization": "Diarization",
        "translation": "Translation",
        "voice_generation": "Voice generation",
        "preview": "Preview",
        "export": "Export",
    }.get(job_type, job_type)


def _coalesce_asr_segments(raw_segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Join Whisper fragments into readable utterances without destroying timestamps."""
    return resegment_for_dubbing(
        raw_segments,
        preferred_seconds=4.8,
        maximum_seconds=7.0,
        minimum_complete_seconds=2.0,
        minimum_fragment_seconds=2.70,
        minimum_words=3,
        maximum_merge_gap=0.50,
    )

    # Legacy implementation retained below for the moment to keep this patch
    # isolated from unrelated working-tree changes. It is unreachable.
    merged: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def ends_sentence(text: str) -> bool:
        return bool(search(r'[.!?…]["\'”’)\]]*$', text.strip()))

    def flush() -> None:
        nonlocal current
        if current and str(current.get("text", "")).strip():
            current["text"] = " ".join(str(current["text"]).split())
            merged.append(current)
        current = None

    for raw in raw_segments:
        text = str(raw.get("text", "")).strip()
        if not text:
            continue
        start_seconds = max(0.0, float(raw.get("start", 0.0)))
        end_seconds = max(start_seconds + 0.1, float(raw.get("end", start_seconds + 0.1)))
        words = raw.get("words") if isinstance(raw.get("words"), list) else []
        if current is None:
            current = {"start": start_seconds, "end": end_seconds, "text": text, "words": list(words)}
            continue

        gap = max(0.0, start_seconds - float(current["end"]))
        proposed_duration = end_seconds - float(current["start"])
        proposed_chars = len(str(current["text"])) + 1 + len(text)
        previous_is_complete = ends_sentence(str(current["text"]))
        must_split = previous_is_complete or gap > 1.15 or proposed_duration > 14.0 or proposed_chars > 220
        if must_split:
            flush()
            current = {"start": start_seconds, "end": end_seconds, "text": text, "words": list(words)}
        else:
            current["end"] = end_seconds
            current["text"] = f"{current['text']} {text}"
            current["words"].extend(words)
    flush()
    return merged


def _run_faster_whisper_asr(
    project_dir: Path,
    state: ProjectAnalysisState,
    timestamp: str,
    on_progress: Any | None = None,
    is_cancelled: Any | None = None,
) -> dict[str, Any]:
    asr_manifest = project_dir / "analysis" / "asr_manifest.json"
    asr_manifest.parent.mkdir(parents=True, exist_ok=True)
    source_language = _normalise_asr_language(state.source_language)
    ready_asr_engines = [
        candidate
        for candidate in list_engines()
        if candidate.get("category") == "asr"
        and candidate.get("installation", {}).get("status") == "ready"
    ]
    chinese_source = str(source_language or "").lower() in {"zh", "zh-cn", "zh-tw", "cmn"}
    engine = next(
        (
            candidate
            for candidate in ready_asr_engines
            if (candidate.get("id") == "asr-funasr-zh") == chinese_source
        ),
        ready_asr_engines[0] if ready_asr_engines else None,
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
    worker_path = PATHS.installers / (
        "run-funasr-zh.py"
        if engine.get("adapter") == "funasr-zh"
        else "run-asr.py"
    )
    if not model_manifest.exists() or not python_executable.exists() or not worker_path.exists():
        raise RuntimeError(f"The {engine.get('display_name', engine_id)} installation is incomplete. Use Repair in Engines.")

    manifest = _read_media_manifest(project_dir)
    audio_path = Path(str(manifest.get("audio_path", "")))
    if not audio_path.exists():
        raise RuntimeError("Prepared audio file is missing. Run Analyze again.")
    duration_seconds = _manifest_duration_seconds(manifest)
    worker_output = project_dir / "analysis" / "asr_worker_output.json"
    progress_file = project_dir / "analysis" / "asr_worker_progress.json"
    devices = ["cuda", "cpu"] if _tool_available("nvidia-smi") else ["cpu"]
    worker_error = ""
    for device in devices:
        worker_output.unlink(missing_ok=True)
        progress_file.unlink(missing_ok=True)
        stdout_path = project_dir / "analysis" / f"asr_worker_{device}.log"
        stderr_path = project_dir / "analysis" / f"asr_worker_{device}.err.log"
        command = [
            str(python_executable), str(worker_path),
            "--manifest", str(model_manifest),
            "--audio", str(audio_path),
            "--output", str(worker_output),
            "--progress-file", str(progress_file),
            "--device", device,
        ]
        if source_language:
            command.extend(["--language", source_language])
        if on_progress:
            on_progress(
                9,
                f"Starting {engine.get('display_name', engine_id)} on {'GPU' if device == 'cuda' else 'CPU'}",
            )
        wait_update = (lambda message: on_progress(9, message)) if on_progress else None
        try:
            with resource_scheduler.model_slot(
                "Whisper transcription",
                device=device,
                on_wait=wait_update,
                is_cancelled=is_cancelled,
            ):
                with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
                    process = subprocess.Popen(
                        command,
                        cwd=PATHS.workspace,
                        stdout=stdout_handle,
                        stderr=stderr_handle,
                        text=True,
                    )
                    last_progress_payload = ""
                    while process.poll() is None:
                        if is_cancelled and is_cancelled():
                            process.terminate()
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait(timeout=5)
                            raise export_service.ExportCancelled("ASR cancelled")
                        if progress_file.exists():
                            try:
                                progress_payload = progress_file.read_text(encoding="utf-8")
                                if progress_payload != last_progress_payload:
                                    progress = json.loads(progress_payload)
                                    if on_progress:
                                        on_progress(
                                            int(progress.get("progress", 10)),
                                            str(progress.get("message", "Whisper is transcribing")),
                                        )
                                    last_progress_payload = progress_payload
                            except (OSError, ValueError, json.JSONDecodeError):
                                pass
                        time.sleep(0.5)
                    return_code = process.returncode
        except RuntimeError as exc:
            if is_cancelled and is_cancelled():
                raise export_service.ExportCancelled("ASR cancelled") from exc
            raise
        if return_code == 0 and worker_output.exists():
            break
        stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
        stdout_text = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
        worker_error = (stderr_text or stdout_text or f"worker exited with code {return_code}").strip()
        if device == "cuda" and on_progress:
            on_progress(
                9,
                f"GPU startup failed; retrying {engine.get('display_name', engine_id)} on CPU",
            )
    else:
        raise RuntimeError(f"ASR worker failed: {worker_error[-1200:]}")

    result_payload = json.loads(worker_output.read_text(encoding="utf-8"))
    raw_segments = _coalesce_asr_segments(result_payload.get("segments", []))

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
                width=round(
                    max(
                        0.08,
                        ((end_seconds - start_seconds) / duration_seconds) * 100,
                    ),
                    3,
                ),
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
        detected_language = str(result_payload.get("language") or "").strip()
        if not state.source_language and detected_language:
            state.source_language = detected_language
        state.segments = next_segments
        state.updated_at = timestamp
        state.last_operation = "transcription"
        _write_analysis_state(project_dir, state)
        _sync_project_languages(project_dir, state)

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
                "segmentation": {
                    **(
                        result_payload.get("segmentation")
                        if isinstance(result_payload.get("segmentation"), dict)
                        else {}
                    ),
                    "strategy": "strict-visual-sync-segments-v3",
                    "preferred_seconds": 5.5,
                    "maximum_seconds": 8.5,
                    "minimum_complete_seconds": 1.45,
                    "minimum_fragment_seconds": 2.20,
                    "minimum_words": 3,
                    "maximum_merge_gap": 0.28,
                    "segment_count": len(transcript_segments),
                },
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

    if job_type == "audio_separation":
        record = _read_project_record(project_dir)
        if not record or not record.source_path:
            raise RuntimeError("The project source video is missing")
        preservation_runtime = audio_preservation_service.runtime_status()
        try:
            with resource_scheduler.model_slot(
                "Audio Preservation",
                device=str(preservation_runtime.get("device") or "cpu"),
                on_wait=(lambda detail: on_progress(2, detail)) if on_progress else None,
                is_cancelled=is_cancelled,
            ):
                preservation = audio_preservation_service.run(
                    project_dir,
                    Path(record.source_path),
                    options or {},
                    on_progress=on_progress,
                    is_cancelled=is_cancelled,
                )
        except audio_preservation_service.AudioPreservationCancelled as exc:
            raise export_service.ExportCancelled(str(exc)) from exc
        artifacts.update(preservation.get("artifacts") or {})
        message = str(preservation.get("message") or "Audio Preservation completed")
        job_status = str(preservation.get("status") or "completed")
    elif job_type == "asr":
        asr_result = _run_faster_whisper_asr(
            project_dir,
            state,
            timestamp,
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        artifacts.update(asr_result["artifacts"])
        message = asr_result["message"]
        job_status = asr_result["status"]
    elif job_type == "diarization":
        diarization_runtime = diarization_service.runtime_status()
        try:
            with resource_scheduler.model_slot(
                "Speaker Detection",
                device=str(diarization_runtime.get("device") or "cpu"),
                on_wait=(lambda detail: on_progress(2, detail)) if on_progress else None,
                is_cancelled=is_cancelled,
            ):
                diarization = diarization_service.run(
                    project_dir,
                    options or {},
                    on_progress=on_progress,
                    is_cancelled=is_cancelled,
                )
        except diarization_service.DiarizationCancelled as exc:
            raise export_service.ExportCancelled(str(exc)) from exc
        latest_state = _read_or_create_analysis_state(project_dir)
        # CASTING_R4_PATCH2B_DIARIZATION_LOCK
        casting_r4_path = project_dir / "analysis" / "casting_r4.json"
        speaker_payloads, segment_payloads = diarization_service.apply_to_analysis(
            latest_state.speakers,
            latest_state.segments,
            diarization.get("manifest") or {},
        )
        if speaker_payloads and not casting_r4_path.is_file():
            existing_voice_ids = {
                str(item.get("voice_profile_id") or "")
                for item in speaker_payloads
                if item.get("voice_profile_id")
            }
            available_profiles = [
                profile for profile in local_voice_service.profiles()
                if str(profile.get("usage_scope") or "both") in {"both", "multi"}
                and (
                    str(profile.get("language") or "multi") in {"multi", "", latest_state.target_language}
                    or str(profile.get("default_engine") or "") == "tts-omnivoice-hq"
                )
            ]
            curated_ids = [
                "omnivoice-M01", "omnivoice-F01", "omnivoice-M02", "omnivoice-F02",
                "omnivoice-M03", "omnivoice-F03", "omnivoice-M05", "omnivoice-F05",
                "omnivoice-SYS01", "omnivoice-CRE01",
            ]
            profile_by_id = {str(profile.get("id") or ""): profile for profile in available_profiles}
            ordered_profiles = [profile_by_id[item] for item in curated_ids if item in profile_by_id]
            ordered_profiles.extend(profile for profile in available_profiles if profile not in ordered_profiles)

            def profile_gender(profile: dict[str, Any]) -> str:
                declared = str(profile.get("gender") or "").lower()
                if declared in {"male", "female"}:
                    return declared
                profile_id = str(profile.get("id") or "")
                if re.search(r"(?:^|-)M\d+$", profile_id, re.IGNORECASE):
                    return "male"
                if re.search(r"(?:^|-)F\d+$", profile_id, re.IGNORECASE):
                    return "female"
                return "unspecified"

            for speaker_payload in speaker_payloads:
                role = str(speaker_payload.get("role") or "").lower()
                wanted_gender = "female" if "female" in role else "male" if "male" in role else ""
                current_id = str(speaker_payload.get("voice_profile_id") or "")
                current_profile = profile_by_id.get(current_id)
                if current_id and (
                    not wanted_gender
                    or current_profile is None
                    or profile_gender(current_profile) in {wanted_gender, "unspecified"}
                ):
                    continue
                if current_id:
                    existing_voice_ids.discard(current_id)
                    speaker_payload.update({
                        "voice_profile_id": None,
                        "voice_engine": None,
                        "voice_model": None,
                    })
                candidates = [
                    profile for profile in ordered_profiles
                    if str(profile.get("id") or "") not in existing_voice_ids
                    and (not wanted_gender or profile_gender(profile) == wanted_gender)
                ]
                if not candidates and wanted_gender:
                    candidates = [
                        profile for profile in ordered_profiles
                        if str(profile.get("id") or "") not in existing_voice_ids
                        and profile_gender(profile) == "unspecified"
                    ]
                if not candidates:
                    candidates = [profile for profile in ordered_profiles if str(profile.get("id") or "") not in existing_voice_ids]
                if not candidates:
                    continue
                selected = candidates[0]
                selected_id = str(selected.get("id") or "")
                speaker_payload.update({
                    "voice_profile_id": selected_id,
                    "voice_engine": str(selected.get("default_engine") or selected.get("preset_engine") or ""),
                    "voice_model": str(selected.get("preset_voice_id") or selected.get("model_size") or "") or None,
                })
                existing_voice_ids.add(selected_id)
            latest_state.speakers = [SpeakerRecord.model_validate(item) for item in speaker_payloads]
            latest_state.segments = [SegmentRecord.model_validate(item) for item in segment_payloads]
            latest_state.updated_at = datetime.now(timezone.utc).isoformat()
            latest_state.last_operation = "diarization"
            _write_analysis_state(project_dir, latest_state)
            artifacts["analysis_state"] = str(project_dir / "analysis" / "state.json")
        artifacts.update(diarization.get("artifacts") or {})
        job_status = str(diarization.get("status") or "completed")
        message = str(diarization.get("message") or "Speaker detection completed")
    elif job_type == "translation":
        ready_translation_engines = [
            item
            for item in list_engines()
            if item.get("category") == "translation"
            and item.get("installation", {}).get("status") == "ready"
            and is_open_source_engine(item)
        ]
        translation_mode = str((options or {}).get("mode") or "studio").lower()
        translation_mode = {
            "quick": "express",
            "faithful": "studio",
            "intelligent": "studio",
            "maximum": "master",
        }.get(translation_mode, translation_mode)
        narrative_profile = str(
            (options or {}).get("narrative_profile")
            or state.narrative_profile
            or "natural_recap"
        ).lower()
        narrative_instructions = str(
            (options or {}).get("narrative_instructions")
            or state.narrative_instructions
            or ""
        ).strip()
        requested_engine_id = str((options or {}).get("engine_id") or "")
        if requested_engine_id:
            engine = next(
                (item for item in ready_translation_engines if item.get("id") == requested_engine_id),
                None,
            )
            if not engine:
                requested_engine = next(
                    (
                        item
                        for item in list_engines()
                        if item.get("id") == requested_engine_id
                    ),
                    None,
                )
                if requested_engine:
                    require_open_source_engine(
                        requested_engine,
                        "DubRoom translation",
                    )
                raise RuntimeError(f"Requested translation engine is not ready: {requested_engine_id}")
        else:
            eligible_engines = [
                item
                for item in ready_translation_engines
                if translation_mode == "experimental"
                or "non-commercial" not in str((item.get("model") or {}).get("license") or "").lower()
                and "cc-by-nc" not in str((item.get("model") or {}).get("license") or "").lower()
            ]
            if translation_mode == "experimental":
                experimental = next(
                    (item for item in ready_translation_engines if str(item.get("id")) == "translation-nllb-600m-int8"),
                    None,
                )
                if experimental:
                    eligible_engines = [experimental]
            tier_score = {
                "studio": 80,
                "quality+": 70,
                "specialist": 60,
                "quality": 50,
                "balanced": 30,
                "light": 10,
            }
            engine = max(
                eligible_engines,
                key=lambda item: (
                    tier_score.get(str((item.get("model") or {}).get("tier", "")).lower(), 0),
                    float((item.get("model") or {}).get("parameters_b") or 0),
                ),
                default=None,
            )
        if not engine:
            job_status = "skipped"
            message = "Install a quantized translation model from Engines"
        elif not state.segments:
            job_status = "skipped"
            message = "Transcribe the source before translation"
        elif not state.target_language:
            raise RuntimeError("Choose the target dubbing language before translation")
        else:
            engine_id = str(engine["id"])
            source_language = state.source_language or "en"
            target_language = state.target_language
            segment_payload = [
                {
                    "id": segment.id,
                    "text": segment.sourceText,
                    "start": _timestamp_seconds(segment.start),
                    "end": _timestamp_seconds(segment.end),
                    "duration_seconds": max(
                        0.1,
                        _timestamp_seconds(segment.end) - _timestamp_seconds(segment.start),
                    ),
                }
                for segment in state.segments
            ]
            if on_progress:
                on_progress(3, "Detecting specialised terminology")
            terminology_report = terminology_service.analyse_transcript(
                project_id, source_language, target_language, segment_payload
            )
            terminology_research: list[dict[str, Any]] = []
            if translation_mode in {"studio", "master"}:
                if on_progress:
                    on_progress(4, "Checking unresolved terminology")
                terminology_research = terminology_service.research_candidates(
                    terminology_report,
                    limit=8 if translation_mode == "master" else 3,
                )
            terminology_report["research"] = terminology_research
            terminology_path = project_dir / "analysis" / "translation_terms.json"
            terminology_path.write_text(
                json.dumps(terminology_report, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            locked_glossary = {
                **_translation_library_glossary(source_language, target_language),
                **terminology_service.resolved_glossary(
                    project_id, source_language, target_language
                ),
            }
            payload = {
                "source_language": source_language,
                "target_language": target_language,
                "external_glossary": locked_glossary,
                "terminology_candidates": terminology_report.get("candidates", []),
                "terminology_research": terminology_research,
                "translation_memory": terminology_service.approved_memory(
                    project_id, source_language, target_language
                ),
                "mode": translation_mode,
                "narrative_profile": narrative_profile,
                "narrative_instructions": narrative_instructions,
                "segments": segment_payload,
            }
            artifacts["translation_terms"] = str(terminology_path)
            model_family = str((engine.get("model") or {}).get("family") or "").lower()
            qwen_context_engine = next(
                (
                    item
                    for item in ready_translation_engines
                    if str(item.get("id")) in {"translation-qwen3-4b-q5", "translation-qwen3-4b-q4"}
                ),
                None,
            )
            use_open_pipeline = qwen_context_engine is not None and (
                "madlad" in model_family or translation_mode == "experimental"
            ) and translation_mode != "express"
            if use_open_pipeline:
                source_fingerprint = hashlib.sha256(
                    json.dumps(
                        [
                            {
                                "source_language": source_language,
                                "target_language": target_language,
                                "glossary": locked_glossary,
                            },
                            *[
                                {"id": item["id"], "text": item["text"]}
                                for item in segment_payload
                            ],
                        ],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest()
                context_path = project_dir / "analysis" / "translation_context.json"
                context: dict[str, Any] = {}
                context_artifacts: dict[str, str] = {}
                if context_path.is_file():
                    try:
                        cached_context = json.loads(context_path.read_text(encoding="utf-8"))
                        if cached_context.get("_source_fingerprint") == source_fingerprint:
                            context = cached_context
                            if on_progress:
                                on_progress(18, "Reusing the saved story memory")
                    except (OSError, json.JSONDecodeError):
                        context = {}
                if not context:
                    context_payload = {**payload, "operation": "context_analysis"}
                    context_result, context_artifacts = _run_translation_worker_stage(
                        project_dir, qwen_context_engine, context_payload, "context", 5, 30, on_progress, is_cancelled
                    )
                    context = context_result.get("context") if isinstance(context_result.get("context"), dict) else {}
                    context["_source_fingerprint"] = source_fingerprint
                terminology_service.save_context_suggestions(
                    project_id,
                    source_language,
                    target_language,
                    context.get("glossary") if isinstance(context.get("glossary"), dict) else {},
                )
                context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")

                raw_result, raw_artifacts = _run_translation_worker_stage(
                    project_dir, engine, {**payload, "operation": "raw_translation"}, "raw", 31, 58, on_progress, is_cancelled
                )
                raw_translations = raw_result.get("translations") if isinstance(raw_result.get("translations"), list) else []
                raw_path = project_dir / "analysis" / "translation_raw.json"
                raw_path.write_text(json.dumps(raw_result, ensure_ascii=False, indent=2), encoding="utf-8")

                post_payload = {
                    **payload,
                    "operation": "post_edit",
                    "mode": translation_mode,
                    "context": context,
                    "raw_translations": raw_translations,
                }
                translated_payload, post_artifacts = _run_translation_worker_stage(
                    project_dir, qwen_context_engine, post_payload, "post_edit", 59, 96, on_progress, is_cancelled
                )
                final_path = project_dir / "analysis" / "translation_final.json"
                final_path.write_text(json.dumps(translated_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                artifacts.update(context_artifacts)
                artifacts.update(raw_artifacts)
                artifacts.update(post_artifacts)
                artifacts["translation_context"] = str(context_path)
                artifacts["translation_raw"] = str(raw_path)
                artifacts["translation_result"] = str(final_path)
            else:
                translated_payload, stage_artifacts = _run_translation_worker_stage(
                    project_dir, engine, payload, "translation", 5, 96, on_progress, is_cancelled
                )
                artifacts.update(stage_artifacts)
                artifacts["translation_result"] = stage_artifacts["translation_result"]
            by_id = {str(item.get("id")): str(item.get("text", "")) for item in translated_payload.get("translations", [])}
            result_by_id = {
                str(item.get("id")): item
                for item in translated_payload.get("translations", [])
                if isinstance(item, dict)
            }
            adapted_by_id = {
                str(item.get("id")): str(item.get("adapted_text", ""))
                for item in translated_payload.get("translations", [])
                if str(item.get("adapted_text", "")).strip()
            }
            duration_adapted_ids = {
                str(item.get("id"))
                for item in translated_payload.get("translations", [])
                if item.get("duration_adapted") is True
            }
            expected_ids = {str(item["id"]) for item in segment_payload}
            missing_ids = sorted(expected_ids - set(by_id))
            invalid_ids = [
                segment_id
                for segment_id, text in by_id.items()
                if not text.strip() or "<think>" in text.lower()
            ]
            if invalid_ids or missing_ids:
                raise RuntimeError(
                    "Translation engine returned "
                    f"{len(invalid_ids)} invalid and {len(missing_ids)} missing segment(s); "
                    "project text was not overwritten"
                )
            latest_state = _read_or_create_analysis_state(project_dir)
            latest_by_id = {segment.id: segment for segment in latest_state.segments}
            source_by_id = {str(item["id"]): str(item["text"]) for item in segment_payload}
            changed_sources = [
                segment_id
                for segment_id, source_text in source_by_id.items()
                if segment_id not in latest_by_id
                or latest_by_id[segment_id].sourceText != source_text
            ]
            if changed_sources:
                raise RuntimeError(
                    "The transcript changed while translation was running; "
                    "the completed translation was preserved as an artifact but was not applied"
                )
            for segment_id in expected_ids:
                segment = latest_by_id[segment_id]
                item_result = result_by_id.get(segment_id, {})
                segment.translatedText = by_id[segment_id]
                segment.rawTranslation = str(item_result.get("raw_text") or "")
                score_value = item_result.get("fidelity_score")
                segment.fidelityScore = int(score_value) if score_value is not None else None
                segment.fidelityIssues = _normalise_fidelity_issues(
                    item_result.get("fidelity_issues")
                )
                segment.adaptedText = (
                    adapted_by_id.get(segment_id, by_id[segment_id])
                    if segment_id in duration_adapted_ids
                    else ""
                )
            terminology_service.remember_translations(
                project_id,
                source_language,
                target_language,
                [
                    (segment.sourceText, by_id.get(segment.id, ""))
                    for segment in latest_state.segments
                    if segment.id in by_id
                ],
            )
            latest_state.updated_at = datetime.now(timezone.utc).isoformat()
            latest_state.narrative_profile = narrative_profile
            latest_state.narrative_instructions = narrative_instructions
            latest_state.last_operation = "translation"
            _write_analysis_state(project_dir, latest_state)
            state = latest_state
            artifacts["analysis_state"] = str(project_dir / "analysis" / "state.json")
            if (
                use_open_pipeline
                and qwen_context_engine
                and bool((options or {}).get("adapt_voice_script", False))
            ):
                _, voice_script_artifacts = _adapt_voice_script(
                    project_dir,
                    state,
                    qwen_context_engine,
                    on_progress=on_progress,
                    is_cancelled=is_cancelled,
                )
                artifacts.update(voice_script_artifacts)
            runtime_info = translated_payload.get("runtime") if isinstance(translated_payload.get("runtime"), dict) else {}
            runtime_label = runtime_info.get("device") or ("GPU" if runtime_info.get("gpu_offload") else "CPU")
            if use_open_pipeline:
                message = (
                    f"Translated {len(by_id)} segments with the open-source pipeline: "
                    f"{engine.get('display_name', engine_id)} + Qwen context and fidelity on {runtime_label}"
                )
            else:
                message = f"Translated {len(by_id)} segments with {engine.get('display_name', engine_id)} on {runtime_label}"
    elif job_type == "voice_generation":
        audio_dir = project_dir / "audio"
        raw_audio_dir = audio_dir / "raw"
        audio_dir.mkdir(parents=True, exist_ok=True)
        raw_audio_dir.mkdir(parents=True, exist_ok=True)
        runtime = native_tts_service.status()
        if not runtime.get("ready") or not runtime.get("installed_count"):
            return JobRecord(
                id=f"{job_type}-{uuid4().hex[:10]}", project_id=project_id, type=job_type,
                status="skipped", progress=100, message="Install a native TTS engine from Engines before generating voices",
                created_at=timestamp, updated_at=timestamp, artifacts={},
            )

        target_language = _normalise_tts_language(state.target_language)
        speaker_by_name = {speaker.name: speaker for speaker in state.speakers}
        project_record = _read_project_record(project_dir)
        if project_record and project_record.dubbing_mode == "multi":
            if not _multispeaker_resolution_ready(project_dir, state):
                raise RuntimeError(
                    "Multi-speaker voice generation requires completed GPT speaker "
                    "resolution or acoustic speaker detection."
                )
            used_speakers = {
                str(segment.speaker)
                for segment in state.segments
                if _segment_tts_text(segment).strip()
            }
            missing_cast = sorted(
                speaker_name
                for speaker_name in used_speakers
                if (
                    speaker_name not in speaker_by_name
                    or not speaker_by_name[speaker_name].voice_profile_id
                )
            )
            if missing_cast:
                raise RuntimeError(
                    "Multi-speaker casting is incomplete. Assign a voice to: "
                    + ", ".join(missing_cast)
                )
        generated_segments: list[dict[str, Any]] = []
        natural_candidates: list[dict[str, Any]] = []
        failed_segments: list[dict[str, Any]] = []
        timing_warnings: list[dict[str, Any]] = []
        merged_segment_ids: list[str] = []
        voice_manifest = audio_dir / "voice_manifest.json"
        sync_plan_path = audio_dir / "sync_plan.json"
        previous_voice_manifest = _read_json(voice_manifest)
        previous_by_id = {
            str(item.get("segment_id")): item
            for item in previous_voice_manifest.get("segments", [])
            if isinstance(item, dict)
        }
        pending_payloads: list[dict[str, Any]] = []
        pending_context: dict[str, dict[str, Any]] = {}
        prepared_voice_profiles: dict[str, dict[str, Any]] = {}
        voice_groups = _build_voice_groups(state.segments)
        merged_segment_ids = [
            str(member_id)
            for group in voice_groups
            for member_id in list(group.get("member_ids") or [])[1:]
        ]

        for voice_group_index, voice_group in enumerate(voice_groups):
            if is_cancelled and is_cancelled():
                raise export_service.ExportCancelled("Voice generation cancelled")
            segment = voice_group["lead"]
            member_ids = list(voice_group["member_ids"])
            text = str(voice_group["text"]).strip()
            speaker = speaker_by_name.get(segment.speaker)
            if not speaker or not speaker.voice_profile_id:
                failed_segments.append(
                    {
                        "segment_id": segment.id,
                        "member_ids": member_ids,
                        "reason": f"No TTS profile assigned to {segment.speaker}",
                    }
                )
                continue

            profile_id = str(speaker.voice_profile_id)
            profile = prepared_voice_profiles.get(profile_id)
            if profile is None:
                profile = local_voice_service.get(profile_id)
                if not profile:
                    failed_segments.append(
                        {
                            "segment_id": segment.id,
                            "member_ids": member_ids,
                            "reason": f"TTS profile not found: {profile_id}",
                        }
                    )
                    continue
                if str(profile.get("voice_type")) == "designed":
                    try:
                        if on_progress:
                            on_progress(8, f"Preparing and locking voice {profile.get('name') or profile_id}")
                        profile = native_tts_service.prepare_designed_profile(profile_id)
                    except (RuntimeError, ValueError) as exc:
                        failed_segments.append(
                            {
                                "segment_id": segment.id,
                                "member_ids": member_ids,
                                "reason": str(exc)[-600:],
                            }
                        )
                        continue
                prepared_voice_profiles[profile_id] = profile

            voice_profile_fingerprint = local_voice_service.profile_fingerprint(profile)
            raw_output_path = raw_audio_dir / f"{segment.id}.wav"
            final_output_path = audio_dir / f"{segment.id}.wav"
            timeline_start = float(voice_group["timeline_start"])
            timeline_end = float(voice_group["timeline_end"])
            target_duration = max(0.1, timeline_end - timeline_start)
            engine_hint = str(
                speaker.voice_engine
                or profile.get("default_engine")
                or profile.get("preset_engine")
                or ""
            ).lower()
            # PATCH041B_AUDIO_START_GUARD_ROBUST_FIX
            if "omnivoice" in engine_hint:
                payload["audio_start_guard"] = True
                payload["postprocess_output"] = False
                payload["pad_duration"] = 0.15
                payload["fade_duration"] = 0.0
            generation_text = (
                str(voice_group.get("omnivoice_text") or text).strip()
                if "omnivoice" in engine_hint
                else text
            )
            text_hash = hashlib.sha256(
                (
                    "tts-sync-v12-continuous-narration\0"
                    f"{target_language}\0{speaker.voice_profile_id}\0"
                    f"{voice_profile_fingerprint}\0"
                    "audio-start-guard-v2b\0"
                    f"{speaker.voice_engine or ''}\0{speaker.voice_instruct or ''}\0"
                    f"{timeline_start:.3f}\0{timeline_end:.3f}\0{generation_text}"
                ).encode("utf-8")
            ).hexdigest()
            previous = previous_by_id.get(segment.id)
            previous_raw = Path(str((previous or {}).get("raw_path") or ""))
            if (
                previous
                and previous.get("text_hash") == text_hash
                and previous_raw.is_file()
                and previous_raw.stat().st_size > 44
            ):
                try:
                    _trim_to_primary_speech_region(previous_raw)
                    _trim_outer_silence(previous_raw)
                    source_duration = _wav_duration(previous_raw)
                    natural_candidates.append(
                        {
                            **previous,
                            "segment_id": segment.id,
                            "path": str(previous_raw),
                            "raw_path": str(previous_raw),
                            "final_path": str(final_output_path),
                            "text_hash": text_hash,
                            "profile_id": speaker.voice_profile_id,
                            "engine": previous.get("engine") or speaker.voice_engine or "profile-default",
                            "model_size": previous.get("model_size") or speaker.voice_model,
                            "language": target_language,
                            "reused": True,
                            "timeline_start": timeline_start,
                            "timeline_end": timeline_end,
                            "ideal_timeline_start": timeline_start,
                            "ideal_timeline_end": timeline_end,
                            "member_ids": member_ids,
                            "source_duration": round(source_duration, 4),
                        }
                    )
                    continue
                except RuntimeError:
                    pass

            payload: dict[str, Any] = {
                "id": segment.id,
                "profile_id": speaker.voice_profile_id,
                "text": generation_text,
                "language": target_language,
                "output_path": str(raw_output_path),
                "target_duration": target_duration,
                "max_chunk_chars": 800,
                "crossfade_ms": 50,
                "normalize": True,
            }
            if "kokoro" in engine_hint:
                payload["speed"] = 1.0
            if speaker.voice_engine:
                payload["engine"] = speaker.voice_engine
            if speaker.voice_model:
                payload["model_size"] = speaker.voice_model
            if speaker.voice_instruct:
                payload["instruct"] = speaker.voice_instruct
            if speaker.effects_chain:
                payload["effects_chain"] = speaker.effects_chain

            pending_payloads.append(payload)
            pending_context[segment.id] = {
                "segment": segment,
                "speaker": speaker,
                "raw_output_path": raw_output_path,
                "final_output_path": final_output_path,
                "text_hash": text_hash,
                "target_duration": target_duration,
                "timeline_start": timeline_start,
                "timeline_end": timeline_end,
                "member_ids": member_ids,
            }

        if pending_payloads:
            def update_voice_progress(done: int, total: int, detail: str) -> None:
                if on_progress:
                    on_progress(10 + round((done / max(1, total)) * 78), detail)

            try:
                batch_results = native_tts_service.generate_batch(
                    pending_payloads,
                    update_voice_progress,
                    is_cancelled=is_cancelled,
                )
            except native_tts_service.TTSBatchCancelled as exc:
                raise export_service.ExportCancelled(str(exc)) from exc

            for generation in batch_results:
                segment_id = str(generation.get("id") or "")
                context = pending_context.get(segment_id)
                if not context:
                    continue
                segment = context["segment"]
                speaker = context["speaker"]
                raw_output_path = context["raw_output_path"]
                if generation.get("status") != "completed":
                    failed_segments.append(
                        {
                            "segment_id": segment_id,
                            "reason": str(
                                generation.get("error")
                                or f"TTS status: {generation.get('status')}"
                            )[-600:],
                        }
                    )
                    continue
                if not raw_output_path.is_file() or raw_output_path.stat().st_size <= 44:
                    failed_segments.append(
                        {
                            "segment_id": segment_id,
                            "reason": "Native TTS completed without a readable audio file",
                        }
                    )
                    continue
                try:
                    _trim_to_primary_speech_region(raw_output_path)
                    _trim_outer_silence(raw_output_path)
                    source_duration = _wav_duration(raw_output_path)
                    natural_candidates.append(
                        {
                            "segment_id": segment.id,
                            "path": str(raw_output_path),
                            "raw_path": str(raw_output_path),
                            "final_path": str(context["final_output_path"]),
                            "text_hash": context["text_hash"],
                            "profile_id": speaker.voice_profile_id,
                            "engine": generation.get("engine") or speaker.voice_engine or "profile-default",
                            "model_size": generation.get("model_size") or speaker.voice_model,
                            "language": target_language,
                            "sample_rate": generation.get("sample_rate"),
                            "device": generation.get("device"),
                            "fallback_chunk_count": generation.get("fallback_chunk_count", 1),
                            "retry_count": generation.get("retry_count", 0),
                            "reused": False,
                            "timeline_start": context["timeline_start"],
                            "timeline_end": context["timeline_end"],
                            "ideal_timeline_start": context["timeline_start"],
                            "ideal_timeline_end": context["timeline_end"],
                            "member_ids": context["member_ids"],
                            "source_duration": round(source_duration, 4),
                        }
                    )
                except RuntimeError as exc:
                    failed_segments.append(
                        {
                            "segment_id": segment.id,
                            "reason": str(exc)[-600:],
                        }
                    )

        sync_plan: dict[str, Any] = {}
        if natural_candidates:
            media_manifest = _read_media_manifest(project_dir)
            source_media_duration = _manifest_duration_seconds(media_manifest)
            if source_media_duration <= 0:
                source_media_duration = max(
                    float(item.get("timeline_end") or 0.0)
                    for item in natural_candidates
                )
            sync_plan = sync_service.build_sync_plan(
                natural_candidates,
                source_duration=source_media_duration,
            )
            sync_service.write_sync_plan(sync_plan_path, sync_plan)
            try:
                generated_segments, sync_failures = sync_service.synchronise_audio_takes(
                    sync_plan,
                    output_dir=audio_dir,
                    on_progress=on_progress,
                    is_cancelled=is_cancelled,
                )
            except sync_service.SyncCancelled as exc:
                raise export_service.ExportCancelled(str(exc)) from exc
            failed_segments.extend(sync_failures)
            timing_warnings.extend(sync_plan.get("warnings", []))

        attempted_count = len(generated_segments) + len(failed_segments)
        if generated_segments and not failed_segments:
            status = "completed"
        elif generated_segments:
            status = "partial"
        elif attempted_count:
            status = "failed"
        else:
            status = "skipped"

        voiceover_path = audio_dir / "voiceover.wav"
        voiceover_path.unlink(missing_ok=True)
        voiceover_duration: float | None = None
        voiceover_error: str | None = None
        voice_source_fingerprint = _voice_render_source_fingerprint(project_dir, state)
        take_set_fingerprint = _voice_take_set_fingerprint(generated_segments)
        if generated_segments:
            try:
                voiceover_duration = _assemble_voiceover_track(
                    generated_segments,
                    state.segments,
                    voiceover_path,
                )
                artifacts["voiceover"] = str(voiceover_path)
            except RuntimeError as exc:
                voiceover_error = str(exc)

        voice_manifest.write_text(
            json.dumps(
                {
                    "created_at": timestamp,
                    "status": status,
                    "runtime": "dubroom-native-tts",
                    "language": target_language,
                    "segments": generated_segments,
                    "failed_segments": failed_segments,
                    "timing_warnings": timing_warnings,
                    "merged_segments": merged_segment_ids,
                    "sync_plan_path": str(sync_plan_path) if sync_plan else None,
                    "sync_plan_fingerprint": sync_plan.get("fingerprint") if sync_plan else None,
                    "source_duration": sync_plan.get("source_duration") if sync_plan else None,
                    "output_duration": sync_plan.get("output_duration") if sync_plan else None,
                    "voiceover_path": str(voiceover_path) if voiceover_path.is_file() else None,
                    "voiceover_duration": voiceover_duration,
                    "voiceover_error": voiceover_error,
                    "source_fingerprint": voice_source_fingerprint,
                    "voiceover_take_fingerprint": (
                        take_set_fingerprint if voiceover_path.is_file() else None
                    ),
                    "stale": False,
                    "stale_reason": None,
                    "note": f"Generated {len(generated_segments)} of {attempted_count} voice segments with balanced audio/video synchronization.",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        if attempted_count:
            latest_state = _read_or_create_analysis_state(project_dir)
            generated_by_id = _voice_takes_by_member_id(generated_segments)
            failed_ids = set(_voice_takes_by_member_id(failed_segments))
            for segment in latest_state.segments:
                take = generated_by_id.get(segment.id)
                if take:
                    segment.voiceAudioReady = True
                    segment.voiceAudioDuration = _to_float(
                        take.get("scheduled_duration")
                        or take.get("output_duration")
                        or take.get("source_duration")
                    )
                    segment.voiceAudioEngine = str(take.get("engine") or "") or None
                    segment.voiceAudioStatus = "ready"
                elif segment.id in failed_ids:
                    segment.voiceAudioReady = False
                    segment.voiceAudioStatus = "failed"
            latest_state.updated_at = datetime.now(timezone.utc).isoformat()
            latest_state.last_operation = "voice_generation"
            _write_analysis_state(project_dir, latest_state)
            state = latest_state

        artifacts["voice_manifest"] = str(voice_manifest)
        if sync_plan:
            artifacts["sync_plan"] = str(sync_plan_path)
        message = (
            f"Voice generation {status}: {len(generated_segments)} generated, "
            f"{len(failed_segments)} failed, {len(timing_warnings)} automatic timing adjustment(s)"
        )
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
        if not isinstance(voice_manifest, dict):
            raise RuntimeError("The voice manifest is invalid. Generate the voices again before export")
        if voice_manifest.get("stale"):
            reason = str(voice_manifest.get("stale_reason") or "the script changed")
            raise RuntimeError(
                f"The generated voice audio is outdated because {reason}. "
                "Run voice generation again before export."
            )
        if record.dubbing_mode == "multi" and (voice_manifest.get("failed_segments") or []):
            failed_count = len(voice_manifest.get("failed_segments") or [])
            raise RuntimeError(
                f"Multi-speaker export blocked: {failed_count} voice take(s) failed. "
                "Regenerate the failed speaker/segments before export."
            )
        current_source_fingerprint = _voice_render_source_fingerprint(project_dir, state)
        manifest_source_fingerprint = str(voice_manifest.get("source_fingerprint") or "")
        if not manifest_source_fingerprint or manifest_source_fingerprint != current_source_fingerprint:
            raise RuntimeError(
                "The generated voice audio no longer matches the current translation, "
                "speaker assignment or voice profile. Run voice generation again before export."
            )

        generated = voice_manifest.get("segments", [])
        segment_by_id = {segment.id: segment for segment in state.segments}
        takes = [
            take
            for take in generated
            if isinstance(take, dict)
            and Path(str(take.get("path", ""))).is_file()
            and take.get("segment_id") in segment_by_id
        ]
        if not takes:
            raise RuntimeError("No current generated voice take is available for export")

        sync_plan: dict[str, Any] = {}
        sync_plan_path = Path(str(voice_manifest.get("sync_plan_path") or ""))
        if sync_plan_path.is_file():
            candidate_plan = _read_json(sync_plan_path)
            if (
                isinstance(candidate_plan, dict)
                and int(candidate_plan.get("version") or 0) != int(sync_service.PLAN_VERSION)
            ):
                raise RuntimeError(
                    "Le moteur de synchronisation vidéo a été mis à niveau. Relance "
                    "Génération des voix avant l'export pour construire le plan "
                    "continu V10 et préserver les pauses visuelles."
                )
            if (
                isinstance(candidate_plan, dict)
                and candidate_plan.get("fingerprint") == voice_manifest.get("sync_plan_fingerprint")
                and isinstance(candidate_plan.get("segments"), list)
            ):
                sync_plan = candidate_plan

        assembled_voiceover = Path(str(voice_manifest.get("voiceover_path") or ""))
        expected_take_fingerprint = str(voice_manifest.get("voiceover_take_fingerprint") or "")
        current_take_fingerprint = _voice_take_set_fingerprint(takes)
        if (
            assembled_voiceover.is_file()
            and state.segments
            and expected_take_fingerprint
            and expected_take_fingerprint == current_take_fingerprint
        ):
            takes = [
                {
                    "segment_id": state.segments[0].id,
                    "path": str(assembled_voiceover),
                    "timeline_start": 0.0,
                }
            ]
        manifest = _read_media_manifest(project_dir)
        duration_seconds = _manifest_duration_seconds(manifest)
        segment_times = {
            segment.id: (_timestamp_seconds(segment.start), _timestamp_seconds(segment.end))
            for segment in state.segments
        }
        subtitle_segments = [
            {
                "id": segment.id,
                "start": _timestamp_seconds(segment.start),
                "end": _timestamp_seconds(segment.end),
                "text": (
                    segment.translatedText.strip()
                    or segment.adaptedText.strip()
                    or segment.sourceText.strip()
                ),
            }
            for segment in state.segments
        ]
        if sync_plan:
            duration_seconds = float(sync_plan.get("output_duration") or duration_seconds)
            segment_times = sync_service.segment_times(sync_plan)
            subtitle_segments = sync_service.remap_subtitles(subtitle_segments, sync_plan)
        export_source_path = Path(record.source_path)
        preserved_bed_path = audio_preservation_service.track_path(project_dir, "bed")
        if record.dubbing_mode == "multi" and not preserved_bed_path:
            raise RuntimeError(
                "Multi-speaker export requires Audio Preservation bed.wav. "
                "Run Cinema or Fast separation before export so the original voices are not mixed back in."
            )
        export_mix_audio_path = preserved_bed_path
        export_options = dict(options or {})
        if preserved_bed_path:
            # In multi-speaker mode this is the dialogue-free music/SFX bed,
            # not the original dialogue track. Keep its gain independent from
            # original_volume, which intentionally remains zero for dubbing.
            export_options["_source_audio_is_bed"] = True
        cleanup_mode = str((options or {}).get("subtitle_cleanup") or "none")
        if cleanup_mode == "subclean":
            if not subclean_service.status().get("runtime_ready"):
                raise RuntimeError(
                    "SubClean is not ready. Install or repair SubClean Runtime, "
                    "or select Automatic, Blur or Crop in the subtitle finish panel."
                )
            if on_progress:
                on_progress(2, "SubClean: reconstructing the embedded subtitle area")
            cleanup_state = subclean_service.start(
                str(export_source_path),
                str((options or {}).get("subtitle_subclean_mode") or "lama"),
                [],
            )
            subclean_service.run(cleanup_state["id"])
            cleanup_result = subclean_service.get(cleanup_state["id"])
            if cleanup_result.get("status") != "completed":
                raise RuntimeError(
                    str(cleanup_result.get("error") or "SubClean could not prepare the clean video")
                )
            export_source_path = Path(str(cleanup_result["output_path"]))
            artifacts["subclean_video"] = str(export_source_path)

        export_progress = on_progress or (lambda _progress, _message: None)
        requires_video_retime = bool(
            sync_plan
            and any(
                bool(item.get("duration_fitted"))
                for item in sync_plan.get("segments", [])
                if isinstance(item, dict)
            )
        )
        if requires_video_retime:
            source_stamp = 0
            try:
                source_stamp = export_source_path.stat().st_mtime_ns
            except OSError:
                pass
            cache_dir = project_dir / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            preserve_source_audio = bool(
                (
                    preserved_bed_path
                    and float(export_options.get("music_volume", 0.0) or 0.0) > 0.0001
                )
                or (
                    not preserved_bed_path
                    and float(export_options.get("original_volume", 0.0) or 0.0) > 0.0001
                    and not bool(export_options.get("original_muted", False))
                )
            )
            preserved_audio_stamp = 0
            if preserve_source_audio and preserved_bed_path:
                try:
                    preserved_audio_stamp = preserved_bed_path.stat().st_mtime_ns
                except OSError:
                    pass
            audio_cache_tag = (
                f"bed-{preserved_audio_stamp}"
                if preserve_source_audio and preserved_bed_path
                else "a1" if preserve_source_audio else "a0"
            )
            retimed_source_path = cache_dir / (
                f"retimed-continuous-v12-pcm-{audio_cache_tag}-"
                f"{sync_plan.get('fingerprint')}-{source_stamp}.mkv"
            )
            if not retimed_source_path.is_file() or retimed_source_path.stat().st_size < 1024:
                try:
                    sync_service.render_retimed_source(
                        export_source_path,
                        retimed_source_path,
                        sync_plan,
                        include_source_audio=preserve_source_audio,
                        source_audio_path=(preserved_bed_path if preserve_source_audio else None),
                        block_size=48,
                        on_progress=on_progress,
                        is_cancelled=is_cancelled,
                    )
                except sync_service.SyncCancelled as exc:
                    raise export_service.ExportCancelled(str(exc)) from exc
            export_source_path = retimed_source_path
            # The retimed container now carries the synchronized bed track.
            export_mix_audio_path = None
            artifacts["retimed_source"] = str(retimed_source_path)
            export_progress = (
                (lambda progress, detail: on_progress(20 + round(progress * 0.8), detail))
                if on_progress
                else (lambda _progress, _message: None)
            )

        PATHS.exports.mkdir(parents=True, exist_ok=True)
        artifacts.update(export_service.execute_export(
            project_id=project_id,
            project_name=record.name,
            source_path=export_source_path,
            source_audio_path=export_mix_audio_path,
            output_root=PATHS.exports,
            options=export_options,
            takes=takes,
            segment_times=segment_times,
            subtitle_segments=subtitle_segments,
            duration_seconds=duration_seconds,
            on_progress=export_progress,
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


def _reconcile_interrupted_project_jobs() -> None:
    if not PROJECTS_ROOT.exists():
        return
    interrupted_at = datetime.now(timezone.utc).isoformat()
    for project_dir in PROJECTS_ROOT.iterdir():
        if not project_dir.is_dir() or project_dir.name.startswith("."):
            continue
        for job in _list_jobs(project_dir):
            if job.status not in {"queued", "running"}:
                continue
            _write_job(
                project_dir,
                job.model_copy(
                    update={
                        "status": "interrupted",
                        "message": f"{_job_label(job.type)} interrupted when the app stopped; retry is available",
                        "updated_at": interrupted_at,
                    }
                ),
            )


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
    tool = _resolve_system_tool(name)
    if not tool:
        return False
    try:
        subprocess.run(
            [tool, "-version"],
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


def _resolve_system_tool(name: str) -> str | None:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    if os.name != "nt":
        return None

    executable = name if name.lower().endswith(".exe") else f"{name}.exe"
    local_app_data = os.environ.get("LOCALAPPDATA")
    candidates: list[Path] = []
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
        allowed_jobs = ["audio_separation", "asr", "diarization", "translation", "voice_generation", "preview", "export"]
        recommended_engines = ["faster_whisper_small_medium", "pyannote_community_1", "argos_translate", "llama_cpp_small_llm", "piper_tts", "kokoro_82m_onnx", "supertonic_3", "f5_tts"]
    elif has_cuda and vram_mb >= 4000:
        profile_id = "gpu_balanced"
        label = "GPU Balanced"
        reason = f"{cuda['name']} with {vram_mb} MB VRAM — chunked pipeline, one model at a time."
        allowed_jobs = ["audio_separation", "asr", "diarization", "translation", "voice_generation", "preview", "export"]
        recommended_engines = ["faster_whisper_small_medium", "argos_translate", "piper_tts", "kokoro_82m_onnx", "supertonic_3"]
    elif has_cuda:
        profile_id = "gpu_light"
        label = "GPU Light"
        reason = f"{cuda['name']} detected but only {vram_mb} MB VRAM — use small models."
        allowed_jobs = ["audio_separation", "asr", "translation", "voice_generation", "export"]
        recommended_engines = ["whisper_cpp_tiny_base", "argos_translate", "piper_tts", "supertonic_3"]
    elif ram_gb >= 16:
        profile_id = "cpu_balanced"
        label = "CPU Balanced"
        reason = f"No GPU. {ram_gb} GB RAM — medium CPU models usable."
        allowed_jobs = ["audio_separation", "asr", "translation", "voice_generation", "export"]
        recommended_engines = ["whisper_cpp_tiny_base", "argos_translate", "piper_tts", "kokoro_82m_onnx", "supertonic_3"]
    elif ram_gb >= 6:
        profile_id = "cpu_fallback"
        label = "CPU Fallback"
        reason = f"No GPU. {ram_gb} GB RAM — tiny models only, slower processing."
        allowed_jobs = ["audio_separation", "asr", "translation", "export"]
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
    # Timing adaptation is no longer the default source for synthesis. Generate
    # the translated sentence naturally first; synchronization is handled later
    # by balancing audio and video rates. adaptedText remains available only as
    # an explicit/manual override when no translated text exists.
    for value in (segment.translatedText, segment.adaptedText, segment.sourceText):
        text = value.strip()
        if not text:
            continue
        if text.lower() in {"pending transcription.", "translation pending engine integration.", "adaptation pending timing engine."}:
            continue
        return text
    return ""


def _multispeaker_resolution_ready(
    project_dir: Path,
    state: ProjectAnalysisState,
) -> bool:
    """Accept the GPT resolver as the authority, with diarization as fallback."""
    resolution_path = project_dir / "analysis" / "speaker-resolution.json"
    if resolution_path.is_file():
        try:
            resolution = json.loads(resolution_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            resolution = {}
        resolved_ids = {
            str(item.get("character_id") or "").strip().upper()
            for item in resolution.get("characters") or []
            if isinstance(item, dict) and str(item.get("character_id") or "").strip()
        }
        voiced_segments = [
            segment for segment in state.segments if _segment_tts_text(segment)
        ]
        if resolved_ids and voiced_segments and all(
            str(segment.characterId or "").strip().upper() in resolved_ids
            for segment in voiced_segments
        ):
            return True
    return diarization_service.status(project_dir).get("status") == "ready"


def _voice_takes_by_member_id(
    takes: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index a merged voice take under every transcript segment it contains."""
    indexed: dict[str, dict[str, Any]] = {}
    for take in takes:
        if not isinstance(take, dict):
            continue
        member_ids = take.get("member_ids")
        if not isinstance(member_ids, list) or not member_ids:
            member_ids = [take.get("segment_id")]
        for member_id in member_ids:
            segment_id = str(member_id or "").strip()
            if segment_id:
                indexed[segment_id] = take
    return indexed


def _signature_voice_profiles() -> dict[str, str]:
    registry_path = PATHS.data / "voice-profiles" / "signature-cast.json"
    registry = _read_json(registry_path)
    result: dict[str, str] = {}
    for item in registry.get("voices") or []:
        if not isinstance(item, dict):
            continue
        voice_key = str(item.get("voice_key") or "").strip().lower()
        profile_id = str(item.get("id") or "").strip()
        if voice_key and profile_id and local_voice_service.get(profile_id):
            result[voice_key] = profile_id
    return result


def _curated_multispeaker_profile_id(
    *,
    voice_key: str,
    sex: str,
    age_group: str,
    ordinal: int,
    used_profile_ids: set[str] | None = None,
) -> str:
    """Choose a deterministic OmniVoice profile for non-signature cast roles."""
    key = str(voice_key or "supporting").strip().lower()
    declared_sex = str(sex or "uncertain").strip().lower()
    age = str(age_group or "unknown").strip().lower()
    used = used_profile_ids or set()
    if key == "system":
        return "omnivoice-SYS01"
    if key == "creature":
        return "omnivoice-CRE01"

    if key == "antagonist":
        candidates = (
            ["omnivoice-F06", "omnivoice-F05", "omnivoice-F08"]
            if declared_sex == "female"
            else ["omnivoice-M02", "omnivoice-M05", "omnivoice-M07"]
        )
    elif declared_sex == "male":
        if age in {"elderly", "senior"}:
            candidates = ["omnivoice-M07", "omnivoice-M08"]
        elif age == "teen":
            candidates = ["omnivoice-M04", "omnivoice-M03"]
        elif age == "adult":
            candidates = ["omnivoice-M05", "omnivoice-M06", "omnivoice-M02"]
        else:
            candidates = ["omnivoice-M01", "omnivoice-M03", "omnivoice-M02"]
    elif declared_sex == "female":
        if age in {"elderly", "senior"}:
            candidates = ["omnivoice-F07", "omnivoice-F08"]
        elif age == "teen":
            candidates = ["omnivoice-F04", "omnivoice-F02"]
        elif age == "adult":
            candidates = ["omnivoice-F05", "omnivoice-F06", "omnivoice-F03"]
        else:
            candidates = ["omnivoice-F01", "omnivoice-F02", "omnivoice-F03"]
    else:
        candidates = [
            "omnivoice-M03",
            "omnivoice-F02",
            "omnivoice-M06",
            "omnivoice-F06",
            "omnivoice-M01",
            "omnivoice-F01",
        ]
    offset = max(0, int(ordinal)) % len(candidates)
    preferred = candidates[offset:] + candidates[:offset]
    gendered_fallback = [
        "omnivoice-M01", "omnivoice-M02", "omnivoice-M03", "omnivoice-M04",
        "omnivoice-M05", "omnivoice-M06", "omnivoice-M07", "omnivoice-M08",
        "omnivoice-F01", "omnivoice-F02", "omnivoice-F03", "omnivoice-F04",
        "omnivoice-F05", "omnivoice-F06", "omnivoice-F07", "omnivoice-F08",
    ]
    for candidate in [*preferred, *gendered_fallback]:
        if candidate not in used:
            return candidate
    return preferred[0]


def _omnivoice_segment_text(segment: SegmentRecord) -> str:
    text = _segment_tts_text(segment).strip()
    if not text:
        return ""
    before: list[str] = []
    after: list[str] = []
    legacy_tag = str(segment.omnivoiceTag or "").strip()
    if legacy_tag:
        before.append(legacy_tag)
    for event in segment.omnivoiceEvents:
        if not isinstance(event, dict):
            continue
        tag = str(event.get("event") or "").strip()
        if not tag:
            continue
        if str(event.get("position") or "before").strip().lower() == "after":
            after.append(tag)
        else:
            before.append(tag)
    return " ".join([*before, text, *after]).strip()


def _expand_v3_voice_units(
    segments: list[SegmentRecord],
    imported_entries: dict[str, dict[str, Any]],
) -> tuple[list[SegmentRecord], dict[str, dict[str, Any]]]:
    """Expand immutable ASR parents into ordered, independently cast dub lines."""
    timeline_duration = max(
        0.1,
        max((_timestamp_seconds(segment.end) for segment in segments), default=0.1),
    )
    expanded_segments: list[SegmentRecord] = []
    expanded_entries: dict[str, dict[str, Any]] = {}

    def position(segment: SegmentRecord) -> None:
        start_seconds = _timestamp_seconds(segment.start)
        end_seconds = max(start_seconds + 0.1, _timestamp_seconds(segment.end))
        segment.left = round(start_seconds / timeline_duration * 100, 4)
        segment.width = round((end_seconds - start_seconds) / timeline_duration * 100, 4)

    for parent in segments:
        parent_entry = imported_entries.get(parent.id)
        units = list((parent_entry or {}).get("voice_units") or [])
        if not parent_entry or not units:
            expanded_segments.append(parent)
            if parent_entry:
                expanded_entries[parent.id] = parent_entry
            continue

        bridge = (parent_entry or {}).get("narrator_bridge") or {}
        bridge_slot = (parent_entry or {}).get("bridge_slot") or {}
        bridge_text = str(bridge.get("translation") or "").strip()
        if bool(bridge.get("enabled")) and bridge_text:
            bridge_segment = parent.model_copy(deep=True)
            bridge_segment.id = f"{parent.id}-bridge"
            bridge_segment.start = str(bridge_slot.get("start") or parent.start)
            bridge_segment.end = str(bridge_slot.get("end") or parent.start)
            bridge_segment.sourceText = ""
            bridge_segment.sourceSegmentId = parent.id
            bridge_segment.speechType = "narration"
            bridge_segment.voiceKey = "narrator"
            position(bridge_segment)
            expanded_segments.append(bridge_segment)
            bridge_events = list(bridge.get("vocal_events") or [])
            expanded_entries[bridge_segment.id] = {
                "id": bridge_segment.id,
                "target_text": bridge_text,
                "temporary_cluster": "NARRATOR_BRIDGE",
                "character_id": "NARRATOR",
                "character_name": "Narrator",
                "character_role": "external_narrator",
                "character_confidence": 1.0,
                "emotion": str(bridge.get("emotion") or "neutral").strip().lower(),
                "emotion_intensity": int(float(bridge.get("emotion_intensity") or 0)),
                "omnivoice_tag": "",
                "vocal_events": bridge_events,
                "source_segment_id": parent.id,
                "speech_type": "narration",
                "voice_key": "narrator",
            }

        parent_start = _timestamp_seconds(parent.start)
        parent_end = max(parent_start + 0.1, _timestamp_seconds(parent.end))
        ordered_units = sorted(units, key=lambda item: int(item.get("order") or 0))
        weights = [
            max(1, len(re.findall(r"\b[\w'-]+\b", str(unit.get("target_text") or ""))))
            for unit in ordered_units
        ]
        total_weight = max(1, sum(weights))
        separator = 0.06 if len(ordered_units) > 1 else 0.0
        usable_duration = max(0.1 * len(ordered_units), parent_end - parent_start - separator * (len(ordered_units) - 1))
        cursor = parent_start
        for index, (unit, weight) in enumerate(zip(ordered_units, weights, strict=True), start=1):
            unit_segment = parent.model_copy(deep=True)
            unit_segment.id = str(unit.get("unit_id") or f"{parent.id}-u{index:02d}")
            duration = usable_duration * weight / total_weight
            unit_end = parent_end if index == len(ordered_units) else min(parent_end, cursor + duration)
            unit_segment.start = _format_timestamp(cursor)
            unit_segment.end = _format_timestamp(max(cursor + 0.1, unit_end))
            unit_segment.sourceText = str(unit.get("source_excerpt") or parent.sourceText).strip()
            unit_segment.sourceSegmentId = parent.id
            unit_segment.speechType = str(unit.get("speech_type") or "").strip()
            unit_segment.voiceKey = str(unit.get("voice_key") or "").strip()
            position(unit_segment)
            expanded_segments.append(unit_segment)
            expanded_entries[unit_segment.id] = {
                "id": unit_segment.id,
                "target_text": str(unit.get("target_text") or "").strip(),
                "temporary_cluster": str((parent_entry or {}).get("temporary_cluster") or "").strip(),
                "character_id": str(unit.get("character_id") or "").strip().upper(),
                "character_name": str(unit.get("character_name") or "").strip(),
                "character_role": str(unit.get("character_role") or "").strip(),
                "character_confidence": unit.get("character_confidence"),
                "emotion": str(unit.get("emotion") or "neutral").strip().lower(),
                "emotion_intensity": int(unit.get("emotion_intensity") or 0),
                "omnivoice_tag": "",
                "vocal_events": list(unit.get("vocal_events") or []),
                "source_segment_id": parent.id,
                "speech_type": str(unit.get("speech_type") or "").strip(),
                "voice_key": str(unit.get("voice_key") or "").strip(),
            }
            cursor = unit_end + separator
    expanded_segments.sort(key=lambda segment: (_timestamp_seconds(segment.start), _timestamp_seconds(segment.end), segment.id))
    return expanded_segments, expanded_entries



def _build_voice_groups(
    segments: list[SegmentRecord],
    *,
    preferred_seconds: float = 6.8,
    maximum_seconds: float = 10.5,
    maximum_gap_seconds: float = 0.55,
    trailing_room_seconds: float = 0.18,
) -> list[dict[str, Any]]:
    """Build continuous narrative TTS takes while preserving ASR anchors.

    Neighbouring rows with the same assigned voice are synthesized as one WAV.
    Original segment IDs remain available in member_ids for subtitles, editing
    and synchronization.
    """
    # CONTINUOUS_NARRATION_V2_20260803
    preferred = max(
        3.5,
        float(os.getenv("DUBROOM_TTS_GROUP_PREFERRED_SECONDS", preferred_seconds)),
    )
    maximum = max(
        preferred,
        float(os.getenv("DUBROOM_TTS_GROUP_MAXIMUM_SECONDS", maximum_seconds)),
    )
    maximum_gap = max(
        0.0,
        float(os.getenv("DUBROOM_TTS_GROUP_MAXIMUM_GAP_SECONDS", maximum_gap_seconds)),
    )
    trailing_room = max(
        0.0,
        min(
            0.30,
            float(
                os.getenv(
                    "DUBROOM_TTS_GROUP_TRAILING_ROOM_SECONDS",
                    trailing_room_seconds,
                )
            ),
        ),
    )

    visible = [segment for segment in segments if _segment_tts_text(segment)]
    if not visible:
        return []

    grouped: list[list[SegmentRecord]] = []
    current: list[SegmentRecord] = []
    hard_end = re.compile(r"""[.!?…]["'”’)]*$""")

    def flush() -> None:
        nonlocal current
        if current:
            grouped.append(current)
        current = []

    for segment in visible:
        if not current:
            current = [segment]
            continue

        first = current[0]
        previous = current[-1]
        group_start = _timestamp_seconds(first.start)
        previous_end = max(group_start, _timestamp_seconds(previous.end))
        next_start = _timestamp_seconds(segment.start)
        next_end = max(next_start + 0.1, _timestamp_seconds(segment.end))
        current_duration = max(0.1, previous_end - group_start)
        projected_duration = max(0.1, next_end - group_start)
        gap = max(0.0, next_start - previous_end)
        same_voice = str(segment.speaker or "").strip() == str(previous.speaker or "").strip()
        previous_complete = bool(hard_end.search(_segment_tts_text(previous)))

        can_join = (
            same_voice
            and gap <= maximum_gap
            and projected_duration <= maximum
            and not (current_duration >= preferred and previous_complete)
        )
        if can_join:
            current.append(segment)
        else:
            flush()
            current = [segment]
    flush()

    groups: list[dict[str, Any]] = []
    for index, members in enumerate(grouped):
        lead = members[0]
        timeline_start = _timestamp_seconds(lead.start)
        source_timeline_end = max(
            timeline_start + 0.1,
            _timestamp_seconds(members[-1].end),
        )
        next_start = (
            _timestamp_seconds(grouped[index + 1][0].start)
            if index + 1 < len(grouped)
            else source_timeline_end
        )
        available_gap = max(0.0, next_start - source_timeline_end)
        reserved_tail = min(trailing_room, max(0.0, available_gap - 0.04))
        timeline_end = source_timeline_end + reserved_tail
        text = re.sub(
            r"\s+",
            " ",
            " ".join(
                _segment_tts_text(member).strip()
                for member in members
                if _segment_tts_text(member).strip()
            ),
        ).strip()
        omnivoice_text = re.sub(
            r"\s+",
            " ",
            " ".join(
                _omnivoice_segment_text(member)
                for member in members
                if _segment_tts_text(member).strip()
            ),
        ).strip()
        groups.append(
            {
                "id": lead.id,
                "lead": lead,
                "members": members,
                "member_ids": [member.id for member in members],
                "text": text,
                "omnivoice_text": omnivoice_text,
                "timeline_start": timeline_start,
                "timeline_end": timeline_end,
                "source_timeline_end": source_timeline_end,
                "anchor_offsets": [
                    {
                        "id": member.id,
                        "start": max(0.0, _timestamp_seconds(member.start) - timeline_start),
                        "end": max(0.0, _timestamp_seconds(member.end) - timeline_start),
                    }
                    for member in members
                ],
                "continuous_narration": len(members) > 1,
            }
        )
    return groups

def _voice_groups_fingerprint(voice_groups: list[dict[str, Any]]) -> str:
    """Fingerprint the exact text and grouping that may be sent to TTS.

    This prevents an old voice_script.json from overriding a newly imported or
    manually edited translation merely because the segment IDs still match.
    """
    fingerprint_payload = [
        {"version": "voice-script-v12-continuous-narration"},
        *[
            {
                "id": group["id"],
                "member_ids": list(group["member_ids"]),
                "text": str(group["text"]),
                "omnivoice_text": str(group.get("omnivoice_text") or ""),
                "timeline_start": round(float(group["timeline_start"]), 3),
                "timeline_end": round(float(group["timeline_end"]), 3),
            }
            for group in voice_groups
        ],
    ]
    return hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _voice_render_source_fingerprint(
    project_dir: Path,
    state: ProjectAnalysisState,
) -> str:
    """Fingerprint the text, timing and voice configuration used by TTS.

    voice_script.json is deliberately ignored. Automatic timing rewrites are no
    longer allowed to replace the current translated text behind the user's back.
    """
    voice_groups = _build_voice_groups(state.segments)
    speaker_by_name = {speaker.name: speaker for speaker in state.speakers}
    payload: list[dict[str, Any]] = [
        {
            "version": "voice-render-source-v12-continuous-narration",
            "target_language": _normalise_tts_language(state.target_language),
        }
    ]
    for group in voice_groups:
        lead = group["lead"]
        speaker = speaker_by_name.get(lead.speaker)
        profile_id = str(speaker.voice_profile_id or "") if speaker else ""
        profile_fingerprint = ""
        if profile_id:
            profile = local_voice_service.get(profile_id)
            if profile:
                profile_fingerprint = local_voice_service.profile_fingerprint(profile)
        payload.append(
            {
                "id": str(group["id"]),
                "member_ids": [str(value) for value in group["member_ids"]],
                "text": str(group["text"]).strip(),
                "omnivoice_text": str(group.get("omnivoice_text") or "").strip(),
                "timeline_start": round(float(group["timeline_start"]), 3),
                "timeline_end": round(float(group["timeline_end"]), 3),
                "speaker": str(lead.speaker),
                "voice_profile_id": profile_id,
                "voice_profile_fingerprint": profile_fingerprint,
                "voice_engine": str(speaker.voice_engine or "") if speaker else "",
                "voice_model": str(speaker.voice_model or "") if speaker else "",
                "voice_instruct": str(speaker.voice_instruct or "") if speaker else "",
                "effects_chain": list(speaker.effects_chain) if speaker else [],
            }
        )
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _voice_take_set_fingerprint(takes: list[dict[str, Any]]) -> str:
    """Fingerprint the exact WAV files assembled into voiceover.wav."""
    payload: list[dict[str, Any]] = [{"version": "voice-take-set-v1"}]
    for take in sorted(takes, key=lambda item: str(item.get("segment_id") or "")):
        path = Path(str(take.get("path") or ""))
        try:
            stat = path.stat()
            stamp = stat.st_mtime_ns
            size = stat.st_size
        except OSError:
            stamp = 0
            size = 0
        payload.append(
            {
                "segment_id": str(take.get("segment_id") or ""),
                "path": str(path.resolve()) if str(path) else "",
                "size": size,
                "mtime_ns": stamp,
                "text_hash": str(take.get("text_hash") or ""),
                "timeline_start": round(float(take.get("timeline_start") or 0.0), 3),
                "timeline_end": round(float(take.get("timeline_end") or 0.0), 3),
            }
        )
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _mark_voice_manifest_stale(
    project_dir: Path,
    *,
    reason: str,
    changed_segment_ids: list[str] | None = None,
) -> None:
    """Preserve old takes for selective regeneration while blocking stale export."""
    manifest_path = project_dir / "audio" / "voice_manifest.json"
    if not manifest_path.is_file():
        return
    manifest = _read_json(manifest_path)
    if not manifest:
        return
    manifest.update(
        {
            "stale": True,
            "stale_reason": reason,
            "invalidated_at": datetime.now(timezone.utc).isoformat(),
            "changed_segment_ids": list(changed_segment_ids or []),
        }
    )
    temporary = manifest_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(manifest_path)


def _adapt_voice_script(
    project_dir: Path,
    state: ProjectAnalysisState,
    engine: dict[str, Any],
    *,
    on_progress: Callable[[int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    voice_groups = _build_voice_groups(state.segments)
    fingerprint = _voice_groups_fingerprint(voice_groups)
    output_path = project_dir / "analysis" / "voice_script.json"
    context = _read_json(project_dir / "analysis" / "translation_context.json")
    groups_payload = []
    for group in voice_groups:
        duration = max(
            0.1,
            float(group["timeline_end"]) - float(group["timeline_start"]),
        )
        members = list(group["members"])
        groups_payload.append(
            {
                "id": group["id"],
                "member_ids": group["member_ids"],
                "source": " ".join(
                    member.sourceText.strip()
                    for member in members
                    if member.sourceText.strip()
                ),
                "translation": group["text"],
                "duration_seconds": round(duration, 3),
                # Calibrated against Kokoro French at natural 1.0x speed. This
                # already includes the permitted transparent 1.08x tempo ceiling.
                "maximum_non_space_characters": max(12, round(duration * 15.0)),
                "maximum_words": max(3, round(duration * 2.55)),
            }
        )
    payload_by_id = {str(item["id"]): item for item in groups_payload}
    artifacts: dict[str, str] = {}
    result: dict[str, Any] | None = None
    if output_path.is_file():
        cached = _read_json(output_path)
        if cached.get("_source_fingerprint") == fingerprint:
            result = cached
            artifacts["voice_script"] = str(output_path)

    if result is None:
        payload = {
            "operation": "voice_script_adapt",
            "source_language": state.source_language or "en",
            "target_language": state.target_language or "fr",
            "context": context,
            "groups": groups_payload,
        }
        result, stage_artifacts = _run_translation_worker_stage(
            project_dir,
            engine,
            payload,
            "voice_script",
            96,
            99,
            on_progress,
            is_cancelled,
        )
        artifacts.update(stage_artifacts)

    repair_round = int(result.get("_repair_rounds") or 0)
    while repair_round < 3:
        current_rows = [
            item
            for item in (result.get("groups") or [])
            if isinstance(item, dict)
        ]
        overflow_rows = [
            item for item in current_rows if bool(item.get("timing_overflow"))
        ]
        if not overflow_rows:
            break
        repair_groups = []
        for item in overflow_rows:
            base = payload_by_id.get(str(item.get("id") or ""))
            if not base:
                continue
            repair_groups.append(
                {
                    **base,
                    "translation": str(item.get("text") or base["translation"]),
                }
            )
        if not repair_groups:
            break
        repair_round += 1
        if on_progress:
            on_progress(
                99,
                f"Repairing {len(repair_groups)} remaining voice groups "
                f"(pass {repair_round} of 3)",
            )
        repair_payload = {
            "operation": "voice_script_adapt",
            "source_language": state.source_language or "en",
            "target_language": state.target_language or "fr",
            "context": context,
            "groups": repair_groups,
        }
        repaired, repair_artifacts = _run_translation_worker_stage(
            project_dir,
            engine,
            repair_payload,
            f"voice_script_repair_{repair_round}",
            99,
            99,
            on_progress,
            is_cancelled,
        )
        repaired_by_id = {
            str(item.get("id")): item
            for item in (repaired.get("groups") or [])
            if isinstance(item, dict)
        }
        result["groups"] = [
            repaired_by_id.get(str(item.get("id")), item)
            for item in current_rows
        ]
        result["_repair_rounds"] = repair_round
        artifacts.update(repair_artifacts)

    remaining_rows = [
        item
        for item in (result.get("groups") or [])
        if isinstance(item, dict) and bool(item.get("timing_overflow"))
    ]
    if remaining_rows and not result.get("_safety_pass"):
        safety_groups = []
        for item in remaining_rows:
            base = payload_by_id.get(str(item.get("id") or ""))
            if not base:
                continue
            safety_groups.append(
                {
                    **base,
                    "translation": str(item.get("text") or base["translation"]),
                    "maximum_non_space_characters": max(
                        12,
                        round(float(base["maximum_non_space_characters"]) * 0.82),
                    ),
                    "maximum_words": max(
                        3,
                        round(float(base["maximum_words"]) * 0.82),
                    ),
                }
            )
        if safety_groups:
            if on_progress:
                on_progress(
                    99,
                    f"Applying the Kokoro safety margin to {len(safety_groups)} groups",
                )
            safety_payload = {
                "operation": "voice_script_adapt",
                "source_language": state.source_language or "en",
                "target_language": state.target_language or "fr",
                "context": context,
                "groups": safety_groups,
            }
            safer, safety_artifacts = _run_translation_worker_stage(
                project_dir,
                engine,
                safety_payload,
                "voice_script_safety",
                99,
                99,
                on_progress,
                is_cancelled,
            )
            safer_by_id = {
                str(item.get("id")): item
                for item in (safer.get("groups") or [])
                if isinstance(item, dict)
            }
            normalised_rows = []
            for item in (result.get("groups") or []):
                replacement = safer_by_id.get(str(item.get("id")), item)
                base = payload_by_id.get(str(item.get("id") or ""), {})
                original_maximum = int(
                    base.get("maximum_non_space_characters")
                    or replacement.get("maximum_non_space_characters")
                    or 12
                )
                text = str(replacement.get("text") or "")
                replacement["maximum_non_space_characters"] = original_maximum
                replacement["non_space_characters"] = len(re.sub(r"\s+", "", text))
                replacement["timing_overflow"] = (
                    int(replacement["non_space_characters"]) > original_maximum
                )
                normalised_rows.append(replacement)
            result["groups"] = normalised_rows
            artifacts.update(safety_artifacts)
        result["_safety_pass"] = True

    result["_source_fingerprint"] = fingerprint
    result["group_count"] = len(groups_payload)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    artifacts["voice_script"] = str(output_path)
    return result, artifacts


TTS_LEAD_IN_SECONDS = 0.15
TTS_TAIL_OUT_SECONDS = 0.10
TTS_SILENCE_WINDOW_SECONDS = 0.01


def _trim_to_primary_speech_region(audio_path: Path) -> bool:
    """PATCH041B_AUDIO_START_GUARD_ROBUST_FIX: destructive speech-island crop disabled.

    A weak initial consonant can fall below an energy threshold. Selecting a
    primary speech island can therefore decapitate the first phoneme. Keep the
    raw take intact; the additive edge guard below may add silence but never
    removes samples from the front.
    """
    return False


def _edge_silence_frames(
    samples: array,
    *,
    sample_rate: int,
    from_end: bool,
) -> int:
    """Measure only clearly silent PCM windows contiguous with one file edge."""
    if not samples or sample_rate <= 0:
        return 0
    window_frames = max(1, round(sample_rate * 0.005))
    peak = max((abs(int(value)) for value in samples), default=0)
    threshold = max(8.0, peak * 0.0015)
    frame_count = len(samples)
    silent_frames = 0

    if from_end:
        cursor = frame_count
        while cursor > 0:
            window_start = max(0, cursor - window_frames)
            window = samples[window_start:cursor]
            rms = math.sqrt(
                sum(int(value) * int(value) for value in window)
                / max(1, len(window))
            )
            if rms > threshold:
                break
            silent_frames += len(window)
            cursor = window_start
    else:
        cursor = 0
        while cursor < frame_count:
            window_end = min(frame_count, cursor + window_frames)
            window = samples[cursor:window_end]
            rms = math.sqrt(
                sum(int(value) * int(value) for value in window)
                / max(1, len(window))
            )
            if rms > threshold:
                break
            silent_frames += len(window)
            cursor = window_end

    return silent_frames


def _trim_outer_silence(
    audio_path: Path,
    *,
    lead_in_seconds: float = TTS_LEAD_IN_SECONDS,
    tail_out_seconds: float = TTS_TAIL_OUT_SECONDS,
) -> bool:
    """PATCH041B_AUDIO_START_GUARD_ROBUST_FIX: additive-only edge protection.

    Never slices the beginning or end of the generated take. It only prepends
    or appends zero PCM when the detected speech sits too close to a file edge.
    This preserves weak plosives/fricatives that an energy-based trim may miss.
    """
    try:
        with wave.open(str(audio_path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            raw_frames = source.readframes(source.getnframes())
    except (OSError, wave.Error):
        return False
    if channels != 1 or sample_width != 2 or sample_rate <= 0 or not raw_frames:
        return False

    samples = array("h")
    samples.frombytes(raw_frames)
    if not samples:
        return False

    window_frames = max(1, round(sample_rate * 0.01))
    energies: list[float] = []
    for offset in range(0, len(samples), window_frames):
        window = samples[offset : offset + window_frames]
        if not window:
            continue
        energies.append(math.sqrt(sum(int(value) * int(value) for value in window) / len(window)))
    if not energies:
        return False

    ordered = sorted(energies)
    noise_floor = ordered[min(len(ordered) - 1, round(len(ordered) * 0.20))]
    speech_level = ordered[min(len(ordered) - 1, round(len(ordered) * 0.90))]
    if noise_floor >= speech_level * 0.65:
        threshold = max(75.0, speech_level * 0.15)
    else:
        threshold = max(75.0, noise_floor * 2.8, speech_level * 0.025)
    active = [energy >= threshold for energy in energies]
    if not any(active):
        return False

    first_active = next(index for index, value in enumerate(active) if value)
    last_active = len(active) - 1 - next(index for index, value in enumerate(reversed(active)) if value)
    speech_start = first_active * window_frames
    speech_end = min(len(samples), (last_active + 1) * window_frames)

    wanted_lead = max(0, round(sample_rate * max(0.0, lead_in_seconds)))
    wanted_tail = max(0, round(sample_rate * max(0.0, tail_out_seconds)))
    existing_lead = max(0, speech_start)
    existing_tail = max(0, len(samples) - speech_end)
    add_lead = max(0, wanted_lead - existing_lead)
    add_tail = max(0, wanted_tail - existing_tail)
    if add_lead <= 0 and add_tail <= 0:
        return False

    # Critical rule: preserve every original sample. No source_start/source_end slicing.
    kept = array("h")
    if add_lead:
        kept.extend(array("h", [0]) * add_lead)
    kept.extend(samples)
    if add_tail:
        kept.extend(array("h", [0]) * add_tail)

    temporary = audio_path.with_name(f"{audio_path.stem}.edgeguard.wav")
    try:
        with wave.open(str(temporary), "wb") as destination:
            destination.setnchannels(1)
            destination.setsampwidth(2)
            destination.setframerate(sample_rate)
            destination.writeframes(kept.tobytes())
        os.replace(temporary, audio_path)
        return True
    except (OSError, wave.Error):
        temporary.unlink(missing_ok=True)
        return False


def _fit_audio_to_duration(audio_path: Path, target_duration: float) -> dict[str, float | bool]:
    """Tempo-fit a generated line to its timeline slot and pad/trim the final milliseconds."""
    ffmpeg = _resolve_system_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to synchronize generated speech")

    # First isolate the real take, then keep a short natural cushion around it.
    # This removes half-second/model padding without cutting directly on speech.
    _trim_to_primary_speech_region(audio_path)
    _trim_outer_silence(audio_path)

    try:
        with wave.open(str(audio_path), "rb") as source:
            source_duration = source.getnframes() / float(source.getframerate())
    except (OSError, wave.Error, ZeroDivisionError) as exc:
        raise RuntimeError(f"Cannot measure generated TTS audio: {exc}") from exc
    if source_duration <= 0 or target_duration <= 0:
        raise RuntimeError("Generated TTS audio has an invalid duration")

    tempo = source_duration / target_duration
    max_natural_tempo = 1.08
    if tempo > max_natural_tempo:
        raise RuntimeError(
            "Natural speech does not fit this timeline slot: "
            f"{source_duration:.2f}s generated for {target_duration:.2f}s available "
            f"(would require {tempo:.2f}x speed; maximum is {max_natural_tempo:.2f}x). "
            "Shorten the adapted dubbing line instead of accelerating the voice."
        )
    if tempo <= 1.025:
        # Never stretch or pad a short take to the full slot. The WAV already
        # keeps 120 ms before speech and 180 ms after it; any larger underfill
        # must be fixed by the translated wording, not by manufacturing silence.
        return {
            "source_duration": round(source_duration, 4),
            "target_duration": round(target_duration, 4),
            "tempo_ratio": 1.0,
            "duration_fitted": False,
        }

    # Only a small, pitch-preserving acceleration is allowed when a line is
    # slightly over its slot. No artificial full-slot padding is added.
    filters = [f"atempo={tempo:.8f}"]

    fitted_path = audio_path.with_name(f"{audio_path.stem}.fitted.wav")
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(audio_path),
            "-filter:a",
            ",".join(filters),
            "-c:a",
            "pcm_s16le",
            str(fitted_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not fitted_path.exists():
        fitted_path.unlink(missing_ok=True)
        raise RuntimeError(f"Speech synchronization failed: {(completed.stderr or completed.stdout)[-800:]}")
    os.replace(fitted_path, audio_path)
    return {
        "source_duration": round(source_duration, 4),
        "target_duration": round(target_duration, 4),
        "tempo_ratio": round(tempo, 4),
        "duration_fitted": True,
    }


def _declick_wav_edges(
    audio_path: Path,
    *,
    fade_in_ms: float = 0.0,
    fade_out_ms: float = 5.0,
) -> bool:
    """PATCH041B_AUDIO_START_GUARD_ROBUST_FIX: no fade-in on narrator speech."""
    try:
        with wave.open(str(audio_path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            raw_frames = source.readframes(source.getnframes())
    except (OSError, wave.Error):
        return False
    if channels != 1 or sample_width != 2 or sample_rate <= 0 or not raw_frames:
        return False

    samples = array("h")
    samples.frombytes(raw_frames)
    if len(samples) < 4:
        return False

    fade_out = 0 if fade_out_ms <= 0 else min(len(samples) // 3, max(2, round(sample_rate * fade_out_ms / 1000.0)))
    if fade_out <= 0:
        return False
    for offset in range(fade_out):
        index = len(samples) - fade_out + offset
        gain = (fade_out - 1 - offset) / float(max(1, fade_out - 1))
        samples[index] = round(samples[index] * gain)

    temporary = audio_path.with_name(f"{audio_path.stem}.declick.wav")
    try:
        with wave.open(str(temporary), "wb") as destination:
            destination.setnchannels(1)
            destination.setsampwidth(2)
            destination.setframerate(sample_rate)
            destination.writeframes(samples.tobytes())
        os.replace(temporary, audio_path)
        return True
    except (OSError, wave.Error):
        temporary.unlink(missing_ok=True)
        return False


def _wav_duration(audio_path: Path) -> float:
    try:
        with wave.open(str(audio_path), "rb") as source:
            return source.getnframes() / float(source.getframerate())
    except (OSError, wave.Error, ZeroDivisionError) as exc:
        raise RuntimeError(f"Cannot measure generated TTS audio: {exc}") from exc


def _apply_natural_tempo(audio_path: Path, tempo: float) -> None:
    if tempo <= 1.025:
        return
    ffmpeg = _resolve_system_tool("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to synchronize generated speech")
    fitted_path = audio_path.with_name(f"{audio_path.stem}.tempo.wav")
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(audio_path),
            "-filter:a",
            f"atempo={tempo:.8f}",
            "-c:a",
            "pcm_s16le",
            str(fitted_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not fitted_path.exists():
        fitted_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Speech synchronization failed: "
            f"{(completed.stderr or completed.stdout)[-800:]}"
        )
    os.replace(fitted_path, audio_path)



def _schedule_voice_takes(
    candidates: list[dict[str, Any]],
    *,
    maximum_tempo: float = 1.04,
    anchor_gap_seconds: float = 0.05,
    minimum_gap_seconds: float = 0.05,
    maximum_gap_borrow_seconds: float = 1.50,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Schedule one natural TTS take per transcript segment.

    A take keeps its original segment start. When it is slightly longer than the
    transcript window, it may use a real silent gap before the next segment. Only
    after that gap is exhausted can a tiny pitch-preserving acceleration be used.
    Short takes are never slowed or padded with fake stretched speech.
    """
    scheduled: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    ordered = sorted(
        candidates,
        key=lambda value: float(
            value.get("ideal_timeline_start")
            if value.get("ideal_timeline_start") is not None
            else value.get("timeline_start") or 0.0
        ),
    )

    for index, item in enumerate(ordered):
        segment_id = str(item.get("segment_id") or "")
        ideal_start = float(
            item.get("ideal_timeline_start")
            if item.get("ideal_timeline_start") is not None
            else item.get("timeline_start") or 0.0
        )
        ideal_end = float(
            item.get("ideal_timeline_end")
            if item.get("ideal_timeline_end") is not None
            else item.get("timeline_end") or ideal_start + 0.1
        )
        target_duration = max(0.1, ideal_end - ideal_start)
        path = Path(str(item.get("path") or ""))
        if not path.is_file():
            failures.append({"segment_id": segment_id, "reason": "Generated voice file is missing"})
            continue

        # Measure the take after excessive padding is reduced, while retaining 0.12-0.18 s of breathing room.
        _trim_to_primary_speech_region(path)
        _trim_outer_silence(path)
        try:
            source_duration = _wav_duration(path)
        except RuntimeError as exc:
            failures.append({"segment_id": segment_id, "reason": str(exc)[-600:]})
            continue

        explicit_next = item.get("next_timeline_start")
        if explicit_next is not None:
            next_anchor = float(explicit_next)
        elif index + 1 < len(ordered):
            following = ordered[index + 1]
            next_anchor = float(
                following.get("ideal_timeline_start")
                if following.get("ideal_timeline_start") is not None
                else following.get("timeline_start") or ideal_end
            )
        else:
            next_anchor = ideal_end

        real_post_gap = max(0.0, next_anchor - ideal_end - minimum_gap_seconds)
        borrowed_gap = min(maximum_gap_borrow_seconds, real_post_gap)
        available_duration = target_duration + borrowed_gap
        tempo = 1.0
        if source_duration > available_duration:
            tempo = source_duration / max(available_duration, 0.1)
            if tempo > maximum_tempo:
                failures.append(
                    {
                        "segment_id": segment_id,
                        "reason": (
                            "Generated speech still does not fit after reducing excessive silence, preserving breathing room, and using "
                            f"{borrowed_gap:.2f}s of the following real gap: "
                            f"{source_duration:.2f}s for {target_duration:.2f}s "
                            f"(would require {tempo:.2f}x; maximum is {maximum_tempo:.2f}x). "
                            "Shorten only this translated segment."
                        ),
                    }
                )
                continue
            try:
                _apply_natural_tempo(path, tempo)
            except RuntimeError as exc:
                failures.append({"segment_id": segment_id, "reason": str(exc)[-600:]})
                continue

        # A tiny edge fade remains only as electrical click protection. Because
        # the WAV now retains real silence, this envelope never touches speech.
        _declick_wav_edges(path)

        adjusted_duration = source_duration / tempo
        used_borrow = max(0.0, adjusted_duration - target_duration)
        underfill = max(0.0, target_duration - adjusted_duration)
        scheduled.append(
            {
                **item,
                "source_duration": round(source_duration, 4),
                "timeline_start": round(ideal_start, 4),
                "timeline_end": round(ideal_start + adjusted_duration, 4),
                "target_duration": round(target_duration, 4),
                "available_duration": round(available_duration, 4),
                "scheduled_duration": round(adjusted_duration, 4),
                "borrowed_gap_seconds": round(used_borrow, 4),
                "underfill_seconds": round(underfill, 4),
                "tempo_ratio": round(tempo, 4),
                "duration_fitted": tempo > 1.001,
                "strict_timeline": True,
                "sync_policy": "segment-anchor-with-real-gap-borrow",
            }
        )
    return scheduled, failures

def _assemble_voiceover_track(
    takes: list[dict[str, Any]],
    segments: list[SegmentRecord],
    output_path: Path,
) -> float:
    """Place synchronized PCM takes on one project-length mono WAV timeline."""
    segment_by_id = {segment.id: segment for segment in segments}
    selected = [
        (take, segment_by_id.get(str(take.get("segment_id") or "")))
        for take in takes
    ]
    selected = [
        (take, segment)
        for take, segment in selected
        if segment is not None and Path(str(take.get("path") or "")).is_file()
    ]
    if not selected:
        raise RuntimeError("No readable voice take is available for the voice-over track")
    sample_rate = 24000
    duration = max(
        float(take.get("timeline_end") or _timestamp_seconds(segment.end))
        for take, segment in selected
    )
    total_frames = max(1, round(duration * sample_rate))
    mixed = array("h", [0]) * total_frames
    for take, segment in selected:
        take_path = Path(str(take["path"]))
        try:
            with wave.open(str(take_path), "rb") as source:
                if (
                    source.getframerate() != sample_rate
                    or source.getnchannels() != 1
                    or source.getsampwidth() != 2
                ):
                    raise RuntimeError(
                        f"Unsupported take format for {take_path.name}; expected mono PCM16 at 24 kHz"
                    )
                samples = array("h")
                samples.frombytes(source.readframes(source.getnframes()))
                # V9: mix the complete take unchanged.
        except (OSError, wave.Error) as exc:
            raise RuntimeError(f"Cannot assemble {take_path.name}: {exc}") from exc
        timeline_start = float(
            take.get("timeline_start") or _timestamp_seconds(segment.start)
        )
        offset = max(0, round(timeline_start * sample_rate))
        available = min(len(samples), total_frames - offset)
        for index in range(max(0, available)):
            target = offset + index
            mixed[target] = max(
                -32768,
                min(32767, int(mixed[target]) + int(samples[index])),
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp.wav")
    with wave.open(str(temporary), "wb") as destination:
        destination.setnchannels(1)
        destination.setsampwidth(2)
        destination.setframerate(sample_rate)
        destination.writeframes(mixed.tobytes())
    os.replace(temporary, output_path)
    return round(total_frames / sample_rate, 4)


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
