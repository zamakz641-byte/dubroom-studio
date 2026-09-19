from __future__ import annotations

import argparse
import json
import os
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def progress(path: Path, value: int, message: str, phase: str) -> None:
    write_json(
        path,
        {
            "progress": max(0, min(99, int(value))),
            "message": message,
            "phase": phase,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def load_pcm_wave(path: Path):
    import numpy as np
    import torch

    with wave.open(str(path), "rb") as source:
        channels = source.getnchannels()
        sample_width = source.getsampwidth()
        sample_rate = source.getframerate()
        frame_count = source.getnframes()
        raw = source.readframes(frame_count)
    if sample_width != 2:
        raise RuntimeError("Prepared diarization audio must be PCM 16-bit WAV")
    samples = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    waveform = torch.from_numpy(samples.copy()).unsqueeze(0)
    return waveform, sample_rate


def annotation_turns(annotation: Any) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    if annotation is None:
        return turns
    for segment, _track, speaker in annotation.itertracks(yield_label=True):
        start = max(0.0, float(segment.start))
        end = max(start, float(segment.end))
        if end - start < 0.01:
            continue
        turns.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "speaker": str(speaker),
            }
        )
    turns.sort(key=lambda item: (item["start"], item["end"], item["speaker"]))
    return turns


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Pyannote speaker diarization worker")
    parser.add_argument("--input", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--min-speakers", type=int, default=0)
    parser.add_argument("--max-speakers", type=int, default=0)
    parser.add_argument("--shared-site-packages", action="append", default=[])
    args = parser.parse_args()

    for shared_path in args.shared_site_packages:
        if shared_path and shared_path not in sys.path:
            sys.path.append(shared_path)

    # The application owns downloads. Project jobs are strictly local/offline.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

    input_path = Path(args.input).resolve()
    model_path = Path(args.model_path).resolve()
    output_path = Path(args.output).resolve()
    progress_path = Path(args.progress_file).resolve()
    if not input_path.is_file():
        raise RuntimeError(f"Prepared vocal track is missing: {input_path}")
    if not model_path.is_dir():
        raise RuntimeError(f"Local Pyannote model is missing: {model_path}")

    started = time.perf_counter()
    progress(progress_path, 4, "Loading the shared Pyannote runtime", "runtime")
    import torch
    from pyannote.audio import Pipeline

    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable in the selected Pyannote runtime")
    device = torch.device(args.device)

    progress(progress_path, 12, "Loading the local speaker model", "model")
    pipeline = Pipeline.from_pretrained(str(model_path))
    pipeline.to(device)

    # Preloading avoids TorchCodec/FFmpeg decoder differences between runtimes.
    waveform, sample_rate = load_pcm_wave(input_path)
    duration = float(waveform.shape[-1]) / float(sample_rate)
    diarization_input = {"waveform": waveform, "sample_rate": sample_rate}
    kwargs: dict[str, Any] = {}
    if args.min_speakers > 0:
        kwargs["min_speakers"] = args.min_speakers
    if args.max_speakers > 0:
        kwargs["max_speakers"] = args.max_speakers

    progress(progress_path, 20, "Detecting speakers on the isolated vocal track", "diarization")
    result = pipeline(diarization_input, **kwargs)
    regular = annotation_turns(getattr(result, "speaker_diarization", result))
    exclusive = annotation_turns(getattr(result, "exclusive_speaker_diarization", None))
    selected = exclusive or regular
    speakers = sorted({item["speaker"] for item in selected})
    elapsed = time.perf_counter() - started
    payload = {
        "schema_version": 1,
        "status": "completed",
        "input_path": str(input_path),
        "model_path": str(model_path),
        "device": args.device,
        "duration": round(duration, 3),
        "elapsed_seconds": round(elapsed, 3),
        "speaker_count": len(speakers),
        "speakers": speakers,
        "turns": selected,
        "regular_turns": regular,
        "exclusive_turns": exclusive,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output_path, payload)
    progress(progress_path, 99, f"Detected {len(speakers)} speaker(s)", "complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"speaker-diarization-error: {exc}", file=sys.stderr)
        raise
