from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock


WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from services.api.app import audio_preservation_service as service
from services.api.app.shared_dependency_service import resolve_shared_dependencies


FAKE_WORKER = r'''
import argparse
import json
import shutil
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--input", required=True)
parser.add_argument("--output-dir", required=True)
parser.add_argument("--output", required=True)
parser.add_argument("--progress-file", required=True)
parser.add_argument("--fail", action="store_true")
args = parser.parse_args()
if args.fail:
    raise SystemExit(7)
output_dir = Path(args.output_dir)
output_dir.mkdir(parents=True, exist_ok=True)
for name in ("vocals.wav", "bed.wav"):
    shutil.copy2(args.input, output_dir / name)
Path(args.progress_file).write_text(json.dumps({"progress": 99, "message": "fake stems ready"}), encoding="utf-8")
Path(args.output).write_text(json.dumps({"status": "ready", "runtime": {"test": True}}), encoding="utf-8")
'''


def make_source(path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for this test")
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:r=24:d=1.2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=1.2",
            "-shortest",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


def runtime_stub() -> dict[str, object]:
    return {
        "usable": True,
        "python": sys.executable,
        "worker": "fake",
        "shared_dependencies": {"status": "ready", "paths": [], "providers": {}, "missing": []},
    }


def fake_command(worker: Path, *, fail: bool = False):
    def build(
        _runtime: dict[str, object],
        source_path: Path,
        output_dir: Path,
        output_path: Path,
        progress_path: Path,
        _options: dict[str, object],
    ) -> list[str]:
        command = [
            sys.executable,
            str(worker),
            "--input",
            str(source_path),
            "--output-dir",
            str(output_dir),
            "--output",
            str(output_path),
            "--progress-file",
            str(progress_path),
        ]
        if fail:
            command.append("--fail")
        return command

    return build


def assert_shared_runtime() -> dict[str, object]:
    demucs_python = (
        service.PATHS.environments
        / "demucs-separation"
        / "venv"
        / "Scripts"
        / "python.exe"
    )
    resolved = resolve_shared_dependencies(demucs_python, ["numpy"])
    assert resolved["status"] == "ready", resolved
    assert not resolved["missing"], resolved
    return resolved


def run_test() -> dict[str, object]:
    shared = assert_shared_runtime()
    with tempfile.TemporaryDirectory(prefix="dubroom-audio-preservation-") as raw_temp:
        temp = Path(raw_temp)
        source = temp / "source.mp4"
        project = temp / "project-ok"
        failed_project = temp / "project-failed"
        worker = temp / "fake-worker.py"
        worker.write_text(FAKE_WORKER, encoding="utf-8")
        make_source(source)

        progress: list[tuple[int, str]] = []
        with (
            mock.patch.object(service, "_runtime", return_value=runtime_stub()),
            mock.patch.object(service, "_worker_command", side_effect=fake_command(worker)) as command_mock,
        ):
            first = service.run(
                project,
                source,
                on_progress=lambda value, message: progress.append((value, message)),
            )
            assert first["status"] == "completed"
            assert command_mock.call_count == 1
            ready = service.status(project)
            assert ready["status"] == "ready", ready
            assert all(ready["tracks"].values()), ready
            assert service.track_path(project, "bed") is not None
            assert service.track_path(project, "invalid") is None

            cached = service.run(project, source)
            assert cached["manifest"]["cache_hit"] is True
            assert command_mock.call_count == 1, "cache should bypass the worker"

            forced = service.run(project, source, {"force": True})
            assert forced["manifest"]["cache_hit"] is False
            assert command_mock.call_count == 2, "explicit reprocess should run the worker"

        with (
            mock.patch.object(service, "_runtime", return_value=runtime_stub()),
            mock.patch.object(service, "_worker_command", side_effect=fake_command(worker, fail=True)),
        ):
            try:
                service.run(failed_project, source)
            except RuntimeError:
                pass
            else:
                raise AssertionError("worker failure should propagate")
        failed = service.status(failed_project)
        assert failed["status"] == "failed", failed
        assert failed["error"], failed
        assert not any(failed["tracks"].values()), failed

        return {
            "shared_dependencies": shared["providers"],
            "first_run": first["manifest"]["status"],
            "cache_hit": cached["manifest"]["cache_hit"],
            "forced_reprocess": forced["manifest"]["status"],
            "failure_status": failed["status"],
            "progress_events": len(progress),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(json.dumps(run_test(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
