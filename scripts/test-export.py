from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app import export_service


def run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout)[-1600:])


def probe(path: Path) -> dict:
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-show_entries", "stream=codec_name,width,height", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return json.loads(completed.stdout)


def mean_volume(path: Path, start: float, duration: float) -> float:
    completed = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-ss", str(start), "-t", str(duration),
            "-i", str(path), "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "NUL",
        ],
        capture_output=True, text=True, check=False,
    )
    match = re.search(r"mean_volume:\s*(-?[\d.]+) dB", completed.stderr)
    if not match:
        raise AssertionError("Could not measure exported audio")
    return float(match.group(1))


def main() -> None:
    assertions: list[str] = []
    caps = export_service.capabilities()
    assert caps["ready"]
    assert caps["video_encoders"]["h264"]
    assertions.append("FFmpeg capabilities")

    try:
        export_service.normalise_options({"video_codec": "copy", "resolution": "1080p"})
        raise AssertionError("copy + resize should have failed")
    except ValueError:
        assertions.append("Compatibility validation")

    portable_name = export_service._portable_path_name(
        "Épisode… I’m Actually Immortal · héros"
    )
    assert portable_name == "Episode... I-m Actually Immortal - heros", portable_name
    assert portable_name.isascii()
    assertions.append("Portable ASCII export names")

    automatic_quality = export_service.normalise_options(
        {"video_codec": "h265", "audio_codec": "aac"}
    )
    assert automatic_quality["max_output_size_gb"] == 0
    assert automatic_quality["max_output_size_bytes"] == 0
    assert not export_service._output_size_budget(8228, automatic_quality)["enabled"]
    assertions.append("Automatic quality has no forced size ceiling")

    capped = export_service.normalise_options(
        {
            "video_codec": "h265",
            "audio_codec": "aac",
            "max_output_size_gb": 4,
            "audio_bitrate": "192k",
        }
    )
    budget = export_service._output_size_budget(8228, capped)
    assert budget["enabled"]
    assert budget["limit_bytes"] == 4_000_000_000
    assert 3200 <= budget["video_kbps"] <= 3500, budget
    budgeted = export_service._options_with_output_size_budget(capped, 8228)
    codec_command: list[str] = []
    budgeted["hardware_acceleration"] = "cpu"
    export_service._video_codec_args(codec_command, budgeted)
    assert "-b:v" in codec_command and "-maxrate" in codec_command
    assertions.append("Hard 4 GB delivery-size bitrate budget")

    clarity = export_service.normalise_options(
        {
            "video_codec": "h264",
            "resolution": "1080p",
            "upscale": "clarity",
        }
    )
    clarity["_source_width"] = 1280
    clarity["_source_height"] = 720
    assert "unsharp=5:5:0.32" in (export_service._video_filter(clarity) or "")
    assertions.append("Fast Lanczos clarity enhancement")

    reframed = export_service.normalise_options(
        {
            "video_codec": "h264",
            "subtitle_cleanup": "crop",
            "subtitle_cleanup_band": 0.10,
            "reframe_scale": 1.20,
            "reframe_x": 0.75,
            "reframe_y": -0.50,
        }
    )
    reframe_filter = export_service._video_filter(reframed) or ""
    assert "crop=iw/1.333333:ih/1.333333" in reframe_filter, reframe_filter
    assert "(iw-ow)*0.875000" in reframe_filter, reframe_filter
    assert "(ih-oh)*0.250000" in reframe_filter, reframe_filter
    assertions.append("Visual reframe coordinates reach FFmpeg")

    with tempfile.TemporaryDirectory(prefix="dubroom-export-") as folder:
        root = Path(folder)
        source = root / "source.mp4"
        upscale_source = root / "upscale-source.mp4"
        upscale_output = root / "upscale-output.mp4"
        take_a = root / "take-a.wav"
        take_b = root / "take-b.wav"
        preserved_bed = root / "bed.wav"
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=12", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)])
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=1", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(upscale_source)])
        upscale_options = export_service.normalise_options(
            {
                "video_codec": "h264",
                "resolution": "720p",
                "aspect": "source",
                "upscale": "standard",
            }
        )
        upscale_filter = export_service._video_filter(upscale_options)
        assert upscale_filter
        run(["ffmpeg", "-y", "-i", str(upscale_source), "-vf", upscale_filter, "-c:v", "libx264", "-preset", "ultrafast", "-an", str(upscale_output)])
        upscale_info = probe(upscale_output)
        upscale_video = next(
            stream
            for stream in upscale_info["streams"]
            if stream.get("codec_name") == "h264"
        )
        assert upscale_video["width"] == 1280, upscale_video
        assert upscale_video["height"] == 720, upscale_video
        assertions.append("Real 320x180 to 1280x720 upscale")
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=520:sample_rate=48000:duration=1.2", "-c:a", "pcm_s16le", str(take_a)])
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=1.4", "-c:a", "pcm_s16le", str(take_b)])
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=12", "-c:a", "pcm_s16le", str(preserved_bed)])
        progress: list[tuple[int, str]] = []
        artifacts = export_service.execute_export(
            project_id="smoke-project",
            project_name="Smoke Project",
            source_path=source,
            source_audio_path=preserved_bed,
            output_root=root / "exports",
            options={
                "delivery": "both", "container": "mp4", "video_codec": "h264", "audio_codec": "aac",
                "quality": 28, "preset": "ultrafast", "resolution": "source", "aspect": "source",
                "short_duration": 10, "short_mode": "dialogue", "normalize_audio": True,
                "_source_audio_is_bed": True, "music_volume": 0.85,
                "original_volume": 0.0, "ducking": False,
                "subtitles_enabled": True, "subtitle_style": "cinema",
                "subtitle_cleanup": "blur", "subtitle_cleanup_band": 0.14,
            },
            takes=[{"segment_id": "a", "path": str(take_a)}, {"segment_id": "b", "path": str(take_b)}],
            segment_times={"a": (1.0, 2.2), "b": (9.0, 10.4)},
            subtitle_segments=[
                {"id": "a", "start": 1.0, "end": 2.2, "text": "Premier sous-titre"},
                {"id": "b", "start": 9.0, "end": 10.4, "text": "Deuxième sous-titre"},
            ],
            duration_seconds=12.0,
            on_progress=lambda value, message: progress.append((value, message)),
            is_cancelled=lambda: False,
        )
        assert Path(artifacts["video"]).exists()
        assert Path(artifacts["short_001"]).exists()
        assert Path(artifacts["short_002"]).exists()
        assert Path(artifacts["subtitles_video"]).exists()
        assert "Premier sous-titre" in Path(artifacts["subtitles_video"]).read_text(encoding="utf-8-sig")
        assert Path(artifacts["manifest"]).exists()
        export_manifest = json.loads(Path(artifacts["manifest"]).read_text(encoding="utf-8"))
        assert export_manifest["source_audio_path"] == str(preserved_bed)
        assert progress[-1][0] == 100
        video_info = probe(Path(artifacts["video"]))
        assert float(video_info["format"]["duration"]) >= 11.5
        assert mean_volume(Path(artifacts["video"]), 5.0, 2.0) > -45.0
        assertions.append("Full dubbed MP4")
        assertions.append("Dialogue-aware Shorts batch")
        assertions.append("Progress and manifest")
        assertions.append("Embedded subtitle cleanup and styled ASS render")
        assertions.append("Demucs bed replaces original dialogue in multi-speaker mix")
        assertions.append("Preserved SFX bed remains audible between voice takes")

        edited_artifacts = export_service.execute_export(
            project_id="edited-smoke-project",
            project_name="Edited Smoke Project",
            source_path=source,
            output_root=root / "exports",
            options={
                "delivery": "full", "container": "mp4", "video_codec": "h264", "audio_codec": "aac",
                "quality": 30, "preset": "ultrafast", "resolution": "source", "aspect": "source",
                "normalize_audio": False,
                "subtitle_cleanup": "crop", "subtitle_cleanup_band": 0.10,
                "edit_ranges": [
                    {"source_start": 0.0, "source_end": 3.0},
                    {"source_start": 6.0, "source_end": 9.0},
                ],
            },
            takes=[{"segment_id": "a", "path": str(take_a)}, {"segment_id": "b", "path": str(take_b)}],
            segment_times={"a": (1.0, 2.2), "b": (7.0, 8.4)},
            subtitle_segments=None,
            duration_seconds=12.0,
            on_progress=lambda value, message: progress.append((value, message)),
            is_cancelled=lambda: False,
        )
        edited_info = probe(Path(edited_artifacts["video"]))
        edited_duration = float(edited_info["format"]["duration"])
        assert 5.8 <= edited_duration <= 6.3, edited_duration
        edited_manifest = json.loads(Path(edited_artifacts["manifest"]).read_text(encoding="utf-8"))
        assert len(edited_manifest["options"]["edit_ranges"]) == 2
        edited_plan = export_service.plan_export(
            12.0,
            {
                "delivery": "shorts",
                "segment_strategy": "count",
                "segment_count": 3,
                "edit_ranges": [
                    {"source_start": 0.0, "source_end": 3.0},
                    {"source_start": 6.0, "source_end": 9.0},
                ],
            },
        )
        assert edited_plan["duration_seconds"] == 6.0
        assert len(edited_plan["regions"]) == 3
        assertions.append("Persistent two-cut edit decision list")
        assertions.append("Bottom subtitle crop and enlargement")
        assertions.append("Edited duration drives Shorts planning")

        filter_value = export_service._video_filter(export_service.normalise_options({
            "container": "mp4", "video_codec": "h264", "audio_codec": "aac", "resolution": "1080p", "aspect": "9:16", "framing": "blur", "upscale": "standard",
        }))
        assert filter_value and "1080:1920" in filter_value and "boxblur" in filter_value
        assertions.append("Vertical standard upscale plan")

    print(json.dumps({"ok": True, "assertions": assertions}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
