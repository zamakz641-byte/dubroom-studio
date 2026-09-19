from __future__ import annotations

import math
import shutil
import subprocess
import wave
from array import array
from pathlib import Path
from typing import Any

from .config import PATHS


CLEANUP_VERSION = 2
# Keep enough bandwidth for speaker timbre. 16 kHz was acceptable for ASR but
# unnecessarily removed upper harmonics from voice-cloning references.
TARGET_SAMPLE_RATE = 24_000
PREFERRED_SECONDS = 6.5
MIN_SEGMENT_SECONDS = 3.0
MAX_SEGMENT_SECONDS = 10.5

FILTERS = {
    "gentle": (
        "highpass=f=55:p=2,lowpass=f=11200:p=2,"
        "afftdn=nr=5:nf=-54:tn=1:ad=0.80,"
        "loudnorm=I=-23:TP=-3:LRA=7,aresample=24000"
    ),
    "balanced": (
        "highpass=f=60:p=2,lowpass=f=10800:p=2,"
        "afftdn=nr=8:nf=-52:tn=1:ad=0.72,"
        "adeclick=t=2:w=18:o=70,"
        "loudnorm=I=-23:TP=-3:LRA=7,aresample=24000"
    ),
    "strong": (
        "highpass=f=70:p=2,lowpass=f=10000:p=2,"
        "afftdn=nr=13:nf=-48:tn=1:ad=0.60,"
        "anlmdn=s=0.00035:p=0.002:r=0.006:m=11,"
        "loudnorm=I=-23:TP=-3:LRA=7,aresample=24000"
    ),
}


def _ffmpeg() -> str:
    executable = "ffmpeg.exe" if shutil.which("ffmpeg.exe") else "ffmpeg"
    resolved = shutil.which(executable)
    if resolved:
        return resolved
    managed = PATHS.data / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
    if managed.is_file():
        return str(managed)
    raise RuntimeError("FFmpeg is required to clean cloned-voice references")


def _confidence(segment: dict[str, Any]) -> float:
    probabilities = [
        float(word.get("probability"))
        for word in (segment.get("words") or [])
        if isinstance(word, dict) and word.get("probability") is not None
    ]
    return sum(probabilities) / len(probabilities) if probabilities else 0.5


def select_reference_region(
    transcription: dict[str, Any] | None,
    fallback_text: str,
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for segment in (transcription or {}).get("segments") or []:
        if not isinstance(segment, dict):
            continue
        start = max(0.0, float(segment.get("start") or 0.0))
        end = max(start, float(segment.get("end") or start))
        text = str(segment.get("text") or "").strip()
        duration = end - start
        if not text or duration < MIN_SEGMENT_SECONDS or duration > MAX_SEGMENT_SECONDS:
            continue
        confidence = _confidence(segment)
        duration_score = max(0.0, 1.0 - abs(duration - PREFERRED_SECONDS) / PREFERRED_SECONDS)
        complete_sentence = 0.05 if text.endswith((".", "!", "?", "…")) else 0.0
        # Exact transcription is the most important input for zero-shot cloning.
        score = confidence * 0.85 + duration_score * 0.10 + complete_sentence
        candidates.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "confidence": confidence,
                "score": score,
            }
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-float(item["score"]), float(item["start"])))
    return candidates[0]


def _audio_metrics(path: Path) -> dict[str, Any]:
    with wave.open(str(path), "rb") as source:
        sample_rate = source.getframerate()
        channels = source.getnchannels()
        frames = source.getnframes()
        samples = array("h")
        samples.frombytes(source.readframes(frames))
    if channels > 1:
        samples = array("h", samples[::channels])
    normalized = [float(value) / 32768.0 for value in samples]
    peak = max((abs(value) for value in normalized), default=0.0)
    rms = math.sqrt(sum(value * value for value in normalized) / max(1, len(normalized)))
    return {
        "sample_rate": sample_rate,
        "channels": 1,
        "duration_seconds": round(len(normalized) / max(1, sample_rate), 3),
        "peak_dbfs": round(20.0 * math.log10(max(peak, 1e-7)), 2),
        "rms_dbfs": round(20.0 * math.log10(max(rms, 1e-7)), 2),
        "clipped_samples": sum(1 for value in normalized if abs(value) >= 0.999),
    }


def prepare_reference(
    source: str | Path,
    destination: str | Path,
    *,
    reference_text: str,
    transcription: dict[str, Any] | None = None,
    mode: str = "balanced",
) -> dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if not source_path.is_file():
        raise ValueError("profile.sample_missing")
    if mode not in FILTERS:
        raise ValueError(f"Unknown voice cleanup mode: {mode}")

    region = select_reference_region(transcription, reference_text)
    command = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source_path)]
    if region:
        start = max(0.0, float(region["start"]) - 0.08)
        end = float(region["end"]) + 0.12
        command.extend(["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}"])
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    command.extend(
        [
            "-af",
            FILTERS[mode],
            "-ac",
            "1",
            "-ar",
            str(TARGET_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(destination_path),
        ]
    )
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    if result.returncode != 0 or not destination_path.is_file():
        destination_path.unlink(missing_ok=True)
        raise RuntimeError((result.stderr or result.stdout or "Voice cleanup failed")[-2000:])

    selected_text = str((region or {}).get("text") or reference_text).strip()
    return {
        "version": CLEANUP_VERSION,
        "mode": mode,
        "path": str(destination_path),
        "reference_text": selected_text,
        "source_path": str(source_path),
        "region": region,
        "metrics": _audio_metrics(destination_path),
    }
