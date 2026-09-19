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
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout)[-2500:])


def main() -> None:
    caps = export_service.capabilities()
    for name in ("aresample", "highpass", "acompressor", "loudnorm", "alimiter"):
        assert caps["filters"][name], name
    options = export_service.normalise_options({})
    assert options["audio_mastering"] is True
    assert options["normalize_audio"] is True

    with tempfile.TemporaryDirectory(prefix="dubroom-mastering-") as folder:
        root = Path(folder)
        source = root / "source.mp4"
        voice = root / "voice.wav"
        mastered = root / "mastered.wav"
        run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:size=320x180:rate=24:duration=4",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=180:sample_rate=44100:duration=4",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-c:a",
                "aac",
                "-shortest",
                str(source),
            ]
        )
        run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=520:sample_rate=24000:duration=1.4",
                "-c:a",
                "pcm_s16le",
                str(voice),
            ]
        )
        progress: list[tuple[int, str]] = []
        export_service._render_mix(
            source,
            mastered,
            [{"segment_id": "line", "path": str(voice)}],
            {"line": (0.8, 2.2)},
            4.0,
            options,
            lambda value, label: progress.append((value, label)),
            lambda: False,
        )
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_name,sample_rate,channels,bits_per_raw_sample",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(mastered),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        probe = json.loads(result.stdout)
        stream = probe["streams"][0]
        assert stream["codec_name"] == "pcm_s24le", stream
        assert stream["sample_rate"] == "48000", stream
        assert stream["channels"] == 2, stream
        duration = float(probe["format"]["duration"])
        assert 3.9 <= duration <= 4.1, duration
        print(
            json.dumps(
                {
                    "ok": True,
                    "sample_rate": 48000,
                    "internal_codec": "pcm_s24le",
                    "channels": 2,
                    "duration_seconds": duration,
                    "filters": [
                        "soxr",
                        "highpass",
                        "acompressor",
                        "loudnorm",
                        "alimiter",
                    ],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
