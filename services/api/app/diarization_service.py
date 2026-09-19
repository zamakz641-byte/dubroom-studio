from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import PATHS


ENGINE_ID = "pyannote-community"
MODEL_REPO = "pyannote/speaker-diarization-community-1"
SHERPA_ENGINE_ID = "sherpa-diarization"
SPEAKER_META_ENGINE_ID = "speaker-eres2netv2"
SPEAKER_META_MODEL_REPO = "iic/speech_eres2netv2_sv_zh-cn_16k-common"
SPEAKER_META_REVISION = "ERES2NETV2_CHINESE_DEMOGRAPHICS_R1"
MANIFEST_VERSION = 1
SHERPA_DEFAULT_CLUSTER_THRESHOLD = 0.92
MIN_SPEAKER_TOTAL_SECONDS = 0.75
PALETTE = ["#7C5CFC", "#2FB7A8", "#F59E0B", "#EC4899", "#3B82F6", "#84CC16", "#F97316", "#A855F7"]


class DiarizationCancelled(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(project_dir: Path) -> dict[str, Path]:
    root = project_dir / "analysis" / "diarization"
    return {
        "root": root,
        "source": project_dir / "audio" / "separation" / "vocals.wav",
        "prepared": root / "vocals-16k-mono.wav",
        "prepared_manifest": root / "prepared.json",
        "manifest": root / "diarization-manifest.json",
        "output": root / "worker.output.json",
        "progress": root / "worker.progress.json",
        "stdout": root / "worker.log",
        "stderr": root / "worker.err.log",
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _environment_python(root: Path) -> Path:
    nested = root / "venv" / "Scripts" / "python.exe"
    return nested if nested.is_file() else root / "Scripts" / "python.exe"


def _speaker_meta_runtime() -> dict[str, Any]:
    env_root = PATHS.environments / SPEAKER_META_ENGINE_ID
    ready = _read_json(env_root / "ready.json")
    python = Path(str(ready.get("python_path") or ""))
    packages = env_root / "packages"
    cache_dir = PATHS.models / SPEAKER_META_ENGINE_ID / "cache"
    worker = PATHS.installers / "run-eres2netv2-speaker-meta.py"
    head = PATHS.models / SPEAKER_META_ENGINE_ID / "demographic_head.joblib"
    return {"python": python, "packages": packages, "cache_dir": cache_dir, "worker": worker, "head": head, "ready": python.is_file() and packages.is_dir() and worker.is_file()}


def _merge_speaker_intelligence(*, prepared_audio: Path, worker_output: Path, result: dict[str, Any], analysis_root: Path) -> dict[str, Any]:
    runtime = _speaker_meta_runtime()
    status: dict[str, Any] = {"model": SPEAKER_META_MODEL_REPO, "status": "unavailable"}
    if not runtime["ready"]:
        result["speaker_meta"] = status
        return result
    output_path = analysis_root / "speaker-intelligence.output.json"
    stdout_path = analysis_root / "speaker-intelligence.log"
    stderr_path = analysis_root / "speaker-intelligence.err.log"
    output_path.unlink(missing_ok=True)
    command = [str(runtime["python"]), str(runtime["worker"]), "--input", str(prepared_audio), "--diarization-json", str(worker_output), "--packages", str(runtime["packages"]), "--cache-dir", str(runtime["cache_dir"]), "--head", str(runtime["head"]), "--analysis-root", str(analysis_root), "--output", str(output_path), "--device", "cuda:0"]
    try:
        with stdout_path.open("w", encoding="utf-8") as stdout_file, stderr_path.open("w", encoding="utf-8") as stderr_file:
            process = subprocess.run(command, cwd=str(PATHS.workspace), stdout=stdout_file, stderr=stderr_file, text=True, timeout=2400)
        if process.returncode != 0 or not output_path.is_file():
            raise RuntimeError(stderr_path.read_text(encoding="utf-8", errors="replace")[-1600:] if stderr_path.is_file() else f"speaker intelligence exited with {process.returncode}")
        meta = _read_json(output_path)
        meta_profiles = {str(item.get("speaker") or ""): item for item in (meta.get("speaker_profiles") or []) if isinstance(item, dict) and str(item.get("speaker") or "")}
        existing = [item for item in (result.get("speaker_profiles") or []) if isinstance(item, dict)]
        by_speaker = {str(item.get("speaker") or ""): dict(item) for item in existing if str(item.get("speaker") or "")}
        for speaker, extra in meta_profiles.items(): by_speaker.setdefault(speaker, {"speaker": speaker}).update(extra)
        result["speaker_profiles"] = [by_speaker[key] for key in sorted(by_speaker)]
        status = {"model": SPEAKER_META_MODEL_REPO, "status": "completed", "analyzed_speaker_count": int(meta.get("analyzed_speaker_count") or 0), "demographic_head_loaded": bool(meta.get("demographic_head_loaded")), "device": str(meta.get("device") or "")}
    except Exception as exc:
        status = {"model": SPEAKER_META_MODEL_REPO, "status": "failed", "error": str(exc)[-1600:]}
    result["speaker_meta"] = status
    return result


def _model_path() -> Path | None:
    candidates: list[Path] = []
    model_root = PATHS.models / ENGINE_ID
    for manifest_path in (
        model_root / "model.json",
        PATHS.environments / ENGINE_ID / "ready.json",
    ):
        manifest = _read_json(manifest_path)
        for key in ("model_path", "snapshot"):
            raw = str(manifest.get(key) or "").strip()
            if raw:
                candidates.append(Path(raw))
    candidates.extend([model_root / "snapshot", model_root / "model"])
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except OSError:
            continue
        if resolved.is_dir() and (resolved / "config.yaml").is_file():
            return resolved
    return None


def runtime_status() -> dict[str, Any]:
    sherpa_root = PATHS.environments / SHERPA_ENGINE_ID
    sherpa_python = _environment_python(sherpa_root)
    sherpa_model = PATHS.models / SHERPA_ENGINE_ID
    sherpa_segmentation = sherpa_model / "segmentation" / "model.int8.onnx"
    sherpa_embedding = sherpa_model / "nemo_en_titanet_small.onnx"
    sherpa_worker = PATHS.installers / "run-sherpa-diarization.py"
    if (
        sherpa_python.is_file()
        and sherpa_segmentation.is_file()
        and sherpa_segmentation.stat().st_size > 1_000_000
        and sherpa_embedding.is_file()
        and sherpa_embedding.stat().st_size > 40_000_000
        and sherpa_worker.is_file()
    ):
        return {
            "engine_id": SHERPA_ENGINE_ID,
            "model_repo": "k2-fsa/sherpa-onnx speaker diarization models",
            "python": str(sherpa_python),
            "execution_provider": "sherpa-onnx",
            "shared_runtime": False,
            "device": "cpu",
            "runtime_ready": True,
            "model_ready": True,
            "model_path": str(sherpa_model),
            "worker": str(sherpa_worker),
            "adapter_ready": True,
            "usable": True,
            "requires_hf_token": False,
            "message": "Détection multispeaker locale prête, sans jeton Hugging Face",
        }
    dedicated_root = PATHS.environments / ENGINE_ID
    shared_root = PATHS.environments / "whisperx-alignment"
    dedicated_python = _environment_python(dedicated_root)
    shared_python = _environment_python(shared_root)
    dedicated_package = dedicated_root / "venv" / "Lib" / "site-packages" / "pyannote" / "audio"
    shared_package = shared_root / "venv" / "Lib" / "site-packages" / "pyannote" / "audio"

    if dedicated_python.is_file() and dedicated_package.is_dir():
        python_executable = dedicated_python
        provider = ENGINE_ID
        device = str(_read_json(dedicated_root / "ready.json").get("device") or "cpu")
    elif shared_python.is_file() and shared_package.is_dir():
        python_executable = shared_python
        provider = "whisperx-alignment"
        device = "cpu"
    else:
        python_executable = dedicated_python
        provider = ENGINE_ID
        device = "cpu"

    model_path = _model_path()
    worker = PATHS.installers / "run-speaker-diarization.py"
    runtime_ready = python_executable.is_file() and (
        dedicated_package.is_dir() or shared_package.is_dir()
    )
    model_ready = bool(model_path)
    return {
        "engine_id": ENGINE_ID,
        "model_repo": MODEL_REPO,
        "python": str(python_executable),
        "execution_provider": provider,
        "shared_runtime": provider != ENGINE_ID,
        "device": device if device in {"cpu", "cuda"} else "cpu",
        "runtime_ready": runtime_ready,
        "model_ready": model_ready,
        "model_path": str(model_path) if model_path else None,
        "worker": str(worker),
        "adapter_ready": worker.is_file(),
        "usable": runtime_ready and model_ready and worker.is_file(),
        "requires_hf_token": not model_ready,
        "message": (
            "Pyannote is ready and reuses the WhisperX runtime"
            if runtime_ready and model_ready and provider == "whisperx-alignment"
            else "Pyannote is ready"
            if runtime_ready and model_ready
            else "The shared Pyannote runtime is ready; install the local Community-1 model"
            if runtime_ready
            else "Install the Pyannote speaker engine"
        ),
    }


def _speaker_duration_totals(turns: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        speaker = str(turn.get("speaker") or "")
        if not speaker:
            continue
        try:
            start = float(turn.get("start") or 0.0)
            end = float(turn.get("end") or start)
        except (TypeError, ValueError):
            continue
        totals[speaker] = totals.get(speaker, 0.0) + max(0.0, end - start)
    return totals


def _filter_micro_clusters(
    turns: list[dict[str, Any]],
    speakers: list[str],
    speaker_profiles: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Drop tiny acoustic clusters without losing the discarded evidence.

    Sherpa can occasionally create a cluster for a short breath, SFX residue or
    a fragment of another speaker.  Those clusters should not become cast
    members or consume a voice profile.
    """
    totals = _speaker_duration_totals(turns)
    usable = [
        speaker
        for speaker in speakers
        if totals.get(str(speaker), 0.0) >= MIN_SPEAKER_TOTAL_SECONDS
    ]
    usable_set = set(usable)
    filtered_turns = [
        turn for turn in turns
        if isinstance(turn, dict) and str(turn.get("speaker") or "") in usable_set
    ]
    profiles = [
        item for item in (speaker_profiles or [])
        if isinstance(item, dict) and str(item.get("speaker") or "") in usable_set
    ]
    discarded_speakers = [speaker for speaker in speakers if speaker not in usable_set]
    discarded_set = set(discarded_speakers)
    discarded_turns = [
        turn for turn in turns
        if isinstance(turn, dict) and str(turn.get("speaker") or "") in discarded_set
    ]
    return filtered_turns, usable, profiles, discarded_speakers, discarded_turns


def _fingerprint(source_path: Path, model_path: Path, options: dict[str, Any]) -> str:
    source_stat = source_path.stat()
    config = model_path / "config.yaml"
    if not config.is_file():
        config = model_path / "segmentation" / "model.int8.onnx"
    model_stat = config.stat()
    payload = {
        "version": MANIFEST_VERSION,
        "speaker_meta_revision": SPEAKER_META_REVISION,
        "source": str(source_path.resolve()),
        "source_size": source_stat.st_size,
        "source_mtime_ns": source_stat.st_mtime_ns,
        "model": str(model_path.resolve()),
        "model_config_size": model_stat.st_size,
        "model_config_mtime_ns": model_stat.st_mtime_ns,
        "min_speakers": int(options.get("min_speakers") or 0),
        "max_speakers": int(options.get("max_speakers") or 0),
        "cluster_threshold": float(options.get("cluster_threshold") or SHERPA_DEFAULT_CLUSTER_THRESHOLD),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def status(project_dir: Path) -> dict[str, Any]:
    paths = _paths(project_dir)
    manifest = _read_json(paths["manifest"])
    state = str(manifest.get("status") or "not_processed")
    turns = manifest.get("turns") if isinstance(manifest.get("turns"), list) else []
    manifest_speakers = [
        str(item) for item in (manifest.get("speakers") or []) if str(item)
    ]
    filtered_turns, usable_speakers, _profiles, discarded_speakers, _discarded_turns = _filter_micro_clusters(
        turns,
        manifest_speakers,
        manifest.get("speaker_profiles") if isinstance(manifest.get("speaker_profiles"), list) else [],
    )
    # New manifests already contain filtered turns.  The dynamic filter above
    # also fixes the UI count for older manifests produced before this patch.
    return {
        "version": int(manifest.get("version") or MANIFEST_VERSION),
        "status": state,
        "progress": int(manifest.get("progress") or (100 if state == "ready" else 0)),
        "message": str(manifest.get("message") or ""),
        "error": manifest.get("error"),
        "speaker_count": len(usable_speakers) if state == "ready" else int(manifest.get("speaker_count") or 0),
        "raw_speaker_count": int(manifest.get("raw_speaker_count") or (len(manifest_speakers) if state == "ready" else 0)),
        "turn_count": len(filtered_turns) if state == "ready" else len(turns),
        "speakers": usable_speakers if state == "ready" else manifest_speakers,
        "discarded_speakers": manifest.get("discarded_speakers") or discarded_speakers,
        "turns": filtered_turns if state == "ready" else turns,
        "duration": manifest.get("duration"),
        "elapsed_seconds": manifest.get("elapsed_seconds"),
        "cache_hit": bool(manifest.get("cache_hit", False)),
        "source_path": str(paths["source"]) if paths["source"].is_file() else None,
        "manifest_path": str(paths["manifest"]),
        "runtime": runtime_status(),
        "created_at": manifest.get("created_at"),
        "updated_at": manifest.get("updated_at"),
    }


def _prepare_audio(source: Path, target: Path, is_cancelled: Callable[[], bool] | None) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required to prepare the vocal track for speaker detection")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.stem}.tmp.wav")
    process = subprocess.Popen(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(temporary)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    while process.poll() is None:
        if is_cancelled and is_cancelled():
            process.terminate()
            raise DiarizationCancelled("Speaker detection cancelled")
        time.sleep(0.2)
    _stdout, stderr = process.communicate()
    if process.returncode != 0 or not temporary.is_file():
        raise RuntimeError(f"Unable to prepare vocal track: {stderr[-1200:]}")
    temporary.replace(target)


def run(
    project_dir: Path,
    options: dict[str, Any] | None = None,
    *,
    on_progress: Callable[[int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    options = options or {}
    paths = _paths(project_dir)
    paths["root"].mkdir(parents=True, exist_ok=True)
    source = paths["source"]
    if not source.is_file():
        raise RuntimeError("Run Audio Preservation first: the isolated vocals.wav track is required")

    runtime = runtime_status()
    if not runtime["runtime_ready"]:
        raise RuntimeError("Installez la détection multispeaker locale depuis Moteurs")
    if not runtime["model_ready"]:
        raise RuntimeError(
            "Installez Sherpa Diarization depuis Moteurs, ou fournissez le modèle Pyannote Community-1"
        )
    if not runtime["adapter_ready"]:
        raise RuntimeError("The speaker diarization adapter is missing")

    model_path = Path(str(runtime["model_path"]))
    fingerprint = _fingerprint(source, model_path, options)
    previous = _read_json(paths["manifest"])
    # DUBROOM_DIARIZATION_RESUME_COMPLETED_V1
    # On Windows the Sherpa child process can finish even if the parent API/job
    # was interrupted or restarted. In that case worker.output.json is valid
    # while diarization-manifest.json is still "running". Recover it before
    # deleting/restarting the worker.
    recovered_output = _read_json(paths["output"])
    if (
        not bool(options.get("force"))
        and previous.get("fingerprint") == fingerprint
        and str(previous.get("status") or "") in {"running", "failed"}
        and recovered_output.get("status") == "completed"
        and isinstance(recovered_output.get("turns"), list)
        and bool(recovered_output.get("turns"))
        and isinstance(recovered_output.get("speakers"), list)
        and bool(recovered_output.get("speakers"))
    ):
        recovered_turns = recovered_output.get("turns") or []
        recovered_speakers = recovered_output.get("speakers") or []
        recovered = {
            **previous,
            "version": MANIFEST_VERSION,
            "status": "ready",
            "progress": 100,
            "message": f"Detected {len(recovered_speakers)} speaker(s) across {len(recovered_turns)} turn(s) (recovered)",
            "speaker_count": len(recovered_speakers),
            "speakers": recovered_speakers,
            "speaker_profiles": recovered_output.get("speaker_profiles") or [],
            "turns": recovered_turns,
            "regular_turns": recovered_output.get("regular_turns") or [],
            "duration": recovered_output.get("duration"),
            "elapsed_seconds": recovered_output.get("elapsed_seconds"),
            "device": recovered_output.get("device"),
            "execution_provider": runtime.get("execution_provider"),
            "cache_hit": True,
            "recovered_worker_output": True,
            "updated_at": _now(),
        }
        _write_json_atomic(paths["manifest"], recovered)
        if on_progress:
            on_progress(100, "Speaker detection recovered from completed Sherpa output")
        return {
            "status": "completed",
            "message": recovered["message"],
            "manifest": recovered,
            "artifacts": {
                "diarization_manifest": str(paths["manifest"]),
                "diarization_log": str(paths["stderr"]),
            },
        }

    if (
        not bool(options.get("force"))
        and previous.get("status") == "ready"
        and previous.get("fingerprint") == fingerprint
        and isinstance(previous.get("turns"), list)
    ):
        previous["cache_hit"] = True
        previous["updated_at"] = _now()
        _write_json_atomic(paths["manifest"], previous)
        if on_progress:
            on_progress(100, "Speaker detection restored from project cache")
        return {
            "status": "completed",
            "message": f"Detected {int(previous.get('speaker_count') or 0)} speaker(s) (cache)",
            "manifest": previous,
            "artifacts": {"diarization_manifest": str(paths["manifest"])},
        }

    started_at = _now()
    running = {
        "version": MANIFEST_VERSION,
        "status": "running",
        "progress": 2,
        "message": "Preparing isolated vocals for speaker detection",
        "fingerprint": fingerprint,
        "source_path": str(source),
        "created_at": previous.get("created_at") or started_at,
        "updated_at": started_at,
    }
    _write_json_atomic(paths["manifest"], running)
    try:
        if on_progress:
            on_progress(3, running["message"])
        prepared_fingerprint = hashlib.sha256(
            f"{source.stat().st_size}:{source.stat().st_mtime_ns}".encode("ascii")
        ).hexdigest()
        prepared_state = _read_json(paths["prepared_manifest"])
        if prepared_state.get("fingerprint") != prepared_fingerprint or not paths["prepared"].is_file():
            _prepare_audio(source, paths["prepared"], is_cancelled)
            _write_json_atomic(paths["prepared_manifest"], {"fingerprint": prepared_fingerprint, "path": str(paths["prepared"]), "updated_at": _now()})

        for disposable in (paths["output"], paths["progress"]):
            disposable.unlink(missing_ok=True)
        command = [
            str(runtime["python"]),
            str(runtime["worker"]),
            "--input", str(paths["prepared"]),
            "--model-path", str(model_path),
            "--output", str(paths["output"]),
            "--progress-file", str(paths["progress"]),
            "--device", str(runtime["device"]),
        ]
        min_speakers = int(options.get("min_speakers") or 0)
        max_speakers = int(options.get("max_speakers") or 0)
        if min_speakers > 0:
            command.extend(["--min-speakers", str(min_speakers)])
        if max_speakers > 0:
            command.extend(["--max-speakers", str(max_speakers)])
        if runtime.get("engine_id") == SHERPA_ENGINE_ID:
            command.extend([
                "--cluster-threshold",
                str(float(options.get("cluster_threshold") or SHERPA_DEFAULT_CLUSTER_THRESHOLD)),
            ])

        env = os.environ.copy()
        if runtime.get("engine_id") != SHERPA_ENGINE_ID:
            env.update({
                "HF_HOME": str(PATHS.cache / "huggingface"),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_HUB_DISABLE_TELEMETRY": "1",
            })
        with paths["stdout"].open("w", encoding="utf-8") as stdout_file, paths["stderr"].open("w", encoding="utf-8") as stderr_file:
            process = subprocess.Popen(command, cwd=str(PATHS.workspace), env=env, stdout=stdout_file, stderr=stderr_file, text=True)
            last_progress = ""
            while process.poll() is None:
                if is_cancelled and is_cancelled():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise DiarizationCancelled("Speaker detection cancelled")
                progress_payload = _read_json(paths["progress"])
                serialized = json.dumps(progress_payload, sort_keys=True)
                if progress_payload and serialized != last_progress:
                    worker_progress = int(progress_payload.get("progress") or 0)
                    mapped = 7 + round(worker_progress * 0.90)
                    detail = str(progress_payload.get("message") or "Detecting speakers")
                    running.update({"progress": mapped, "message": detail, "updated_at": _now()})
                    _write_json_atomic(paths["manifest"], running)
                    if on_progress:
                        on_progress(mapped, detail)
                    last_progress = serialized
                time.sleep(0.4)
            return_code = process.returncode

        if return_code != 0 or not paths["output"].is_file():
            stderr = paths["stderr"].read_text(encoding="utf-8", errors="replace") if paths["stderr"].is_file() else ""
            engine_name = "Sherpa" if runtime.get("engine_id") == SHERPA_ENGINE_ID else "Pyannote"
            raise RuntimeError(f"{engine_name} speaker detection failed: {stderr[-1800:]}")
        result = _read_json(paths["output"])
        if runtime.get("engine_id") == SHERPA_ENGINE_ID:
            if on_progress:
                on_progress(97, "ERes2NetV2: embeddings et profil locuteur")
            result = _merge_speaker_intelligence(
                prepared_audio=paths["prepared"],
                worker_output=paths["output"],
                result=result,
                analysis_root=paths["root"],
            )
        raw_turns = result.get("turns") if isinstance(result.get("turns"), list) else []
        raw_speakers = [
            str(item) for item in (result.get("speakers") or []) if str(item)
        ]
        raw_profiles = result.get("speaker_profiles") if isinstance(result.get("speaker_profiles"), list) else []
        turns, speakers, speaker_profiles, discarded_speakers, discarded_turns = _filter_micro_clusters(
            raw_turns,
            raw_speakers,
            raw_profiles,
        )
        detail = f"Detected {len(speakers)} usable speaker(s) across {len(turns)} turn(s)"
        if discarded_speakers:
            detail += f" ({len(discarded_speakers)} micro-cluster(s) filtered)"
        completed = {
            **running,
            "status": "ready",
            "progress": 100,
            "message": detail,
            "speaker_count": len(speakers),
            "speakers": speakers,
            "speaker_profiles": speaker_profiles,
            "turns": turns,
            "regular_turns": turns,
            "raw_speaker_count": len(raw_speakers),
            "raw_speakers": raw_speakers,
            "discarded_speakers": discarded_speakers,
            "discarded_turns": discarded_turns,
            "min_speaker_total_seconds": MIN_SPEAKER_TOTAL_SECONDS,
            "cluster_threshold": float(options.get("cluster_threshold") or SHERPA_DEFAULT_CLUSTER_THRESHOLD),
            "duration": result.get("duration"),
            "elapsed_seconds": result.get("elapsed_seconds"),
            "device": result.get("device"),
            "execution_provider": runtime.get("execution_provider"),
            "cache_hit": False,
            "updated_at": _now(),
        }
        _write_json_atomic(paths["manifest"], completed)
        if on_progress:
            on_progress(100, completed["message"])
        return {
            "status": "completed",
            "message": completed["message"],
            "manifest": completed,
            "artifacts": {
                "diarization_manifest": str(paths["manifest"]),
                "diarization_log": str(paths["stderr"]),
            },
        }
    except DiarizationCancelled:
        running.update({"status": "cancelled", "message": "Speaker detection cancelled", "updated_at": _now()})
        _write_json_atomic(paths["manifest"], running)
        raise
    except Exception as exc:
        running.update({"status": "failed", "progress": 100, "message": "Speaker detection failed", "error": str(exc), "updated_at": _now()})
        _write_json_atomic(paths["manifest"], running)
        raise


def _seconds(timestamp: str) -> float:
    parts = str(timestamp or "0").replace(",", ".").split(":")
    try:
        if len(parts) == 3:
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


def _format_duration(seconds: float) -> str:
    total = max(0, round(seconds))
    minutes, remainder = divmod(total, 60)
    return f"{minutes}m {remainder:02d}s" if minutes else f"{remainder}s"


def apply_to_analysis(
    speakers: list[Any],
    segments: list[Any],
    manifest: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_turns = [item for item in manifest.get("turns", []) if isinstance(item, dict)]
    raw_speakers = [str(item) for item in manifest.get("speakers", []) if str(item)]
    if not raw_turns or not raw_speakers:
        return [], []

    filtered_turns, usable_raw, _profiles, _discarded, _discarded_turns = _filter_micro_clusters(
        raw_turns,
        raw_speakers,
        manifest.get("speaker_profiles") if isinstance(manifest.get("speaker_profiles"), list) else [],
    )
    if not filtered_turns or not usable_raw:
        return [], []

    traits_by_raw = {
        str(item.get("speaker") or ""): item
        for item in (manifest.get("speaker_profiles") or [])
        if isinstance(item, dict)
    }
    duration_by_raw = _speaker_duration_totals(filtered_turns)
    ordered_raw = sorted(
        usable_raw,
        key=lambda value: min(
            (
                float(turn.get("start") or 0)
                for turn in filtered_turns
                if str(turn.get("speaker")) == value
            ),
            default=10**12,
        ),
    )

    existing_by_name = {
        str(getattr(item, "name", "")): item
        for item in speakers
        if str(getattr(item, "name", ""))
    }

    # Re-diarization must not silently shuffle voice identities.  Match new
    # acoustic clusters to the previous speaker labels using timestamp overlap
    # before creating any new display names.
    overlap_by_pair: dict[tuple[str, str], float] = {}
    for raw in ordered_raw:
        raw_turns_for_speaker = [
            turn for turn in filtered_turns if str(turn.get("speaker") or "") == raw
        ]
        for segment in segments:
            previous_name = str(getattr(segment, "speaker", "") or "")
            if not previous_name or previous_name not in existing_by_name:
                continue
            seg_start = _seconds(str(getattr(segment, "start", "0")))
            seg_end = max(seg_start + 0.01, _seconds(str(getattr(segment, "end", "0"))))
            overlap = 0.0
            for turn in raw_turns_for_speaker:
                turn_start = float(turn.get("start") or 0.0)
                turn_end = float(turn.get("end") or turn_start)
                overlap += max(0.0, min(seg_end, turn_end) - max(seg_start, turn_start))
            if overlap > 0:
                overlap_by_pair[(raw, previous_name)] = (
                    overlap_by_pair.get((raw, previous_name), 0.0) + overlap
                )

    display_by_raw: dict[str, str] = {}
    claimed_existing: set[str] = set()
    for (raw, previous_name), score in sorted(
        overlap_by_pair.items(),
        key=lambda item: item[1],
        reverse=True,
    ):
        if score < 0.25 or raw in display_by_raw or previous_name in claimed_existing:
            continue
        display_by_raw[raw] = previous_name
        claimed_existing.add(previous_name)

    used_names = set(display_by_raw.values())
    next_index = 1
    for raw in ordered_raw:
        if raw in display_by_raw:
            continue
        while f"Speaker {next_index}" in used_names:
            next_index += 1
        display_by_raw[raw] = f"Speaker {next_index}"
        used_names.add(display_by_raw[raw])
        next_index += 1

    next_speakers: list[dict[str, Any]] = []
    for index, raw in enumerate(ordered_raw):
        name = display_by_raw[raw]
        existing = existing_by_name.get(name)
        traits = traits_by_raw.get(raw, {})
        detected_gender = str(traits.get("gender") or "unspecified")
        next_speakers.append({
            "name": name,
            "role": (
                getattr(existing, "role", None)
                or (
                    "Detected female speaker" if detected_gender == "female"
                    else "Detected male speaker" if detected_gender == "male"
                    else "Detected speaker"
                )
            ),
            "duration": _format_duration(duration_by_raw.get(raw, 0.0)),
            "color": getattr(existing, "color", None) or PALETTE[index % len(PALETTE)],
            "level": int(getattr(existing, "level", 82) or 82),
            "voice_profile_id": getattr(existing, "voice_profile_id", None),
            "voice_engine": getattr(existing, "voice_engine", None),
            "voice_model": getattr(existing, "voice_model", None),
            "voice_instruct": getattr(existing, "voice_instruct", None),
            "effects_chain": list(getattr(existing, "effects_chain", []) or []),
        })

    color_by_name = {item["name"]: item["color"] for item in next_speakers}
    raw_index = {raw: index for index, raw in enumerate(ordered_raw)}
    next_segments: list[dict[str, Any]] = []
    for segment in segments:
        start = _seconds(str(getattr(segment, "start", "0")))
        end = max(start + 0.01, _seconds(str(getattr(segment, "end", "0"))))
        center = (start + end) / 2
        best_raw: str | None = None
        best_score = (-1.0, float("-inf"))
        for turn in filtered_turns:
            raw = str(turn.get("speaker") or "")
            if raw not in display_by_raw:
                continue
            turn_start = float(turn.get("start") or 0)
            turn_end = float(turn.get("end") or turn_start)
            overlap = max(0.0, min(end, turn_end) - max(start, turn_start))
            distance = (
                0.0
                if turn_start <= center <= turn_end
                else min(abs(center - turn_start), abs(center - turn_end))
            )
            score = (overlap, -distance)
            if score > best_score:
                best_raw = raw
                best_score = score

        # No usable turn should normally be missing, but preserve the previous
        # assignment rather than inventing Speaker 1 if there is no evidence.
        previous_name = str(getattr(segment, "speaker", "") or "")
        if best_raw is None:
            if previous_name in color_by_name:
                assigned_name = previous_name
                lane = next(
                    (
                        raw_index[raw] % 3
                        for raw, name in display_by_raw.items()
                        if name == previous_name
                    ),
                    int(getattr(segment, "lane", 0) or 0),
                )
            else:
                assigned_name = next_speakers[0]["name"]
                lane = 0
        else:
            assigned_name = display_by_raw[best_raw]
            lane = raw_index[best_raw] % 3

        payload = segment.model_dump() if hasattr(segment, "model_dump") else dict(segment)
        payload.update({
            "speaker": assigned_name,
            "color": color_by_name[assigned_name],
            "lane": lane,
        })
        next_segments.append(payload)
    return next_speakers, next_segments

