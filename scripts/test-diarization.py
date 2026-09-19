from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from services.api.app import diarization_service as service


FAKE_WORKER = r'''
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--model-path", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--progress-file", required=True)
parser.add_argument("--device", required=True)
parser.add_argument("--min-speakers")
parser.add_argument("--max-speakers")
args = parser.parse_args()
turns = [
    {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
    {"start": 2.0, "end": 4.5, "speaker": "SPEAKER_01"},
]
Path(args.progress_file).write_text(json.dumps({"progress": 90, "message": "fake diarization ready"}), encoding="utf-8")
Path(args.output).write_text(json.dumps({
    "status": "completed",
    "device": args.device,
    "duration": 5.0,
    "elapsed_seconds": 0.1,
    "speaker_count": 2,
    "speakers": ["SPEAKER_00", "SPEAKER_01"],
    "turns": turns,
    "regular_turns": turns,
}), encoding="utf-8")
'''


class FakeSegment:
    def __init__(self, segment_id: str, start: str, end: str) -> None:
        self.payload = {
            "id": segment_id,
            "left": 0.0,
            "width": 10.0,
            "lane": 0,
            "speaker": "Speaker 1",
            "label": segment_id,
            "color": "#000000",
            "start": start,
            "end": end,
            "sourceText": segment_id,
            "translatedText": "",
            "adaptedText": "",
            "emotion": "Neutral",
            "intensity": 35,
            "pace": 100,
            "fit": 0,
            "locked": False,
        }
        for key, value in self.payload.items():
            setattr(self, key, value)

    def model_dump(self):
        return dict(self.payload)


def make_vocals(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for this test")
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=5", "-c:a", "pcm_s16le", str(path)],
        check=True,
    )


def run_test() -> dict[str, object]:
    actual_runtime = service.runtime_status()
    assert actual_runtime["runtime_ready"], actual_runtime
    with tempfile.TemporaryDirectory(prefix="dubroom-diarization-") as raw_temp:
        temp = Path(raw_temp)
        project = temp / "project"
        model = temp / "model"
        worker = temp / "fake-worker.py"
        model.mkdir()
        (model / "config.yaml").write_text("version: 3.1\n", encoding="utf-8")
        worker.write_text(FAKE_WORKER, encoding="utf-8")
        make_vocals(project / "audio" / "separation" / "vocals.wav")
        runtime = {
            "engine_id": service.ENGINE_ID,
            "model_repo": service.MODEL_REPO,
            "python": sys.executable,
            "execution_provider": "test-shared-runtime",
            "shared_runtime": True,
            "device": "cpu",
            "runtime_ready": True,
            "model_ready": True,
            "model_path": str(model),
            "worker": str(worker),
            "adapter_ready": True,
            "usable": True,
            "requires_hf_token": False,
            "message": "test",
        }
        progress: list[tuple[int, str]] = []
        with mock.patch.object(service, "runtime_status", return_value=runtime):
            first = service.run(project, on_progress=lambda value, message: progress.append((value, message)))
            assert first["status"] == "completed", first
            current = service.status(project)
            assert current["status"] == "ready", current
            assert current["speaker_count"] == 2, current
            assert current["turn_count"] == 2, current
            cached = service.run(project)
            assert cached["manifest"]["cache_hit"] is True, cached

        existing = [
            SimpleNamespace(
                name="Speaker 1", color="#112233", level=77,
                voice_profile_id="omnivoice-M01", voice_engine="omnivoice",
                voice_model="M01", voice_instruct="calm", effects_chain=[],
            )
        ]
        speakers, segments = service.apply_to_analysis(
            existing,
            [FakeSegment("a", "00:00:00.100", "00:00:01.600"), FakeSegment("b", "00:00:02.200", "00:00:04.000")],
            first["manifest"],
        )
        # Acoustic cluster order is temporary. Re-diarization deliberately
        # preserves the previous voice on the strongest-overlap cluster, even
        # when that cluster is not the first one in the file.
        assert {item["name"] for item in speakers} == {"Speaker 1", "Speaker 2"}
        preserved = next(item for item in speakers if item["name"] == "Speaker 1")
        assert preserved["voice_profile_id"] == "omnivoice-M01"
        assert {item["speaker"] for item in segments} == {"Speaker 1", "Speaker 2"}
        return {
            "shared_runtime": actual_runtime["execution_provider"],
            "model_ready": actual_runtime["model_ready"],
            "speakers": current["speaker_count"],
            "turns": current["turn_count"],
            "cache_hit": cached["manifest"]["cache_hit"],
            "voice_assignment_preserved": preserved["voice_profile_id"],
            "progress_events": len(progress),
        }


if __name__ == "__main__":
    print(json.dumps(run_test(), ensure_ascii=False, indent=2))
