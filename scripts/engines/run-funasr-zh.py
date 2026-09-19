from __future__ import annotations

import argparse
import json
import re
import time
import wave
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--progress-file", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--language", default="zh")
    return parser.parse_args()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def progress(path: Path, value: int, message: str) -> None:
    write_json(path, {"progress": value, "message": message})


def audio_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / max(1, handle.getframerate())


def normalize_tokens(text: str) -> list[str]:
    tokens = [item for item in re.split(r"\s+", text.strip()) if item]
    return tokens if len(tokens) > 1 else list(text.strip())


def join_tokens(tokens: list[str]) -> str:
    result = ""
    for token in tokens:
        if result and re.search(r"[A-Za-z0-9]$", result) and re.match(r"^[A-Za-z0-9]", token):
            result += " "
        result += token
    return result.strip()


def build_segments(
    text: str,
    timestamps: list[Any],
    maximum_seconds: float | None = None,
) -> list[dict[str, Any]]:
    tokens = normalize_tokens(text)
    pairs = [item for item in timestamps if isinstance(item, list) and len(item) >= 2]
    usable = min(len(tokens), len(pairs))
    if usable == 0:
        return []
    tokens = tokens[:usable]
    pairs = pairs[:usable]
    segments: list[dict[str, Any]] = []
    current_tokens: list[str] = []
    current_pairs: list[list[float]] = []

    def flush() -> None:
        if not current_tokens:
            return
        words = [
            {
                "word": token,
                "start": round(
                    min(float(pair[0]) / 1000.0, maximum_seconds)
                    if maximum_seconds is not None
                    else float(pair[0]) / 1000.0,
                    3,
                ),
                "end": round(
                    min(float(pair[1]) / 1000.0, maximum_seconds)
                    if maximum_seconds is not None
                    else float(pair[1]) / 1000.0,
                    3,
                ),
                "probability": 1.0,
            }
            for token, pair in zip(current_tokens, current_pairs, strict=True)
        ]
        segments.append(
            {
                "start": words[0]["start"],
                "end": words[-1]["end"],
                "text": join_tokens(current_tokens),
                "words": words,
            }
        )
        current_tokens.clear()
        current_pairs.clear()

    for token, raw_pair in zip(tokens, pairs, strict=True):
        pair = [float(raw_pair[0]), float(raw_pair[1])]
        gap = (pair[0] - current_pairs[-1][1]) / 1000.0 if current_pairs else 0.0
        projected = (pair[1] - current_pairs[0][0]) / 1000.0 if current_pairs else 0.0
        if current_tokens and (gap > 0.72 or projected > 8.5 or len(current_tokens) >= 34):
            flush()
        current_tokens.append(token)
        current_pairs.append(pair)
        if token in {"。", "！", "？", "!", "?"} and len(current_tokens) >= 5:
            flush()
    flush()
    compacted: list[dict[str, Any]] = []
    for segment in segments:
        duration = float(segment["end"]) - float(segment["start"])
        is_micro = len(str(segment["text"]).strip()) <= 2 or duration < 0.75
        if compacted and is_micro:
            previous = compacted[-1]
            gap = float(segment["start"]) - float(previous["end"])
            combined_duration = float(segment["end"]) - float(previous["start"])
            if gap <= 1.5 and combined_duration <= 10.8:
                previous["text"] = f"{previous['text']}{segment['text']}"
                previous["end"] = segment["end"]
                previous["words"].extend(segment["words"])
                continue
        compacted.append(segment)
    return compacted


def subtitle_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


def write_readable_sidecars(output_path: Path, segments: list[dict[str, Any]]) -> None:
    text_lines = [
        f"[{subtitle_timestamp(float(item['start'])).replace(',', '.')} --> "
        f"{subtitle_timestamp(float(item['end'])).replace(',', '.')}] {item['text']}"
        for item in segments
    ]
    output_path.with_suffix(".txt").write_text("\n".join(text_lines) + "\n", encoding="utf-8")
    srt_blocks = [
        f"{index}\n{subtitle_timestamp(float(item['start']))} --> "
        f"{subtitle_timestamp(float(item['end']))}\n{item['text']}"
        for index, item in enumerate(segments, start=1)
    ]
    output_path.with_suffix(".srt").write_text("\n\n".join(srt_blocks) + "\n", encoding="utf-8-sig")


def main() -> None:
    args = parse_args()
    manifest_path = Path(args.manifest)
    audio_path = Path(args.audio)
    output_path = Path(args.output)
    progress_path = Path(args.progress_file)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    model_path = Path(str(manifest["model_path"]))
    vad_path = Path(str(manifest["vad_model_path"]))
    if not model_path.is_dir() or not vad_path.is_dir():
        raise FileNotFoundError("Paraformer-zh or FSMN-VAD model directory is missing")

    progress(progress_path, 12, "Loading Paraformer-zh on GPU")
    import torch
    from funasr import AutoModel

    device = args.device if args.device == "cpu" or torch.cuda.is_available() else "cpu"
    started = time.perf_counter()
    model = AutoModel(
        model=str(model_path),
        vad_model=str(vad_path),
        device=device,
        disable_update=True,
    )
    progress(progress_path, 28, "Transcribing Mandarin with Paraformer-zh")
    duration = audio_duration(audio_path)
    result = model.generate(
        input=str(audio_path),
        # FunASR 1.2.7 can mismatch batched VAD results after sorting clips by
        # duration. One clip per inference keeps text and timestamps aligned;
        # CUDA still processes five minutes in only a few seconds.
        batch_size_s=1,
        pred_timestamp=True,
    )
    first = result[0] if result else {}
    segments = build_segments(
        str(first.get("text") or ""),
        first.get("timestamp") or [],
        maximum_seconds=duration,
    )
    write_json(
        output_path,
        {
            "engine": "funasr-paraformer-zh",
            "device": device,
            "compute_type": "torch-fp32",
            "language": "zh",
            "duration": duration,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "segments": segments,
        },
    )
    write_readable_sidecars(output_path, segments)
    progress(progress_path, 100, f"Mandarin transcription ready: {len(segments)} segments")


if __name__ == "__main__":
    main()
