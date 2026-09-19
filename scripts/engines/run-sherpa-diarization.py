from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


def estimate_speaker_traits(samples: Any, sample_rate: int, turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    import numpy as np

    by_speaker: dict[str, list[float]] = {}
    frame_length = round(sample_rate * 0.08)
    min_lag = max(1, round(sample_rate / 350))
    max_lag = round(sample_rate / 70)
    window = np.hanning(frame_length).astype(np.float32)
    for turn in turns:
        speaker = str(turn["speaker"])
        start = max(0, round(float(turn["start"]) * sample_rate))
        end = min(len(samples), round(float(turn["end"]) * sample_rate))
        if end - start < frame_length:
            continue
        pitches = by_speaker.setdefault(speaker, [])
        step = max(frame_length, round((end - start) / 18))
        for offset in range(start, end - frame_length + 1, step):
            if len(pitches) >= 220:
                break
            frame = np.asarray(samples[offset : offset + frame_length], dtype=np.float32)
            frame = (frame - frame.mean()) * window
            energy = float(np.sqrt(np.mean(frame * frame)))
            if energy < 0.004:
                continue
            correlation = np.correlate(frame, frame, mode="full")[frame_length - 1 :]
            if correlation[0] <= 1e-8:
                continue
            region = correlation[min_lag : max_lag + 1]
            lag = min_lag + int(np.argmax(region))
            confidence = float(correlation[lag] / correlation[0])
            if confidence >= 0.28:
                pitches.append(sample_rate / lag)
    traits = []
    for speaker in sorted({str(turn["speaker"]) for turn in turns}):
        pitches = by_speaker.get(speaker, [])
        median_pitch = float(np.median(pitches)) if pitches else 0.0
        sex = "female" if median_pitch >= 170 else "male" if 0 < median_pitch <= 155 else "uncertain"
        sample_factor = min(1.0, len(pitches) / 80.0)
        boundary_distance = min(1.0, abs(median_pitch - 162.5) / 55.0) if median_pitch else 0.0
        sex_confidence = round(min(0.85, sample_factor * (0.45 + 0.5 * boundary_distance)), 2)
        # Pitch alone cannot distinguish an adult woman from a teenage or young
        # male voice reliably. Only expose a cautious coarse hint at the very
        # high end; GPT resolves age from narrative context and never an exact age.
        if median_pitch >= 300 and len(pitches) >= 12:
            age_group, age_confidence = "child", 0.34
        elif median_pitch >= 245 and len(pitches) >= 20:
            age_group, age_confidence = "teen", 0.22
        else:
            age_group, age_confidence = "unknown", 0.0
        traits.append({
            "speaker": speaker,
            "sex": sex,
            "gender": "unspecified" if sex == "uncertain" else sex,
            "sex_confidence": sex_confidence,
            "age_group": age_group,
            "age_confidence": age_confidence,
            "median_pitch_hz": round(median_pitch, 1) if median_pitch else None,
            "pitch_samples": len(pitches),
        })
    return traits


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--min-speakers", type=int, default=0)
    parser.add_argument("--max-speakers", type=int, default=0)
    parser.add_argument("--cluster-threshold", type=float, default=0.92)
    return parser.parse_args()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(8):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.025 * (attempt + 1))


def main() -> None:
    args = parse_args()
    import sherpa_onnx
    import soundfile as sf

    model_root = Path(args.model_path).resolve()
    segmentation = model_root / "segmentation" / "model.int8.onnx"
    embedding = model_root / "nemo_en_titanet_small.onnx"
    if not segmentation.is_file() or not embedding.is_file():
        raise RuntimeError("Sherpa diarization models are incomplete")

    fixed_speakers = (
        args.min_speakers
        if args.min_speakers > 0 and args.min_speakers == args.max_speakers
        else -1
    )
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(segmentation)
            ),
            num_threads=2,
            provider="cpu",
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(embedding),
            num_threads=2,
            provider="cpu",
        ),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=fixed_speakers,
            threshold=max(0.35, min(0.95, float(args.cluster_threshold))),
        ),
        min_duration_on=0.30,
        min_duration_off=0.45,
    )
    if not config.validate():
        raise RuntimeError("Sherpa diarization configuration is invalid")

    diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    audio, sample_rate = sf.read(args.input, dtype="float32", always_2d=True)
    if sample_rate != diarizer.sample_rate:
        raise RuntimeError(
            f"Expected {diarizer.sample_rate} Hz audio, received {sample_rate} Hz"
        )
    samples = audio[:, 0]
    started = time.monotonic()

    def on_progress(processed: int, total: int) -> int:
        progress = 5 if total <= 0 else round(processed / total * 92)
        write_json(
            Path(args.progress_file),
            {
                "progress": max(1, min(96, progress)),
                "message": "Détection locale des changements de locuteur",
                "processed_chunks": processed,
                "total_chunks": total,
            },
        )
        return 0

    result = diarizer.process(samples, callback=on_progress).sort_by_start_time()
    turns = [
        {
            "start": round(float(turn.start), 3),
            "end": round(float(turn.end), 3),
            "speaker": f"SPEAKER_{int(turn.speaker):02d}",
        }
        for turn in result
        if float(turn.end) > float(turn.start)
    ]
    speakers = sorted({turn["speaker"] for turn in turns})
    speaker_profiles = estimate_speaker_traits(samples, sample_rate, turns)
    payload = {
        "status": "completed",
        "device": "cpu-onnx",
        "duration": round(len(samples) / sample_rate, 3),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "speaker_count": len(speakers),
        "speakers": speakers,
        "speaker_profiles": speaker_profiles,
        "turns": turns,
        "regular_turns": turns,
        "runtime": "sherpa-onnx",
        "cluster_threshold": max(0.35, min(0.95, float(args.cluster_threshold))),
        "min_speakers": int(args.min_speakers),
        "max_speakers": int(args.max_speakers),
    }
    write_json(Path(args.output), payload)
    write_json(
        Path(args.progress_file),
        {"progress": 99, "message": f"{len(speakers)} locuteur(s) détecté(s)"},
    )


if __name__ == "__main__":
    main()
