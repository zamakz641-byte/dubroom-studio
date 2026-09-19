from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app import native_tts_service, resource_scheduler, voice_reference_service
from services.api.app.config import PATHS


def main() -> None:
    reference = (
        PATHS.data
        / "voice-samples"
        / "original-narrators"
        / "fr-narrateur-cinematique.wav"
    )
    transcription = voice_reference_service.transcribe_reference(str(reference))
    assert transcription["device"] == "cuda", transcription
    assert "royaume" in transcription["text"].lower(), transcription

    engine_id = "tts-qwen3-0.6b-base"
    python_executable = native_tts_service._runtime_python(engine_id)
    worker = PATHS.installers / "run-tts.py"
    with tempfile.TemporaryDirectory(prefix="dubroom-qwen-after-whisper-") as folder:
        test_root = Path(folder)
        output = test_root / "qwen-after-whisper.wav"
        request_path = test_root / "request.json"
        request = {
            "family": "qwen3",
            "variant": "clone",
            "model_root": str(PATHS.models / engine_id),
            "output_path": str(output),
            "text": "Cette voix est prête pour un doublage naturel.",
            "language": "fr",
            "sample": {
                "path": str(reference),
                "reference_text": transcription["text"],
                "prompt_cache_path": str(test_root / "voice-prompt.pt"),
            },
        }
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.update(
            {
                "DUBROOM_DEVICE": "cuda",
                "HF_HOME": str(PATHS.cache / "huggingface"),
                "TORCH_HOME": str(PATHS.cache / "torch"),
            }
        )
        with resource_scheduler.model_slot(
            "Qwen clone after Whisper test",
            device="cuda",
        ):
            result = subprocess.run(
                [
                    str(python_executable),
                    str(worker),
                    "--request",
                    str(request_path),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=360,
                check=False,
            )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout)[-3000:])
        assert output.is_file() and output.stat().st_size > 10_000
        with wave.open(str(output), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
        assert 1.0 <= duration <= 15.0, duration
        print(
            json.dumps(
                {
                    "ok": True,
                    "sequence": [
                        {
                            "model": transcription["engine_name"],
                            "device": transcription["device"],
                            "text": transcription["text"],
                        },
                        {
                            "model": engine_id,
                            "device": "cuda",
                            "duration_seconds": round(duration, 3),
                        },
                    ],
                    "workers_are_isolated": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
