from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import unicodedata
import wave
from array import array
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


VOWEL_GROUP = re.compile(r"[aeiouy]+")
WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿŒœ]+")


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def french_syllable_estimate(text: str) -> int:
    total = 0
    for raw_word in WORD.findall(text):
        word = (
            unicodedata.normalize("NFKD", raw_word.lower())
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        groups = len(VOWEL_GROUP.findall(word))
        if groups > 1 and re.search(r"(?:e|es|ent)$", word):
            groups -= 1
        total += max(1, groups)
    return total


def _silence_runs(flags: list[bool], frame_seconds: float, minimum: float) -> list[tuple[float, float]]:
    runs: list[tuple[float, float]] = []
    start: int | None = None
    for index, silent in enumerate(flags + [False]):
        if silent and start is None:
            start = index
        elif not silent and start is not None:
            duration = (index - start) * frame_seconds
            if duration >= minimum:
                runs.append((start * frame_seconds, index * frame_seconds))
            start = None
    return runs


def inspect_pcm_wave(path: Path, *, silence_db: float = -42.0) -> dict[str, float]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        frame_count = handle.getnframes()
        raw = handle.readframes(frame_count)
    if sample_width != 2:
        raise ValueError(f"Unsupported WAV sample width ({sample_width}) for {path}")
    samples = array("h")
    samples.frombytes(raw)
    if channels > 1:
        samples = array(
            "h",
            (
                round(sum(samples[index + channel] for channel in range(channels)) / channels)
                for index in range(0, len(samples), channels)
            ),
        )
    duration = len(samples) / max(sample_rate, 1)
    samples_per_frame = max(1, round(sample_rate * 0.02))
    threshold = 32768.0 * (10.0 ** (silence_db / 20.0))
    silent_flags: list[bool] = []
    for start in range(0, len(samples), samples_per_frame):
        frame = samples[start : start + samples_per_frame]
        if not frame:
            continue
        rms = math.sqrt(sum(float(value) * float(value) for value in frame) / len(frame))
        silent_flags.append(rms <= threshold)
    frame_seconds = samples_per_frame / max(sample_rate, 1)
    runs = _silence_runs(silent_flags, frame_seconds, 0.12)
    leading = runs[0][1] - runs[0][0] if runs and runs[0][0] <= 0.001 else 0.0
    trailing = (
        runs[-1][1] - runs[-1][0]
        if runs and runs[-1][1] >= duration - frame_seconds * 1.5
        else 0.0
    )
    internal = sum(end - start for start, end in runs) - leading - trailing
    return {
        "duration": duration,
        "leading_silence": max(0.0, leading),
        "internal_silence": max(0.0, internal),
        "trailing_silence": max(0.0, trailing),
        "pause_count": float(
            sum(
                1
                for start, end in runs
                if start > 0.001 and end < duration - frame_seconds * 1.5
            )
        ),
    }


def describe(values: list[float]) -> dict[str, float]:
    if not values:
        return {"mean": 0.0, "median": 0.0, "p10": 0.0, "p90": 0.0}
    return {
        "mean": round(statistics.fmean(values), 4),
        "median": round(statistics.median(values), 4),
        "p10": round(percentile(values, 0.10), 4),
        "p90": round(percentile(values, 0.90), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    project = args.project.resolve()
    state = json.loads((project / "analysis" / "state.json").read_text(encoding="utf-8"))
    script = json.loads(
        (project / "analysis" / "voice_script.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (project / "audio" / "voice_manifest.json").read_text(encoding="utf-8")
    )
    state_by_id = {str(item["id"]): item for item in state.get("segments", [])}
    group_by_id = {str(item["id"]): item for item in script.get("groups", [])}

    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for item in manifest.get("segments", []):
        segment_id = str(item.get("segment_id") or "")
        group = group_by_id.get(segment_id, {})
        path = Path(str(item.get("path") or ""))
        if not path.is_file():
            missing.append(segment_id)
            continue
        audio = inspect_pcm_wave(path)
        text = str(group.get("text") or "")
        member_ids = [str(value) for value in item.get("member_ids", [])]
        emotions = [
            str(state_by_id.get(member_id, {}).get("emotion") or "Neutral")
            for member_id in member_ids
        ]
        emotion = Counter(emotions).most_common(1)[0][0] if emotions else "Neutral"
        intensity_values = [
            float(state_by_id.get(member_id, {}).get("intensity") or 0)
            for member_id in member_ids
        ]
        target = float(
            item.get("target_duration")
            or group.get("duration_seconds")
            or item.get("source_duration")
            or audio["duration"]
        )
        actual = float(audio["duration"])
        non_space_characters = len(re.sub(r"\s+", "", text))
        syllables = french_syllable_estimate(text)
        gap = target - actual
        video_speed = target / actual if actual > 0 else 1.0
        symmetric_video_speed = math.sqrt(video_speed) if video_speed > 0 else 1.0
        symmetric_audio_speed = 1.0 / symmetric_video_speed if symmetric_video_speed else 1.0
        active_span = max(
            0.001,
            actual - audio["leading_silence"] - audio["trailing_silence"],
        )
        rows.append(
            {
                "segment_id": segment_id,
                "member_count": len(member_ids),
                "profile_id": str(item.get("profile_id") or ""),
                "emotion": emotion,
                "intensity": round(statistics.fmean(intensity_values), 2)
                if intensity_values
                else 0.0,
                "text": text,
                "non_space_characters": non_space_characters,
                "estimated_syllables": syllables,
                "audio_duration": round(actual, 4),
                "target_video_duration": round(target, 4),
                "gap_seconds": round(gap, 4),
                "coverage_ratio": round(actual / target, 4) if target > 0 else 1.0,
                "characters_per_audio_second": round(
                    non_space_characters / actual, 4
                )
                if actual > 0
                else 0.0,
                "characters_per_active_span_second": round(
                    non_space_characters / active_span, 4
                ),
                "syllables_per_audio_second": round(syllables / actual, 4)
                if actual > 0
                else 0.0,
                "leading_silence": round(audio["leading_silence"], 4),
                "internal_silence": round(audio["internal_silence"], 4),
                "trailing_silence": round(audio["trailing_silence"], 4),
                "internal_pause_count": int(audio["pause_count"]),
                "video_speed_if_video_only": round(video_speed, 4),
                "video_speed_if_split_evenly": round(symmetric_video_speed, 4),
                "audio_speed_if_split_evenly": round(symmetric_audio_speed, 4),
            }
        )

    profiles: dict[str, list[dict[str, Any]]] = defaultdict(list)
    emotions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        profiles[row["profile_id"]].append(row)
        emotions[row["emotion"]].append(row)

    gaps = [float(row["gap_seconds"]) for row in rows]
    coverage = [float(row["coverage_ratio"]) for row in rows]
    video_speeds = [float(row["video_speed_if_video_only"]) for row in rows]
    shorter = [row for row in rows if float(row["gap_seconds"]) > 0.15]
    longer = [row for row in rows if float(row["gap_seconds"]) < -0.15]
    safe_buckets = {
        "no_change_0_to_3_percent": sum(0.97 <= value <= 1.03 for value in video_speeds),
        "up_to_5_percent": sum(1.03 < value <= 1.05 for value in video_speeds),
        "up_to_10_percent": sum(1.05 < value <= 1.10 for value in video_speeds),
        "up_to_15_percent": sum(1.10 < value <= 1.15 for value in video_speeds),
        "up_to_20_percent": sum(1.15 < value <= 1.20 for value in video_speeds),
        "over_20_percent": sum(value > 1.20 for value in video_speeds),
        "audio_longer_than_video_over_3_percent": sum(value < 0.97 for value in video_speeds),
    }

    def group_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "segments": len(items),
            "characters_per_audio_second": describe(
                [float(item["characters_per_audio_second"]) for item in items]
            ),
            "syllables_per_audio_second": describe(
                [float(item["syllables_per_audio_second"]) for item in items]
            ),
            "internal_silence_seconds": describe(
                [float(item["internal_silence"]) for item in items]
            ),
            "coverage_ratio": describe(
                [float(item["coverage_ratio"]) for item in items]
            ),
        }

    report = {
        "created_at": datetime.now().isoformat(),
        "project": str(project),
        "method": {
            "silence_threshold_dbfs": -42.0,
            "minimum_pause_seconds": 0.12,
            "syllables": "French orthographic heuristic; suitable for relative timing, not phonetic annotation",
        },
        "counts": {
            "analysis_segments": len(state_by_id),
            "voice_script_groups": len(group_by_id),
            "generated_voice_segments": len(rows),
            "missing_audio_files": len(missing),
            "audio_shorter_by_over_150ms": len(shorter),
            "audio_longer_by_over_150ms": len(longer),
        },
        "overall": {
            "characters_per_audio_second": describe(
                [float(row["characters_per_audio_second"]) for row in rows]
            ),
            "characters_per_active_span_second": describe(
                [float(row["characters_per_active_span_second"]) for row in rows]
            ),
            "syllables_per_audio_second": describe(
                [float(row["syllables_per_audio_second"]) for row in rows]
            ),
            "leading_silence_seconds": describe(
                [float(row["leading_silence"]) for row in rows]
            ),
            "internal_silence_seconds": describe(
                [float(row["internal_silence"]) for row in rows]
            ),
            "trailing_silence_seconds": describe(
                [float(row["trailing_silence"]) for row in rows]
            ),
            "gap_seconds": describe(gaps),
            "coverage_ratio": describe(coverage),
            "video_speed_if_video_only": describe(video_speeds),
            "total_target_video_seconds": round(
                sum(float(row["target_video_duration"]) for row in rows), 3
            ),
            "total_generated_audio_seconds": round(
                sum(float(row["audio_duration"]) for row in rows), 3
            ),
            "total_positive_gap_seconds": round(
                sum(max(0.0, float(row["gap_seconds"])) for row in rows), 3
            ),
        },
        "video_speed_buckets": safe_buckets,
        "profiles": {key: group_summary(value) for key, value in profiles.items()},
        "emotions": {key: group_summary(value) for key, value in emotions.items()},
        "largest_positive_gaps": sorted(
            rows, key=lambda row: float(row["gap_seconds"]), reverse=True
        )[:20],
        "largest_overflows": sorted(rows, key=lambda row: float(row["gap_seconds"]))[:20],
        "missing_audio_segments": missing,
    }

    output = args.output or project / "analysis" / "voice_timing_report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    csv_path = output.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["segment_id"])
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({"ok": True, "report": str(output), "csv": str(csv_path), **report["counts"], **report["overall"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
