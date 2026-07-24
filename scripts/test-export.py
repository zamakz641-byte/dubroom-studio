from __future__ import annotations

import json
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

    with tempfile.TemporaryDirectory(prefix="dubroom-export-") as folder:
        root = Path(folder)
        source = root / "source.mp4"
        take_a = root / "take-a.wav"
        take_b = root / "take-b.wav"
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=12", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=12", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)])
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=520:sample_rate=48000:duration=1.2", "-c:a", "pcm_s16le", str(take_a)])
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=660:sample_rate=48000:duration=1.4", "-c:a", "pcm_s16le", str(take_b)])
        progress: list[tuple[int, str]] = []
        artifacts = export_service.execute_export(
            project_id="smoke-project",
            project_name="Smoke Project",
            source_path=source,
            output_root=root / "exports",
            options={
                "delivery": "both", "container": "mp4", "video_codec": "h264", "audio_codec": "aac",
                "quality": 28, "preset": "ultrafast", "resolution": "source", "aspect": "source",
                "short_duration": 10, "short_mode": "dialogue", "normalize_audio": True,
            },
            takes=[{"segment_id": "a", "path": str(take_a)}, {"segment_id": "b", "path": str(take_b)}],
            segment_times={"a": (1.0, 2.2), "b": (9.0, 10.4)},
            duration_seconds=12.0,
            on_progress=lambda value, message: progress.append((value, message)),
            is_cancelled=lambda: False,
        )
        assert Path(artifacts["video"]).exists()
        assert Path(artifacts["short_001"]).exists()
        assert Path(artifacts["short_002"]).exists()
        assert Path(artifacts["manifest"]).exists()
        assert progress[-1][0] == 100
        video_info = probe(Path(artifacts["video"]))
        assert float(video_info["format"]["duration"]) >= 11.5
        assertions.append("Full dubbed MP4")
        assertions.append("Dialogue-aware Shorts batch")
        assertions.append("Progress and manifest")

        edited_artifacts = export_service.execute_export(
            project_id="edited-smoke-project",
            project_name="Edited Smoke Project",
            source_path=source,
            output_root=root / "exports",
            options={
                "delivery": "full", "container": "mp4", "video_codec": "h264", "audio_codec": "aac",
                "quality": 30, "preset": "ultrafast", "resolution": "source", "aspect": "source",
                "normalize_audio": False,
                "edit_ranges": [
                    {"source_start": 0.0, "source_end": 3.0},
                    {"source_start": 6.0, "source_end": 9.0},
                ],
            },
            takes=[{"segment_id": "a", "path": str(take_a)}, {"segment_id": "b", "path": str(take_b)}],
            segment_times={"a": (1.0, 2.2), "b": (7.0, 8.4)},
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
        assertions.append("Edited duration drives Shorts planning")

        filter_value = export_service._video_filter(export_service.normalise_options({
            "container": "mp4", "video_codec": "h264", "audio_codec": "aac", "resolution": "1080p", "aspect": "9:16", "framing": "blur", "upscale": "standard",
        }))
        assert filter_value and "1080:1920" in filter_value and "boxblur" in filter_value
        assertions.append("Vertical standard upscale plan")

    print(json.dumps({"ok": True, "assertions": assertions}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
