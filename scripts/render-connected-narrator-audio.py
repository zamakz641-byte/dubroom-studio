from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api.app import native_tts_service  # noqa: E402


PROFILE_ID = "local-7ece52bb1d7a4e34ab95d28fbd9225cf"
ENGINE_ID = "tts-kokoro-82m"
SAMPLE_RATE = 24_000

SUBTITLE_DANGLING_WORDS = {
    "a",
    "an",
    "the",
    "this",
    "that",
    "these",
    "those",
    "and",
    "but",
    "or",
    "so",
    "to",
    "for",
    "of",
    "in",
    "on",
    "at",
    "by",
    "with",
    "from",
    "as",
}


def subtitle_chunks(words: list[str], maximum: int = 12) -> list[list[str]]:
    chunks: list[list[str]] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + maximum)
        if end < len(words):
            punctuation_breaks = [
                index
                for index in range(start + 5, end + 1)
                if words[index - 1].rstrip('"\'').endswith((".", "!", "?", ",", ";", ":"))
            ]
            if punctuation_breaks:
                end = punctuation_breaks[-1]
            while (
                end > start + 6
                and words[end - 1].strip('.,!?;:\"\'').lower() in SUBTITLE_DANGLING_WORDS
            ):
                end -= 1
        chunks.append(words[start:end])
        start = end
    return chunks


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as source:
        return source.getnframes() / max(1, source.getframerate())


