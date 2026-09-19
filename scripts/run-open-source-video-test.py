from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.config import PATHS  # noqa: E402
from services.api.app import export_service  # noqa: E402
from services.api.app.main import (  # noqa: E402
    ProjectAnalysisState,
    SegmentRecord,
    SpeakerRecord,
    _adapt_voice_script,
    _format_timestamp,
    _read_or_create_analysis_state,
    _run_stub_job,
    _write_analysis_state,
)
from services.api.app.engine_service import list_engines  # noqa: E402
from services.api.app.segmentation import resegment_for_dubbing  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run DubRoom's strict open-source pipeline on a real video project.",
    )
    parser.add_argument("--source-project", required=True)
    parser.add_argument("--test-project", required=True)
    parser.add_argument(
        "--stage",
        choices=("prepare", "translate", "voice-script", "voice", "export", "report"),
        required=True,
    )
    parser.add_argument(
        "--profile-id",
        default="local-6615a2a1d4f545ce8e2881ba6c42afe9",
    )
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def prepare(source_id: str, test_id: str) -> dict[str, Any]:
    source_dir = PATHS.projects / source_id
    test_dir = PATHS.projects / test_id
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source project is missing: {source_dir}")
    if test_dir.exists():
        state = _read_or_create_analysis_state(test_dir)
        return {
            "project_id": test_id,
            "reused": True,
            "segments": len(state.segments),
        }

    (test_dir / "analysis").mkdir(parents=True)
    (test_dir / "audio").mkdir()
    (test_dir / "jobs").mkdir()

    project = read_json(source_dir / "project.json")
    project.update(
        {
            "id": test_id,
            "name": f"{project.get('name', source_id)} · Open-source validation",
            "project_dir": str(test_dir),
            "status": "prepared",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    write_json(test_dir / "project.json", project)

    media = read_json(source_dir / "analysis" / "media_manifest.json")
    source_audio = Path(str(media.get("audio_path") or ""))
    test_audio = test_dir / "audio" / "source_16k_mono.wav"
    if source_audio.is_file():
        try:
            os.link(source_audio, test_audio)
        except OSError:
            shutil.copy2(source_audio, test_audio)
    media["project_id"] = test_id
    media["audio_path"] = str(test_audio)
    write_json(test_dir / "analysis" / "media_manifest.json", media)

    asr = read_json(source_dir / "analysis" / "asr_manifest.json")
    raw_segments = list(asr.get("segments") or [])
    segments = resegment_for_dubbing(raw_segments)
    duration = max(
        0.1,
        float(asr.get("duration") or (media.get("media") or {}).get("duration_seconds") or 0),
    )
    speaker = SpeakerRecord(
        name="Narrator",
        role="Open-source validation narrator",
        duration="--",
        color="#39c6bd",
        level=68,
    )
    records: list[SegmentRecord] = []
    manifest_rows: list[dict[str, Any]] = []
    for index, row in enumerate(segments, start=1):
        segment_id = f"asr-{index:04d}"
        start = max(0.0, float(row.get("start") or 0))
        end = max(start + 0.1, float(row.get("end") or start + 0.1))
        text = str(row.get("text") or "").strip()
        manifest_rows.append(
            {
                "id": segment_id,
                "start": start,
                "end": end,
                "text": text,
                "words": list(row.get("words") or []),
            }
        )
        records.append(
            SegmentRecord(
                id=segment_id,
                left=round((start / duration) * 100, 3),
                width=round(max(0.08, ((end - start) / duration) * 100), 3),
                lane=(index - 1) % 3,
                speaker=speaker.name,
                label=f"ASR {index}",
                color=speaker.color,
                start=_format_timestamp(start),
                end=_format_timestamp(end),
                sourceText=text,
                translatedText="",
                adaptedText="",
                emotion="Neutral",
                intensity=35,
                pace=100,
                fit=0,
                locked=False,
            )
        )
    state = ProjectAnalysisState(
        speakers=[speaker],
        segments=records,
        updated_at=datetime.now(timezone.utc).isoformat(),
        source_language=str(project.get("source_language") or asr.get("language") or "en"),
        target_language=str(project.get("target_language") or "fr"),
        narrative_profile="natural_recap",
        narrative_instructions=(
            "Natural premium French recap. Preserve every fact while using concise "
            "spoken phrasing that fits at normal speed."
        ),
        last_operation="open_source_test_prepared",
    )
    _write_analysis_state(test_dir, state)

    asr.update(
        {
            "project_id": test_id,
            "status": "completed",
            "segmentation": {
                "strategy": "complete-sentence-word-timestamps-v2",
                "preferred_seconds": 6.5,
                "maximum_seconds": 10.5,
                "raw_segment_count": len(raw_segments),
                "segment_count": len(manifest_rows),
            },
            "segments": manifest_rows,
        }
    )
    write_json(test_dir / "analysis" / "asr_manifest.json", asr)
    return {
        "project_id": test_id,
        "reused": False,
        "video_seconds": duration,
        "raw_segments": len(raw_segments),
        "segments": len(records),
        "maximum_segment_seconds": max(
            float(row["end"]) - float(row["start"]) for row in manifest_rows
        ),
    }


def progress(percent: int, message: str) -> None:
    print(
        json.dumps(
            {
                "time": datetime.now(timezone.utc).isoformat(),
                "progress": percent,
                "message": message,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


def run_translation(test_id: str) -> dict[str, Any]:
    project_dir = PATHS.projects / test_id
    state = _read_or_create_analysis_state(project_dir)
    started = time.perf_counter()
    result = _run_stub_job(
        test_id,
        project_dir,
        state,
        "translation",
        datetime.now(timezone.utc).isoformat(),
        {
            "engine_id": "translation-madlad400-3b-int8",
            "mode": "studio",
            "narrative_profile": "natural_recap",
            "narrative_instructions": (
                "Natural premium French recap. Preserve every fact while using "
                "concise spoken phrasing that fits at normal speed."
            ),
        },
        progress,
        lambda: False,
    )
    return {
        "status": result.status,
        "message": result.message,
        "seconds": round(time.perf_counter() - started, 2),
        "artifacts": result.artifacts,
    }


def run_voice(test_id: str, profile_id: str) -> dict[str, Any]:
    project_dir = PATHS.projects / test_id
    state = _read_or_create_analysis_state(project_dir)
    for speaker in state.speakers:
        speaker.voice_profile_id = profile_id
        speaker.voice_engine = "kokoro"
        speaker.voice_model = "tts-kokoro-82m"
    state.updated_at = datetime.now(timezone.utc).isoformat()
    state.last_operation = "open_source_voice_assigned"
    _write_analysis_state(project_dir, state)
    started = time.perf_counter()
    result = _run_stub_job(
        test_id,
        project_dir,
        state,
        "voice_generation",
        datetime.now(timezone.utc).isoformat(),
        {},
        progress,
        lambda: False,
    )
    return {
        "status": result.status,
        "message": result.message,
        "seconds": round(time.perf_counter() - started, 2),
        "artifacts": result.artifacts,
    }


def run_voice_script(test_id: str) -> dict[str, Any]:
    project_dir = PATHS.projects / test_id
    state = _read_or_create_analysis_state(project_dir)
    engine = next(
        (
            item
            for item in list_engines()
            if str(item.get("id")) in {
                "translation-qwen3-4b-q5",
                "translation-qwen3-4b-q4",
            }
            and item.get("installation", {}).get("status") == "ready"
        ),
        None,
    )
    if not engine:
        raise RuntimeError("The open-source Qwen voice-script adapter is not ready")
    started = time.perf_counter()
    result, artifacts = _adapt_voice_script(
        project_dir,
        state,
        engine,
        on_progress=progress,
        is_cancelled=lambda: False,
    )
    return {
        "status": "completed",
        "seconds": round(time.perf_counter() - started, 2),
        "groups": len(result.get("groups") or []),
        "timing_overflow_groups": sum(
            bool(item.get("timing_overflow"))
            for item in (result.get("groups") or [])
            if isinstance(item, dict)
        ),
        "artifacts": artifacts,
    }


def run_export(test_id: str) -> dict[str, Any]:
    project_dir = PATHS.projects / test_id
    state = _read_or_create_analysis_state(project_dir)
    options = export_service.normalise_options(
        {
            "container": "mp4",
            "video_codec": "copy",
            "audio_codec": "aac",
            "delivery": "full",
            "resolution": "source",
            "aspect": "source",
            "upscale": "off",
        }
    )
    started = time.perf_counter()
    result = _run_stub_job(
        test_id,
        project_dir,
        state,
        "export",
        datetime.now(timezone.utc).isoformat(),
        options,
        progress,
        lambda: False,
    )
    return {
        "status": result.status,
        "message": result.message,
        "seconds": round(time.perf_counter() - started, 2),
        "artifacts": result.artifacts,
    }


def report(test_id: str) -> dict[str, Any]:
    project_dir = PATHS.projects / test_id
    project = read_json(project_dir / "project.json")
    media = read_json(project_dir / "analysis" / "media_manifest.json")
    state = _read_or_create_analysis_state(project_dir)
    durations = [
        max(
            0.1,
            sum(
                float(part) * multiplier
                for part, multiplier in zip(
                    segment.end.split(":"),
                    (3600, 60, 1),
                    strict=True,
                )
            )
            - sum(
                float(part) * multiplier
                for part, multiplier in zip(
                    segment.start.split(":"),
                    (3600, 60, 1),
                    strict=True,
                )
            ),
        )
        for segment in state.segments
    ]
    translated = [segment for segment in state.segments if segment.translatedText.strip()]
    adapted = [segment for segment in state.segments if segment.adaptedText.strip()]
    overflow = 0
    final_path = project_dir / "analysis" / "translation_final.json"
    translation_payload = read_json(final_path) if final_path.is_file() else {}
    translation_rows = list(translation_payload.get("translations") or [])
    overflow = sum(bool(row.get("timing_overflow")) for row in translation_rows)
    low_fidelity = sum(
        int(row.get("fidelity_score") or 0) < 90 for row in translation_rows
    )

    voice_path = project_dir / "audio" / "voice_manifest.json"
    voice = read_json(voice_path) if voice_path.is_file() else {}
    takes = list(voice.get("segments") or [])
    voice_script_path = project_dir / "analysis" / "voice_script.json"
    voice_script = (
        read_json(voice_script_path) if voice_script_path.is_file() else {}
    )
    voice_script_rows = list(voice_script.get("groups") or [])
    tempo_ratios = [
        float(take.get("tempo_ratio") or 1.0)
        for take in takes
        if isinstance(take, dict)
    ]
    return {
        "project_id": test_id,
        "source_path": project.get("source_path"),
        "video_seconds": round(
            float((media.get("media") or {}).get("duration_seconds") or 0),
            3,
        ),
        "speech_seconds": round(sum(durations), 3),
        "timeline_end_seconds": max(
            (
                sum(
                    float(part) * multiplier
                    for part, multiplier in zip(
                        segment.end.split(":"),
                        (3600, 60, 1),
                        strict=True,
                    )
                )
                for segment in state.segments
            ),
            default=0,
        ),
        "segments": len(state.segments),
        "translated_segments": len(translated),
        "adapted_segments": len(adapted),
        "translation_fragment_budget_flags": overflow,
        "voice_script_conservative_flags": sum(
            bool(row.get("timing_overflow"))
            for row in voice_script_rows
            if isinstance(row, dict)
        ),
        "low_fidelity_segments": low_fidelity,
        "voice_takes": len(takes),
        "voice_failures": len(voice.get("failed_segments") or []),
        "maximum_tempo_ratio": max(tempo_ratios, default=1.0),
        "above_1_08": sum(ratio > 1.0801 for ratio in tempo_ratios),
        "last_operation": state.last_operation,
    }


def main() -> None:
    args = parse_args()
    if args.stage == "prepare":
        payload = prepare(args.source_project, args.test_project)
    elif args.stage == "translate":
        payload = run_translation(args.test_project)
    elif args.stage == "voice":
        payload = run_voice(args.test_project, args.profile_id)
    elif args.stage == "voice-script":
        payload = run_voice_script(args.test_project)
    elif args.stage == "export":
        payload = run_export(args.test_project)
    else:
        payload = report(args.test_project)
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
