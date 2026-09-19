from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DubRoom WhisperX alignment adapter")
    parser.add_argument("--audio", required=True, help="Source audio/video file to align")
    parser.add_argument("--transcript", required=True, help="ASR manifest JSON with segments")
    parser.add_argument("--output", required=True, help="Output aligned JSON path")
    parser.add_argument("--language", help="Language code, for example en/fr/ja")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    return parser.parse_args()


def _load_segments(transcript_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(transcript_path.read_text(encoding="utf-8-sig"))
    raw_segments = payload.get("segments") if isinstance(payload, dict) else None
    if not isinstance(raw_segments, list):
        raise ValueError("Transcript manifest must contain a segments array")
    segments: list[dict[str, Any]] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        segments.append(
            {
                "start": float(item.get("start") or 0.0),
                "end": float(item.get("end") or 0.0),
                "text": text,
            }
        )
    return segments


def main() -> None:
    args = parse_args()
    audio_path = Path(args.audio)
    transcript_path = Path(args.transcript)
    output_path = Path(args.output)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    if not transcript_path.exists():
        raise FileNotFoundError(f"Transcript file not found: {transcript_path}")

    import whisperx

    segments = _load_segments(transcript_path)
    language = args.language
    if not language:
        manifest = json.loads(transcript_path.read_text(encoding="utf-8-sig"))
        language = str(manifest.get("language") or "en") if isinstance(manifest, dict) else "en"

    model_a, metadata = whisperx.load_align_model(language_code=language, device=args.device)
    aligned = whisperx.align(
        segments,
        model_a,
        metadata,
        str(audio_path),
        args.device,
        return_char_alignments=False,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            {
                "engine": "whisperx",
                "language": language,
                "device": args.device,
                "segments": aligned.get("segments", segments),
                "word_segments": aligned.get("word_segments", []),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()