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
from uuid import uuid4

from .config import PATHS
from .shared_dependency_service import resolve_shared_dependencies


ENGINE_ID = "demucs-separation"
DEFAULT_MODEL = "htdemucs"
CINEMATIC_ENGINE_ID = "cinematic-separation"
CINEMATIC_MODEL = "bandit-v2-dnr3-multilingual"
MANIFEST_VERSION = 1
TRACK_NAMES = {"original", "vocals", "bed"}
_RUNTIME_CACHE: tuple[float, dict[str, Any]] | None = None
_RUNTIME_CACHE_TTL_SECONDS = 300


class AudioPreservationCancelled(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(project_dir: Path) -> dict[str, Path]:
    audio_root = project_dir / "audio"
    separation = audio_root / "separation"
    return {
        "audio_root": audio_root,
        "source_dir": audio_root / "source",
        "separation_dir": separation,
        "original": audio_root / "source" / "original.wav",
        "vocals": separation / "vocals.wav",
        "bed": separation / "bed.wav",
        "music": separation / "music.wav",
        "sfx": separation / "sfx.wav",
        "manifest": separation / "separation-manifest.json",
        "legacy_manifest": audio_root / "separation-manifest.json",
        "input": separation / "worker.input.json",
        "output": separation / "worker.output.json",
        "progress": separation / "worker.progress.json",
        "stdout": separation / "worker.log",
        "stderr": separation / "worker.err.log",
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
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _fingerprint(source_path: Path, options: dict[str, Any]) -> str:
    stat = source_path.stat()
    stable_options = {
        "engine": str(options.get("profile") or "cinema"),
        "model": str(options.get("model") or (CINEMATIC_MODEL if str(options.get("profile") or "cinema") == "cinema" else DEFAULT_MODEL)),
        "device": str(options.get("device") or "auto"),
        "segment": float(options.get("segment") or 7.0),
        "overlap": float(options.get("overlap") or 0.25),
        "shifts": int(options.get("shifts") or 1),
        "batch_size": int(options.get("batch_size") or 1),
        "hop_seconds": float(options.get("hop_seconds") or 2.0),
    }
    payload = {
        "version": MANIFEST_VERSION,
        "source": str(source_path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "options": stable_options,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _environment_python(environment: Path) -> Path:
    nested = environment / "venv" / "Scripts" / "python.exe"
    return nested if nested.is_file() else environment / "Scripts" / "python.exe"


def _cuda_runtime_candidates() -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    if not PATHS.environments.is_dir():
        return candidates
    for environment in PATHS.environments.iterdir():
        if not environment.is_dir() or environment.name == ENGINE_ID:
            continue
        python_executable = _environment_python(environment)
        venv_root = python_executable.parent.parent
        torch_version = venv_root / "Lib" / "site-packages" / "torch" / "version.py"
        if not python_executable.is_file() or not torch_version.is_file():
            continue
        version_text = torch_version.read_text(encoding="utf-8-sig", errors="replace").lower()
        if "+cu" not in version_text and "cuda: optional[str] = '" not in version_text:
            continue
        candidates.append((environment.name, python_executable))
    # DUBROOM_BANDIT_SAFE_TURBO_V2_2_RUNTIME
    candidates.sort(
        key=lambda item: (
            0 if "torch28" in item[0].lower() or "torch-28" in item[0].lower() else
            1 if "omnivoice" in item[0].lower() else
            2,
            item[0].lower(),
        )
    )
    return candidates


def _probe_cuda_runtime(
    python_executable: Path,
    shared_paths: list[str],
) -> dict[str, Any]:
    payload = json.dumps(shared_paths)
    code = ";".join([
        "import json,sys",
        f"[sys.path.append(p) for p in json.loads({payload!r}) if p not in sys.path]",
        "import numpy,torch,torchaudio,demucs.separate",
        "available=bool(torch.cuda.is_available())",
        "print(json.dumps({'available':available,'device_name':torch.cuda.get_device_name(0) if available else None,'torch':torch.__version__,'cuda':torch.version.cuda,'torchaudio':torchaudio.__version__,'numpy':numpy.__version__,'python_version':f'{sys.version_info.major}.{sys.version_info.minor}'}))",
    ])
    try:
        completed = subprocess.run(
            [str(python_executable), "-c", code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "error": str(exc)}
    if completed.returncode != 0:
        return {
            "available": False,
            "error": (completed.stderr or completed.stdout).strip()[-1200:],
        }
    try:
        result = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"available": False, "error": "CUDA probe returned unreadable output"}
    return result if isinstance(result, dict) else {"available": False}


def _runtime(*, refresh: bool = False) -> dict[str, Any]:
    global _RUNTIME_CACHE
    if (
        not refresh
        and _RUNTIME_CACHE
        and time.monotonic() - _RUNTIME_CACHE[0] < _RUNTIME_CACHE_TTL_SECONDS
    ):
        return _RUNTIME_CACHE[1]
    runtime_root = PATHS.environments / ENGINE_ID
    cpu_python = _environment_python(runtime_root)
    worker_path = PATHS.installers / "run-audio-separation.py"
    ready_path = runtime_root / "ready.json"
    python_executable = cpu_python
    execution_provider = ENGINE_ID
    dependencies = resolve_shared_dependencies(cpu_python, ["numpy"])
    acceleration: dict[str, Any] = {
        "device": "cpu",
        "device_name": "CPU",
        "torch": None,
        "cuda": None,
    }
    if ready_path.is_file() and worker_path.is_file():
        demucs_site = runtime_root / "venv" / "Lib" / "site-packages"
        for provider, candidate_python in _cuda_runtime_candidates():
            probe = _probe_cuda_runtime(
                candidate_python,
                [str(demucs_site)],
            )
            if not probe.get("available"):
                continue
            python_executable = candidate_python
            execution_provider = provider
            dependencies = {
                "status": "ready",
                "python": str(candidate_python),
                "python_version": probe.get("python_version"),
                "paths": [str(demucs_site)],
                "providers": {
                    "numpy": provider,
                    "demucs.separate": ENGINE_ID,
                },
                "missing": [],
                "error": "",
            }
            acceleration = {
                "device": "cuda",
                "device_name": probe.get("device_name"),
                "torch": probe.get("torch"),
                "cuda": probe.get("cuda"),
                "torchaudio": probe.get("torchaudio"),
            }
            break
    result = {
        "engine_id": ENGINE_ID,
        "runtime_root": str(runtime_root),
        "python": str(python_executable),
        "execution_provider": execution_provider,
        **acceleration,
        "worker": str(worker_path),
        "ready_manifest": str(ready_path),
        "installed": cpu_python.is_file() and ready_path.is_file(),
        "adapter_ready": worker_path.is_file(),
        "shared_dependencies": dependencies,
        "usable": (
            python_executable.is_file()
            and ready_path.is_file()
            and worker_path.is_file()
            and dependencies.get("status") == "ready"
        ),
    }
    _RUNTIME_CACHE = (time.monotonic(), result)
    return result


def _cinematic_runtime() -> dict[str, Any]:
    runtime_root = PATHS.environments / CINEMATIC_ENGINE_ID
    ready = _read_json(runtime_root / "ready.json")
    model_path = Path(str(ready.get("model_path") or PATHS.models / CINEMATIC_ENGINE_ID / "bandit-v2-dnr3-multilingual.ckpt"))
    source_path = Path(str(ready.get("source_path") or runtime_root / "bandit-v2"))
    worker = PATHS.installers / "run-cinematic-separation.py"
    candidates = _cuda_runtime_candidates()
    # DUBROOM_BANDIT_RUNTIME_SELECTOR_V2_4
    preferred_provider = 'tts-omnivoice-hq-torch28-v53'
    candidates.sort(
        key=lambda item: (
            0 if item[0] == preferred_provider else 1,
            item[0].lower(),
        )
    )
    python_executable = candidates[0][1] if candidates else _environment_python(runtime_root)
    usable = (
        python_executable.is_file()
        and model_path.is_file()
        and model_path.stat().st_size > 400_000_000
        and (source_path / "src" / "models" / "bandit" / "bandit.py").is_file()
        and worker.is_file()
    )
    return {
        "engine_id": CINEMATIC_ENGINE_ID,
        "runtime_root": str(runtime_root),
        "python": str(python_executable),
        "execution_provider": candidates[0][0] if candidates else CINEMATIC_ENGINE_ID,
        "device": "cuda" if candidates else "cpu",
        "device_name": "Shared CUDA GPU" if candidates else "CPU",
        "worker": str(worker),
        "model_path": str(model_path),
        "source_path": str(source_path),
        "installed": bool(ready) and model_path.is_file(),
        "adapter_ready": worker.is_file(),
        "shared_dependencies": {
            "status": "ready" if python_executable.is_file() else "missing",
            "python": str(python_executable),
            "paths": [],
            "providers": {"torch": candidates[0][0] if candidates else CINEMATIC_ENGINE_ID, "bandit": CINEMATIC_ENGINE_ID},
            "missing": [] if python_executable.is_file() else ["python"],
        },
        "usable": usable,
    }


def _selected_runtime(options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    profile = str(options.get("profile") or "cinema").strip().lower()
    cinematic = _cinematic_runtime()
    if profile == "cinema" and cinematic.get("usable"):
        return cinematic
    return _runtime()


def _shared_torch_cache() -> Path:
    configured = PATHS.cache / "torch"
    candidates = [
        configured,
        Path(os.environ["TORCH_HOME"]).expanduser() if os.environ.get("TORCH_HOME") else None,
        Path.home() / ".cache" / "torch",
        PATHS.cache / ENGINE_ID / "torch",
    ]
    for candidate in candidates:
        if candidate and any((candidate / "hub" / "checkpoints").glob("*.th")):
            return candidate.resolve()
    configured.mkdir(parents=True, exist_ok=True)
    return configured.resolve()


def _manifest(project_dir: Path) -> dict[str, Any]:
    paths = _paths(project_dir)
    manifest = _read_json(paths["manifest"])
    if not manifest:
        manifest = _read_json(paths["legacy_manifest"])
    return manifest


def status(project_dir: Path) -> dict[str, Any]:
    paths = _paths(project_dir)
    manifest = _manifest(project_dir)
    state = str(manifest.get("status") or "not_processed")
    backend = str(manifest.get("backend") or ENGINE_ID)
    selected_runtime = (
        _cinematic_runtime() if backend == CINEMATIC_ENGINE_ID else _runtime()
    )
    tracks = {
        name: str(paths[name]) if state == "ready" and paths[name].is_file() else None
        for name in TRACK_NAMES
    }
    return {
        "version": int(manifest.get("version") or MANIFEST_VERSION),
        "status": state,
        "progress": int(manifest.get("progress") or (100 if state == "ready" else 0)),
        "message": str(manifest.get("message") or ""),
        "error": manifest.get("error"),
        "backend": backend,
        "model": str(manifest.get("model") or DEFAULT_MODEL),
        "fingerprint": manifest.get("fingerprint"),
        "duration": manifest.get("duration"),
        "cache_hit": bool(manifest.get("cache_hit", False)),
        "created_at": manifest.get("created_at"),
        "updated_at": manifest.get("updated_at"),
        "tracks": tracks,
        "runtime": selected_runtime,
    }


def runtime_status(*, refresh: bool = False) -> dict[str, Any]:
    demucs = dict(_runtime(refresh=refresh))
    cinematic = _cinematic_runtime()
    active = cinematic if cinematic.get("usable") else demucs
    return {**active, "profiles": {"cinema": cinematic, "fast": demucs}}


def track_path(project_dir: Path, track: str) -> Path | None:
    if track not in TRACK_NAMES:
        return None
    current = status(project_dir)
    raw_path = (current.get("tracks") or {}).get(track)
    if current.get("status") != "ready" or not raw_path:
        return None
    path = Path(str(raw_path)).resolve()
    audio_root = (project_dir / "audio").resolve()
    return path if path.is_file() and audio_root in path.parents else None


def _run_process(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    stdout: Any = subprocess.PIPE,
    stderr: Any = subprocess.PIPE,
    cwd: Path | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        command,
        env=env,
        cwd=str(cwd) if cwd else None,
        stdout=stdout,
        stderr=stderr,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    while process.poll() is None:
        if is_cancelled and is_cancelled():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            raise AudioPreservationCancelled("Audio preservation cancelled")
        time.sleep(0.25)
    return process


def _extract_original(
    source_path: Path,
    output_path: Path,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for Audio Preservation")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    process = _run_process(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source_path),
            "-map",
            "0:a:0",
            "-vn",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ],
        is_cancelled=is_cancelled,
    )
    _, stderr = process.communicate()
    if process.returncode != 0 or not output_path.is_file():
        raise RuntimeError(f"FFmpeg could not extract the original audio: {stderr[-1200:]}")


def _duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("FFprobe is required to validate Audio Preservation")
    completed = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    try:
        value = float(completed.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"Unreadable audio artifact: {path.name}") from exc
    if completed.returncode != 0 or value <= 0:
        raise RuntimeError(f"Invalid audio artifact: {path.name}")
    return value


def _worker_command(
    runtime: dict[str, Any],
    source_path: Path,
    output_dir: Path,
    output_path: Path,
    progress_path: Path,
    options: dict[str, Any],
) -> list[str]:
    if runtime.get("engine_id") == CINEMATIC_ENGINE_ID:
        command = [
            str(runtime["python"]),
            str(runtime["worker"]),
            "--input", str(source_path),
            "--output-dir", str(output_dir),
            "--output", str(output_path),
            "--progress-file", str(progress_path),
            "--model-path", str(runtime["model_path"]),
            "--source-path", str(runtime["source_path"]),
            "--device", str(options.get("device") or "auto"),
            "--batch-size", str(int(options.get("batch_size") or 1)),
            "--hop-seconds", str(float(options.get("hop_seconds") or 2.0)),
        ]
        for shared_path in runtime.get("shared_dependencies", {}).get("paths", []):
            command.extend(["--shared-site-packages", str(shared_path)])
        return command
    command = [
        str(runtime["python"]),
        str(runtime["worker"]),
        "--input",
        str(source_path),
        "--output-dir",
        str(output_dir),
        "--output",
        str(output_path),
        "--progress-file",
        str(progress_path),
        "--model",
        str(options.get("model") or DEFAULT_MODEL),
        "--device",
        str(options.get("device") or "auto"),
        "--segment",
        str(float(options.get("segment") or 7.0)),
        "--overlap",
        str(float(options.get("overlap") or 0.25)),
        "--shifts",
        str(int(options.get("shifts") or 1)),
    ]
    for shared_path in runtime["shared_dependencies"].get("paths", []):
        command.extend(["--shared-site-packages", str(shared_path)])
    return command


def run(
    project_dir: Path,
    source_path: Path,
    options: dict[str, Any] | None = None,
    on_progress: Callable[[int, str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    options = dict(options or {})
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise RuntimeError("The project source video is missing")
    paths = _paths(project_dir)
    runtime = _selected_runtime(options)
    options["profile"] = (
        "cinema" if runtime.get("engine_id") == CINEMATIC_ENGINE_ID else "fast"
    )
    # DUBROOM_BANDIT_TURBO_V2
    if runtime.get("engine_id") == CINEMATIC_ENGINE_ID:
        options.setdefault("batch_size", 4)
        options.setdefault("hop_seconds", 4.0)
    fingerprint = _fingerprint(source_path, options)
    current = _manifest(project_dir)
    ready_files = all(paths[name].is_file() for name in TRACK_NAMES)
    if (
        not bool(options.get("force"))
        and current.get("status") == "ready"
        and current.get("fingerprint") == fingerprint
        and ready_files
    ):
        cached = dict(current)
        cached.update({"cache_hit": True, "updated_at": _now()})
        _write_json_atomic(paths["manifest"], cached)
        if on_progress:
            on_progress(99, "Audio Preservation cache reused")
        return {
            "status": "completed",
            "message": "Audio Preservation ready (shared cache reused)",
            "artifacts": {name: str(paths[name]) for name in TRACK_NAMES} | {"separation_manifest": str(paths["manifest"])},
            "manifest": cached,
        }

    if not runtime["usable"]:
        missing = runtime["shared_dependencies"].get("missing", [])
        detail = f" Missing shared dependencies: {', '.join(missing)}." if missing else ""
        raise RuntimeError(
            "Audio Separation is installed but its reusable runtime is not callable. "
            "Repair Bandit Cinéma or Demucs from Engines."
            + detail
        )

    paths["source_dir"].mkdir(parents=True, exist_ok=True)
    paths["separation_dir"].mkdir(parents=True, exist_ok=True)
    run_token = uuid4().hex[:10]
    staging = paths["separation_dir"] / f".staging-{run_token}"
    staging.mkdir(parents=True, exist_ok=True)
    staged_original = staging / "original.wav"
    staged_output = staging / "worker.output.json"
    staged_progress = staging / "worker.progress.json"
    started_at = _now()
    running_manifest = {
        "version": MANIFEST_VERSION,
        "status": "running",
        "progress": 2,
        "message": "Preparing Audio Preservation",
        "error": None,
        "backend": str(runtime.get("engine_id") or ENGINE_ID),
        "model": str(options.get("model") or (CINEMATIC_MODEL if runtime.get("engine_id") == CINEMATIC_ENGINE_ID else DEFAULT_MODEL)),
        "fingerprint": fingerprint,
        "source_media": str(source_path),
        "cache_hit": False,
        "created_at": started_at,
        "updated_at": started_at,
    }
    _write_json_atomic(paths["manifest"], running_manifest)
    _write_json_atomic(paths["input"], {
        "source": str(source_path),
        "fingerprint": fingerprint,
        "options": options,
        "runtime": runtime,
        "created_at": started_at,
    })

    env = os.environ.copy()
    shared_cache = PATHS.cache
    torch_cache = _shared_torch_cache()
    huggingface_cache = shared_cache / "huggingface"
    torch_cache.mkdir(parents=True, exist_ok=True)
    huggingface_cache.mkdir(parents=True, exist_ok=True)
    env.update({
        "TORCH_HOME": str(torch_cache),
        "HF_HOME": str(huggingface_cache),
        "HUGGINGFACE_HUB_CACHE": str(huggingface_cache / "hub"),
        "XDG_CACHE_HOME": str(shared_cache),
    })

    try:
        if on_progress:
            on_progress(8, "Extracting the original PCM audio")
        _extract_original(source_path, staged_original, is_cancelled)
        if on_progress:
            on_progress(18, "Starting the shared cinematic audio worker" if runtime.get("engine_id") == CINEMATIC_ENGINE_ID else "Starting the shared Demucs worker")

        command = _worker_command(
            runtime,
            staged_original,
            staging,
            staged_output,
            staged_progress,
            options,
        )
        with paths["stdout"].open("w", encoding="utf-8") as stdout_handle, paths["stderr"].open("w", encoding="utf-8") as stderr_handle:
            process = subprocess.Popen(
                command,
                env=env,
                cwd=str(PATHS.workspace),
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            last_progress = ""
            while process.poll() is None:
                if is_cancelled and is_cancelled():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    raise AudioPreservationCancelled("Audio Preservation cancelled")
                if staged_progress.is_file():
                    progress_text = staged_progress.read_text(encoding="utf-8", errors="replace")
                    if progress_text != last_progress:
                        worker_progress = _read_json(staged_progress)
                        mapped = 18 + round(int(worker_progress.get("progress") or 0) * 0.76)
                        message = str(worker_progress.get("message") or "Separating audio")
                        if on_progress:
                            on_progress(min(94, mapped), message)
                        last_progress = progress_text
                time.sleep(0.4)

        if process.returncode != 0 or not staged_output.is_file():
            stderr_text = paths["stderr"].read_text(encoding="utf-8", errors="replace") if paths["stderr"].is_file() else ""
            stdout_text = paths["stdout"].read_text(encoding="utf-8", errors="replace") if paths["stdout"].is_file() else ""
            raise RuntimeError(f"Audio separation worker failed: {(stderr_text or stdout_text)[-1800:]}")

        staged_vocals = staging / "vocals.wav"
        staged_bed = staging / "bed.wav"
        durations = {
            "original": _duration(staged_original),
            "vocals": _duration(staged_vocals),
            "bed": _duration(staged_bed),
        }
        tolerance = max(2.0, durations["original"] * 0.02)
        for name in ("vocals", "bed"):
            if abs(durations[name] - durations["original"]) > tolerance:
                raise RuntimeError(f"{name}.wav duration does not match the source audio")

        paths["source_dir"].mkdir(parents=True, exist_ok=True)
        staged_original.replace(paths["original"])
        staged_vocals.replace(paths["vocals"])
        staged_bed.replace(paths["bed"])
        for optional_track in ("music", "sfx"):
            staged_track = staging / f"{optional_track}.wav"
            if staged_track.is_file():
                staged_track.replace(paths[optional_track])
        shutil.copy2(staged_output, paths["output"])
        if staged_progress.is_file():
            shutil.copy2(staged_progress, paths["progress"])

        completed_at = _now()
        worker_result = _read_json(paths["output"])
        manifest = {
            "version": MANIFEST_VERSION,
            "status": "ready",
            "progress": 100,
            "message": "Original, voices and SFX/music stems are ready",
            "error": None,
            "backend": str(runtime.get("engine_id") or ENGINE_ID),
            "model": str(options.get("model") or (CINEMATIC_MODEL if runtime.get("engine_id") == CINEMATIC_ENGINE_ID else DEFAULT_MODEL)),
            "fingerprint": fingerprint,
            "source_media": str(source_path),
            "original": str(paths["original"]),
            "vocals": str(paths["vocals"]),
            "bed": str(paths["bed"]),
            "music": str(paths["music"]) if paths["music"].is_file() else None,
            "sfx": str(paths["sfx"]) if paths["sfx"].is_file() else None,
            "duration": durations["original"],
            "durations": durations,
            "runtime": worker_result.get("runtime") or runtime,
            "shared_dependencies": runtime["shared_dependencies"],
            "shared_cache": {
                "torch": str(torch_cache),
                "huggingface": str(huggingface_cache),
            },
            "cache_hit": False,
            "created_at": started_at,
            "updated_at": completed_at,
        }
        _write_json_atomic(paths["manifest"], manifest)
        if on_progress:
            on_progress(99, "Audio Preservation artifacts validated")
        return {
            "status": "completed",
            "message": "Audio Preservation completed",
            "artifacts": {name: str(paths[name]) for name in TRACK_NAMES} | {"separation_manifest": str(paths["manifest"])},
            "manifest": manifest,
        }
    except AudioPreservationCancelled:
        cancelled = dict(running_manifest)
        cancelled.update({"status": "cancelled", "message": "Audio Preservation cancelled", "updated_at": _now()})
        _write_json_atomic(paths["manifest"], cancelled)
        raise
    except Exception as exc:
        failed = dict(running_manifest)
        failed.update({
            "status": "failed",
            "progress": 100,
            "message": "Audio Preservation failed",
            "error": str(exc),
            "updated_at": _now(),
        })
        _write_json_atomic(paths["manifest"], failed)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
