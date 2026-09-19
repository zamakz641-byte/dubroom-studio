from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def overlap_seconds(left: dict[str, Any], right: dict[str, Any]) -> float:
    return max(
        0.0,
        min(float(left["end"]), float(right["end"]))
        - max(float(left["start"]), float(right["start"])),
    )


def build(
    *,
    source: Path,
    asr_path: Path,
    subtitle_evidence_path: Path,
) -> dict[str, Any]:
    asr = json.loads(asr_path.read_text(encoding="utf-8-sig"))
    subtitles = json.loads(subtitle_evidence_path.read_text(encoding="utf-8-sig"))

    transcript_segments = [
        {
            "transcript_id": f"ASR_{index:05d}",
            "start": round(float(item["start"]), 3),
            "end": round(float(item["end"]), 3),
            "text": str(item.get("text") or "").strip(),
        }
        for index, item in enumerate(asr.get("segments") or [], start=1)
        if str(item.get("text") or "").strip()
    ]
    subtitle_pairs = list(subtitles.get("pairs") or [])

    alignment: list[dict[str, Any]] = []
    matched_pair_ids: set[str] = set()
    pair_cursor = 0
    for transcript in transcript_segments:
        while (
            pair_cursor < len(subtitle_pairs)
            and float(subtitle_pairs[pair_cursor]["end"]) <= float(transcript["start"])
        ):
            pair_cursor += 1

        matches: list[dict[str, Any]] = []
        candidate_index = pair_cursor
        while (
            candidate_index < len(subtitle_pairs)
            and float(subtitle_pairs[candidate_index]["start"]) < float(transcript["end"])
        ):
            pair = subtitle_pairs[candidate_index]
            overlap = overlap_seconds(transcript, pair)
            if overlap > 0:
                pair_id = str(pair["pair_id"])
                matched_pair_ids.add(pair_id)
                transcript_duration = max(
                    0.001, float(transcript["end"]) - float(transcript["start"])
                )
                matches.append(
                    {
                        "pair_id": pair_id,
                        "overlap_seconds": round(overlap, 3),
                        "asr_overlap_ratio": round(overlap / transcript_duration, 4),
                    }
                )
            candidate_index += 1

        alignment.append(
            {
                "transcript_id": transcript["transcript_id"],
                "subtitle_matches": matches,
            }
        )

    tracks = {str(item.get("kind")): item for item in subtitles.get("tracks") or []}
    return {
        "kind": "dubroom_narrator_transcription_bundle",
        "schema_version": 1,
        "dubbing_mode": "narrator_story",
        "source_language": "zh",
        "target_language": "en",
        "project_id": "hwprtpdahgy-full-1080p",
        "project_name": "HwPRTPDahGY Full Story",
        "media": {
            "source_filename": source.name,
            "duration_seconds": round(float(asr.get("duration") or 0), 3),
            "source_sha256": sha256(source),
        },
        "provenance": {
            "asr": {
                "kind": "asr_zh",
                "language": "zh",
                "origin": "audio_transcription",
                "engine": asr.get("engine"),
                "device": asr.get("device"),
                "elapsed_seconds": asr.get("elapsed_seconds"),
                "source_path": str(asr_path.resolve()),
                "sha256": sha256(asr_path),
            },
            "subtitle_zh": tracks.get("subtitle_zh", {}),
            "subtitle_en": tracks.get("subtitle_en", {}),
            "subtitle_note": (
                "The Chinese and English subtitle tracks are uploader-provided. "
                "The English lane is not labelled as YouTube auto-translation."
            ),
        },
        "statistics": {
            "asr_segment_count": len(transcript_segments),
            "subtitle_pair_count": len(subtitle_pairs),
            "asr_segments_with_subtitle_match": sum(
                bool(item["subtitle_matches"]) for item in alignment
            ),
            "asr_segments_without_subtitle_match": sum(
                not item["subtitle_matches"] for item in alignment
            ),
            "subtitle_pairs_with_asr_match": len(matched_pair_ids),
            "subtitle_pairs_without_asr_match": len(subtitle_pairs) - len(matched_pair_ids),
        },
        "asr_segments": transcript_segments,
        "subtitle_pairs": subtitle_pairs,
        "alignment": alignment,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--asr", required=True, type=Path)
    parser.add_argument("--subtitle-evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    payload = build(
        source=args.source.resolve(),
        asr_path=args.asr.resolve(),
        subtitle_evidence_path=args.subtitle_evidence.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "statistics": payload["statistics"],
            },
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
