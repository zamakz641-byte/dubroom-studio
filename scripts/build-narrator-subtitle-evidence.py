from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


TIMECODE_RE = re.compile(
    r"(?P<hours>\d{2}):(?P<minutes>\d{2}):(?P<seconds>\d{2}),(?P<milliseconds>\d{3})"
)


def seconds(value: str) -> float:
    match = TIMECODE_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timecode: {value}")
    return round(
        int(match.group("hours")) * 3600
        + int(match.group("minutes")) * 60
        + int(match.group("seconds"))
        + int(match.group("milliseconds")) / 1000,
        3,
    )


def parse_srt(path: Path) -> list[dict[str, object]]:
    content = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    cues: list[dict[str, object]] = []
    for block in re.split(r"\n{2,}", content.strip()):
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3 or " --> " not in lines[1]:
            continue
        start_text, end_text = lines[1].split(" --> ", 1)
        cues.append(
            {
                "source_index": int(lines[0]),
                "start": seconds(start_text),
                "end": seconds(end_text.split()[0]),
                "text": " ".join(lines[2:]).strip(),
            }
        )
    return cues


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(zh_path: Path, en_path: Path) -> dict[str, object]:
    zh_cues = parse_srt(zh_path)
    en_cues = parse_srt(en_path)
    if len(zh_cues) != len(en_cues):
        raise ValueError(f"Subtitle cue count differs: zh={len(zh_cues)}, en={len(en_cues)}")

    pairs: list[dict[str, object]] = []
    for index, (zh, en) in enumerate(zip(zh_cues, en_cues, strict=True), start=1):
        if abs(float(zh["start"]) - float(en["start"])) > 0.05 or abs(
            float(zh["end"]) - float(en["end"])
        ) > 0.05:
            raise ValueError(f"Subtitle timing mismatch at cue {index}")
        pairs.append(
            {
                "pair_id": f"SUBPAIR_{index:05d}",
                "start": zh["start"],
                "end": zh["end"],
                "zh": {
                    "evidence_id": f"EVD_ZH_{index:05d}",
                    "kind": "subtitle_zh",
                    "language": "zh-Hans",
                    "origin": "uploader_provided",
                    "text": zh["text"],
                },
                "en": {
                    "evidence_id": f"EVD_EN_{index:05d}",
                    "kind": "subtitle_en",
                    "language": "en",
                    "origin": "uploader_provided",
                    "text": en["text"],
                },
            }
        )

    return {
        "kind": "dubroom_narrator_subtitle_evidence",
        "schema_version": 1,
        "revision": "uploader-zh-en-pairing-20260811-v1",
        "tracks": [
            {
                "kind": "subtitle_zh",
                "language": "zh-Hans",
                "origin": "uploader_provided",
                "path": str(zh_path.resolve()),
                "sha256": sha256(zh_path),
                "cue_count": len(zh_cues),
            },
            {
                "kind": "subtitle_en",
                "language": "en",
                "origin": "uploader_provided",
                "path": str(en_path.resolve()),
                "sha256": sha256(en_path),
                "cue_count": len(en_cues),
            },
        ],
        "pair_count": len(pairs),
        "timing_match_tolerance_seconds": 0.05,
        "pairs": pairs,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zh", required=True, type=Path)
    parser.add_argument("--en", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build(args.zh.resolve(), args.en.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "pair_count": result["pair_count"],
                "zh_sha256": result["tracks"][0]["sha256"],
                "en_sha256": result["tracks"][1]["sha256"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
