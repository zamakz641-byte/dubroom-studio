from __future__ import annotations

import json
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from .config import PATHS


DOWNLOAD_ROOT = PATHS.data / "youtube-downloads"
STATE_ROOT = DOWNLOAD_ROOT / "state"
MEDIA_ROOT = DOWNLOAD_ROOT / "media"
PYTHON_EXE = PATHS.environments / "yt-dlp" / "venv" / "Scripts" / "python.exe"
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com"}
_processes: dict[str, subprocess.Popen[str]] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def runtime_ready() -> bool:
    if not PYTHON_EXE.is_file():
        return False
    try:
        completed = subprocess.run(
            [str(PYTHON_EXE), "-c", "import yt_dlp"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def validate_url(url: str) -> str:
    candidate = url.strip()
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in ALLOWED_HOSTS:
        raise RuntimeError("Enter a valid YouTube video URL")
    if not parsed.path or parsed.path == "/":
        raise RuntimeError("This YouTube URL does not identify a video")
    return candidate


def _base_command() -> list[str]:
    if not runtime_ready():
        raise RuntimeError("YouTube Importer is not installed. Install it from Engines first.")
    return [str(PYTHON_EXE), "-m", "yt_dlp", "--no-config", "--no-playlist", "--no-warnings"]


def inspect(url: str) -> dict[str, Any]:
    candidate = validate_url(url)
    command = [*_base_command(), "--skip-download", "--dump-single-json", candidate]
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90, check=False)
    if completed.returncode != 0:
        raise RuntimeError(_friendly_error(completed.stderr or completed.stdout))
    payload = json.loads(completed.stdout)
    return {
        "id": str(payload.get("id", "")),
        "title": str(payload.get("title", "YouTube video")),
        "channel": payload.get("channel") or payload.get("uploader"),
        "duration": payload.get("duration"),
        "thumbnail": payload.get("thumbnail"),
        "width": payload.get("width"),
        "height": payload.get("height"),
        "fps": payload.get("fps"),
        "live": bool(payload.get("is_live")),
        "webpage_url": payload.get("webpage_url") or candidate,
    }


def _normalise_range(
    start_seconds: float | None,
    end_seconds: float | None,
) -> tuple[float | None, float | None]:
    start = None if start_seconds is None else max(0.0, float(start_seconds))
    end = None if end_seconds is None else float(end_seconds)
    if start is None and end is None:
        return None, None
    start = start or 0.0
    if end is None:
        raise RuntimeError("Choose an end time for the YouTube excerpt")
    if end <= start:
        raise RuntimeError("The excerpt end time must be after its start time")
    if end - start < 0.5:
        raise RuntimeError("The YouTube excerpt must be at least 0.5 seconds long")
    return round(start, 3), round(end, 3)


def start(
    url: str,
    title: str | None = None,
    *,
    media_type: str = "video",
    start_seconds: float | None = None,
    end_seconds: float | None = None,
) -> dict[str, Any]:
    candidate = validate_url(url)
    if not runtime_ready():
        raise RuntimeError("YouTube Importer is not installed")
    kind = str(media_type or "video").strip().lower()
    if kind not in {"video", "audio"}:
        raise RuntimeError("YouTube download type must be video or audio")
    range_start, range_end = _normalise_range(start_seconds, end_seconds)
    download_id = uuid4().hex
    state = {
        "id": download_id,
        "status": "queued",
        "progress": 0.0,
        "message": "Waiting for the downloader",
        "url": candidate,
        "title": title or "YouTube video",
        "media_type": kind,
        "start_seconds": range_start,
        "end_seconds": range_end,
        "path": None,
        "eta": None,
        "speed": None,
        "error": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    _write_state(download_id, state)
    return state


def run(download_id: str) -> None:
    state = get(download_id)
    target = MEDIA_ROOT / download_id
    target.mkdir(parents=True, exist_ok=True)
    output = str(target / "%(title).160B [%(id)s].%(ext)s")
    media_type = str(state.get("media_type") or "video")
    start_seconds = state.get("start_seconds")
    end_seconds = state.get("end_seconds")
    partial = start_seconds is not None and end_seconds is not None
    command = [
        *_base_command(),
        "--newline",
        "--progress",
        "--progress-delta", "0.5",
        "--concurrent-fragments", "4",
        "--socket-timeout", "30",
        "--http-chunk-size", "10M",
        "--retries", "10",
        "--fragment-retries", "10",
        "--progress-template", "download:__DUB_PROGRESS__%(progress._percent_str)s|%(progress.eta)s|%(progress.speed)s",
        "--print", "after_move:__DUB_FILE__%(filepath)s",
        "--windows-filenames",
    ]
    if partial:
        command.extend(
            [
                "--download-sections",
                f"*{float(start_seconds):.3f}-{float(end_seconds):.3f}",
                "--force-keyframes-at-cuts",
            ]
        )
    if media_type == "audio":
        command.extend(
            [
                "--format",
                "ba/b",
                "--extract-audio",
                "--audio-format",
                "wav",
                "--audio-quality",
                "0",
            ]
        )
    else:
        command.extend(
            [
                "--format",
                (
                    "bv*[ext=mp4][height<=720]+ba[ext=m4a]/"
                    "bv*[height<=720]+ba/b[height<=720]/b"
                    if partial
                    else (
                        "bv*[ext=mp4][vcodec^=avc1][height<=1080]+ba[ext=m4a]/"
                        "bv*[height<=1080]+ba/b[height<=1080]/b"
                    )
                ),
                "--merge-output-format",
                "mp4",
                "--remux-video",
                "mp4",
                "--write-subs",
                "--sub-langs",
                "zh-Hans,en",
                "--sub-format",
                "srt",
            ]
        )
    command.extend(["--output", output, str(state["url"])])
    range_label = (
        f" ({float(start_seconds):.1f}s to {float(end_seconds):.1f}s)"
        if partial
        else ""
    )
    _patch_state(
        download_id,
        status="downloading",
        message=(
            f"Downloading the best audio{range_label}"
            if media_type == "audio"
            else f"Downloading the best video and audio{range_label}"
        ),
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=flags)
    with _lock:
        _processes[download_id] = process
    last_lines: list[str] = []
    try:
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.strip()
            if not line:
                continue
            last_lines = (last_lines + [line])[-12:]
            if line.startswith("__DUB_PROGRESS__"):
                parts = line.removeprefix("__DUB_PROGRESS__").split("|", 2)
                percent = _percent(parts[0] if parts else "0")
                _patch_state(download_id, progress=min(percent, 96), eta=_clean(parts[1] if len(parts) > 1 else None), speed=_clean(parts[2] if len(parts) > 2 else None), message="Downloading media")
            elif line.startswith("__DUB_FILE__"):
                _patch_state(
                    download_id,
                    path=line.removeprefix("__DUB_FILE__").strip(),
                    progress=98,
                    status="processing",
                    message=(
                        "Finalizing the audio reference"
                        if media_type == "audio"
                        else "Finalizing the video container"
                    ),
                )
        code = process.wait()
        current = get(download_id)
        if current.get("status") == "cancelled":
            return
        if code != 0:
            raise RuntimeError(_friendly_error("\n".join(last_lines)))
        path = Path(str(current.get("path") or ""))
        if not path.is_file():
            candidates = sorted(target.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True)
            allowed_extensions = (
                {".wav", ".flac", ".m4a", ".mp3", ".opus", ".ogg", ".webm"}
                if media_type == "audio"
                else {".mp4", ".mkv", ".webm", ".mov"}
            )
            path = next(
                (
                    item
                    for item in candidates
                    if item.is_file() and item.suffix.lower() in allowed_extensions
                ),
                Path(),
            )
        if not path.is_file():
            raise RuntimeError(
                "The download finished but no audio file was produced"
                if media_type == "audio"
                else "The download finished but no video file was produced"
            )
        _patch_state(
            download_id,
            status="completed",
            progress=100,
            path=str(path.resolve()),
            message="Audio reference ready" if media_type == "audio" else "Video ready",
            eta=None,
            speed=None,
        )
    except Exception as exc:
        if get(download_id).get("status") != "cancelled":
            _patch_state(download_id, status="failed", message="Download failed", error=str(exc))
    finally:
        with _lock:
            _processes.pop(download_id, None)


def cancel(download_id: str) -> dict[str, Any]:
    state = get(download_id)
    with _lock:
        process = _processes.get(download_id)
    if process and process.poll() is None:
        process.terminate()
    _patch_state(download_id, status="cancelled", message="Download cancelled", error=None)
    return get(download_id)


def get(download_id: str) -> dict[str, Any]:
    path = STATE_ROOT / f"{download_id}.json"
    if not path.is_file():
        raise KeyError(download_id)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(download_id: str, state: dict[str, Any]) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    (STATE_ROOT / f"{download_id}.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def _patch_state(download_id: str, **patch: Any) -> None:
    state = get(download_id)
    state.update(patch)
    state["updated_at"] = _now()
    _write_state(download_id, state)


def _percent(value: str) -> float:
    match = re.search(r"([\d.]+)", value.replace(",", "."))
    return float(match.group(1)) if match else 0.0


def _clean(value: str | None) -> str | None:
    candidate = (value or "").strip()
    return None if not candidate or candidate in {"NA", "N/A", "Unknown"} else candidate


def _friendly_error(detail: str) -> str:
    text = detail.strip()
    if "Sign in to confirm" in text or "cookies" in text.lower():
        return "YouTube requires authentication for this video. Try a public, unrestricted video."
    if "Video unavailable" in text:
        return "This YouTube video is unavailable"
    return text[-1000:] or "yt-dlp could not process this URL"
