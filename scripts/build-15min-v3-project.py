from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "sss-first-15min-v3"
PROJECT = ROOT / "projects" / PROJECT_ID
SOURCE = PROJECT / "source" / "source-first-15min.mp4"
AUDIO = PROJECT / "audio" / "source_16k_mono.wav"
ASR = PROJECT / "analysis" / "asr" / "paraformer-zh-first-15min.json"
FULL_DIARIZATION = (
    ROOT
    / "projects"
    / "sss-20260808-183800"
    / "analysis"
    / "diarization"
    / "diarization-manifest.json"
)


def stamp(seconds: float) -> str:
    milliseconds = max(0, round(float(seconds) * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole:02d}.{milliseconds:03d}"


def media_probe() -> dict:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,r_frame_rate,channels,sample_rate",
        "-of",
        "json",
        str(SOURCE),
    ]
    return json.loads(subprocess.check_output(command, text=True, encoding="utf-8"))


def frame_rate(value: str) -> float:
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        return float(numerator) / max(1.0, float(denominator))
    return float(value or 0)


def main() -> None:
    for required in (SOURCE, AUDIO, ASR, FULL_DIARIZATION):
        if not required.is_file():
            raise FileNotFoundError(required)

    asr = json.loads(ASR.read_text(encoding="utf-8-sig"))
    source_segments = [item for item in asr.get("segments", []) if item.get("text")]
    duration = float(asr.get("duration") or 900.0)
    now = datetime.now(timezone.utc).isoformat()

    palette = ["#8B5CF6", "#06B6D4", "#F59E0B", "#EC4899", "#10B981", "#3B82F6"]
    segments = []
    for index, item in enumerate(source_segments, start=1):
        start = max(0.0, float(item.get("start") or 0.0))
        end = min(duration, max(start + 0.1, float(item.get("end") or start + 0.1)))
        segments.append(
            {
                "id": f"zh15-{index:03d}",
                "left": round(start / duration * 100, 4),
                "width": round((end - start) / duration * 100, 4),
                "lane": 0,
                "speaker": "Acoustic evidence",
                "acousticSpeaker": "UNCLUSTERED",
                "label": "Acoustic evidence",
                "color": palette[0],
                "start": stamp(start),
                "end": stamp(end),
                "sourceText": str(item.get("text") or "").strip(),
                "translatedText": "",
                "adaptedText": "",
                "rawTranslation": "",
                "fidelityScore": None,
                "fidelityIssues": [],
                "voiceAudioReady": False,
                "voiceAudioDuration": None,
                "voiceAudioEngine": None,
                "voiceAudioStatus": None,
                "voiceSkip": False,
                "emotion": "neutral",
                "omnivoiceTag": None,
                "omnivoiceEvents": [],
                "intensity": 50,
                "pace": 100,
                "fit": 0,
                "locked": False,
            }
        )

    speakers = [
        {
            "name": "Acoustic evidence",
            "role": "Temporary acoustic evidence only; GPT resolves the real identities",
            "duration": "15m 00s",
            "color": palette[0],
            "level": 82,
            "voice_profile_id": None,
            "voice_engine": None,
            "voice_model": None,
            "voice_instruct": None,
            "effects_chain": [],
            "character_id": None,
            "voice_key": "unknown",
            "detected_sex": "uncertain",
            "detected_age_group": "unknown",
        }
    ]
    state = {
        "speakers": speakers,
        "segments": segments,
        "updated_at": now,
        "source_language": "zh",
        "target_language": "en",
        "revision": 1,
        "narrative_profile": "natural_recap",
        "narrative_instructions": (
            "External third-person narrator for exposition; stable MC voice only for audible "
            "dialogue or explicit inner monologue. Resolve all recurring characters globally."
        ),
        "last_operation": "paraformer_zh_cuda",
        "mix": {
            "voice_volume": 1.0,
            "original_volume": 0.0,
            "music_volume": 0.5,
            "voice_muted": False,
            "original_muted": False,
            "music_muted": False,
            "normalize": True,
            "ducking": True,
            "music_path": None,
        },
    }

    probe = media_probe()
    video = next(stream for stream in probe["streams"] if stream.get("codec_type") == "video")
    audio = next(stream for stream in probe["streams"] if stream.get("codec_type") == "audio")
    fmt = probe["format"]
    media_manifest = {
        "project_id": PROJECT_ID,
        "created_at": now,
        "source_video_path": str(SOURCE.resolve()),
        "audio_path": str(AUDIO.resolve()),
        "waveform_peaks": [],
        "source_language": "zh",
        "target_language": "en",
        "output_aspect": "source",
        "content_type": "anime",
        "dubbing_mode": "multi",
        "media": {
            "path": str(SOURCE.resolve()),
            "file_name": SOURCE.name,
            "duration_seconds": float(fmt.get("duration") or duration),
            "size_bytes": int(fmt.get("size") or SOURCE.stat().st_size),
            "format_name": fmt.get("format_name"),
            "video": {
                "codec": video.get("codec_name"),
                "width": int(video.get("width") or 0),
                "height": int(video.get("height") or 0),
                "fps": frame_rate(str(video.get("r_frame_rate") or "0")),
            },
            "audio": {
                "codec": audio.get("codec_name"),
                "channels": int(audio.get("channels") or 0),
                "sample_rate": int(audio.get("sample_rate") or 0),
            },
        },
    }
    project_record = {
        "id": PROJECT_ID,
        "name": "SSS Sacrificial Mage — test 15 min Multi-Speaker V3",
        "status": "prepared",
        "project_dir": str(PROJECT.resolve()),
        "source_path": str(SOURCE.resolve()),
        "original_source_path": None,
        "derived_sources": [],
        "media_manifest_path": str((PROJECT / "analysis" / "media_manifest.json").resolve()),
        "source_language": "zh",
        "target_language": "en",
        "output_aspect": "source",
        "performance_profile": "gpu_quality",
        "content_type": "anime",
        "dubbing_mode": "multi",
        "created_at": now,
        "updated_at": now,
    }

    (PROJECT / "analysis").mkdir(parents=True, exist_ok=True)
    (PROJECT / "analysis" / "diarization").mkdir(parents=True, exist_ok=True)
    (PROJECT / "project.json").write_text(json.dumps(project_record, ensure_ascii=False, indent=2), encoding="utf-8")
    (PROJECT / "analysis" / "media_manifest.json").write_text(json.dumps(media_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (PROJECT / "analysis" / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (PROJECT / "analysis" / "asr_manifest.json").write_text(json.dumps(asr, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copy2(FULL_DIARIZATION, PROJECT / "analysis" / "diarization" / "diarization-manifest.json")

    sys.path.insert(0, str(ROOT))
    from services.api.app import transcript_exchange_service

    payload = transcript_exchange_service.build_exchange_payload(
        project_id=PROJECT_ID,
        project_name=project_record["name"],
        state=state,
        project_dir=PROJECT,
    )
    result = transcript_exchange_service.write_export(
        project_dir=PROJECT,
        payload=payload,
        export_format="manifest",
        chunk_size=60,
    )
    print(json.dumps({"segments": len(segments), "duration": duration, "export": result}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