def timestamp(value: float) -> str:
    milliseconds = max(0, round(value * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def assemble_voiceover(
    takes: list[dict[str, Any]],
    output: Path,
    duration_seconds: float,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    zero_chunk = b"\x00\x00" * SAMPLE_RATE
    cursor = 0
    final_frames = round(duration_seconds * SAMPLE_RATE)
    with wave.open(str(output), "wb") as destination:
        destination.setnchannels(1)
        destination.setsampwidth(2)
        destination.setframerate(SAMPLE_RATE)
        for take in takes:
            start_frame = round(float(take["planned_start"]) * SAMPLE_RATE)
            if start_frame < cursor:
                raise ValueError(f"Audio overlap before {take['block_id']}")
            silence = start_frame - cursor
            while silence:
                count = min(silence, SAMPLE_RATE)
                destination.writeframesraw(zero_chunk[: count * 2])
                silence -= count
                cursor += count
            with wave.open(str(take["audio_path"]), "rb") as source:
                if (
                    source.getnchannels() != 1
                    or source.getsampwidth() != 2
                    or source.getframerate() != SAMPLE_RATE
                ):
                    raise ValueError(f"Unexpected WAV format: {take['audio_path']}")
                while True:
                    frames = source.readframes(SAMPLE_RATE)
                    if not frames:
                        break
                    destination.writeframesraw(frames)
                    cursor += len(frames) // 2
        remaining = max(0, final_frames - cursor)
        while remaining:
            count = min(remaining, SAMPLE_RATE)
            destination.writeframesraw(zero_chunk[: count * 2])
            remaining -= count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    blocks = list(manifest.get("narration_blocks") or [])
    if not blocks:
        raise ValueError("Manifest has no narration blocks")
    raw_dir = args.output_dir / "takes"
    raw_dir.mkdir(parents=True, exist_ok=True)

    payloads: list[dict[str, Any]] = []
    block_by_id = {str(item["block_id"]): item for item in blocks}
    completed: dict[str, dict[str, Any]] = {}
    for block in blocks:
        output_path = raw_dir / f"{block['block_id']}.wav"
        if output_path.is_file() and output_path.stat().st_size > 44:
            completed[str(block["block_id"])] = {
                "id": block["block_id"],
                "status": "completed",
                "audio_path": str(output_path),
                "duration": wav_duration(output_path),
                "reused": True,
            }
            continue
        payloads.append(
            {
                "id": block["block_id"],
                "profile_id": PROFILE_ID,
                "engine_id": ENGINE_ID,
                "text": block["text"],
                "language": "en",
                "output_path": str(output_path),
                "target_duration": float(block["hard_end"]) - float(block["planned_start"]),
                "max_chunk_chars": 800,
                "crossfade_ms": 50,
                "normalize": True,
                "speed": 1.0,
            }
        )

    def progress(done: int, total: int, message: str) -> None:
        print(
            json.dumps(
                {
                    "event": "progress",
                    "completed": done + len(completed),
                    "total": len(blocks),
                    "message": message,
                },
                ensure_ascii=True,
            ),
            flush=True,
        )

    if payloads:
        for item in native_tts_service.generate_batch(payloads, progress):
            completed[str(item.get("id") or "")] = item

    takes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    timing_failures: list[dict[str, Any]] = []
    for block in blocks:
        block_id = str(block["block_id"])
        result = completed.get(block_id) or {}
        audio_path = Path(str(result.get("audio_path") or raw_dir / f"{block_id}.wav"))
        if result.get("status") != "completed" or not audio_path.is_file():
            failures.append(
                {"block_id": block_id, "error": str(result.get("error") or "missing audio")[-1200:]}
            )
            continue
        duration = wav_duration(audio_path)
        available = float(block["hard_end"]) - float(block["planned_start"])
        take = {
            "block_id": block_id,
            "planned_start": float(block["planned_start"]),
            "hard_end": float(block["hard_end"]),
            "available_duration": round(available, 3),
            "audio_duration": round(duration, 3),
            "audio_path": str(audio_path),
            "engine_id": result.get("engine_id") or ENGINE_ID,
            "profile_id": PROFILE_ID,
            "text": block["text"],
        }
        takes.append(take)
        if duration > available + 0.02:
            timing_failures.append(take)

    report = {
        "kind": "dubroom_connected_narrator_audio",
        "schema_version": 1,
        "source_manifest": str(args.manifest.resolve()),
        "engine_id": ENGINE_ID,
        "profile_id": PROFILE_ID,
        "take_count": len(takes),
        "failures": failures,
        "timing_failures": timing_failures,
        "takes": takes,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.output_dir / "narrator-audio-manifest.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if failures or timing_failures:
        raise RuntimeError(
            f"Narrator render incomplete: failures={len(failures)}, timing={len(timing_failures)}"
        )

    duration_seconds = float((manifest.get("media") or {}).get("duration_seconds") or 0)
    voiceover_path = args.output_dir / "narrator-voiceover.wav"
    assemble_voiceover(takes, voiceover_path, duration_seconds)

    srt_blocks: list[str] = []
    cue_index = 1
    for take in takes:
        words = str(take["text"]).split()
        chunks = subtitle_chunks(words)
        spoken_start = float(take["planned_start"])
        spoken_duration = float(take["audio_duration"])
        consumed_words = 0
        for chunk in chunks:
            cue_start = spoken_start + spoken_duration * (consumed_words / max(1, len(words)))
            consumed_words += len(chunk)
            cue_end = spoken_start + spoken_duration * (consumed_words / max(1, len(words)))
            cue_end = min(float(take["hard_end"]), cue_end)
            midpoint = math.ceil(len(chunk) / 2)
            lines = [" ".join(chunk[:midpoint])]
            if midpoint < len(chunk):
                lines.append(" ".join(chunk[midpoint:]))
            srt_blocks.append(
                f"{cue_index}\n{timestamp(cue_start)} --> {timestamp(cue_end)}\n"
                + "\n".join(lines)
            )
            cue_index += 1
    subtitle_path = args.output_dir / "narrator-en.srt"
    subtitle_path.write_text("\n\n".join(srt_blocks) + "\n", encoding="utf-8-sig")

    report.update(
        {
            "voiceover_path": str(voiceover_path),
            "subtitle_path": str(subtitle_path),
            "duration_seconds": duration_seconds,
            "passed": True,
        }
    )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"event": "completed", "report": str(report_path.resolve())}, indent=2))


if __name__ == "__main__":
    main()
