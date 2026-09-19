from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import engine_service, resource_scheduler
from .config import PATHS


WORKER_PATH = PATHS.installers / "run-asr.py"
TRANSCRIPT_ROOT = PATHS.temp / "voice-reference-transcripts"


def _ready_whisper_engine() -> dict[str, Any]:
    candidates = [
        engine
        for engine in engine_service.list_engines()
        if str(engine.get("id") or "").startswith("faster-whisper-")
        and "-raw" not in str(engine.get("id") or "")
        and "-onnx" not in str(engine.get("id") or "")
        and (engine.get("installation") or {}).get("status") == "ready"
    ]
    if not candidates:
        raise RuntimeError(
            "No ready Faster Whisper model can transcribe this voice reference. "
            "Enter the exact text manually or repair Whisper from Engines."
        )
    candidates.sort(
        key=lambda engine: (
            int((engine.get("model") or {}).get("quality_rank") or 0),
            int((engine.get("model") or {}).get("speed_rank") or 0),
        ),
        reverse=True,
    )
    return candidates[0]


def transcribe_reference(
    file_path: str,
    *,
    language: str | None = None,
) -> dict[str, Any]:
    source = Path(file_path).expanduser().resolve()
    if not source.is_file():
        raise ValueError("profile.sample_missing")
    engine = _ready_whisper_engine()
    engine_id = str(engine["id"])
    manifest = PATHS.models / engine_id / "model.json"
    python_executable = (
        PATHS.environments / engine_id / "venv" / "Scripts" / "python.exe"
    )
    if not manifest.is_file() or not python_executable.is_file() or not WORKER_PATH.is_file():
        raise RuntimeError(
            f"{engine.get('display_name') or engine_id} is incomplete. "
            "Use Repair from Engines."
        )

    TRANSCRIPT_ROOT.mkdir(parents=True, exist_ok=True)
    request_id = uuid4().hex
    output_path = TRANSCRIPT_ROOT / f"{request_id}.json"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    devices = ["cuda", "cpu"] if shutil.which("nvidia-smi") else ["cpu"]
    last_error = ""
    try:
        for device in devices:
            output_path.unlink(missing_ok=True)
            command = [
                str(python_executable),
                str(WORKER_PATH),
                "--manifest",
                str(manifest),
                "--audio",
                str(source),
                "--output",
                str(output_path),
                "--device",
                device,
            ]
            normalized_language = str(language or "").lower().split("-", 1)[0].strip()
            if normalized_language and normalized_language != "auto":
                command.extend(["--language", normalized_language])
            environment = os.environ.copy()
            environment.update(
                {
                    "HF_HOME": str(PATHS.cache / "huggingface"),
                    "TORCH_HOME": str(PATHS.cache / "torch"),
                    "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
                }
            )
            try:
                # Qwen and Whisper both use the single GPU slot. Their workers
                # are isolated subprocesses, so exiting a worker releases all
                # model weights before the next model is allowed to start.
                with resource_scheduler.model_slot(
                    "Whisper voice-reference transcription",
                    device=device,
                ):
                    result = subprocess.run(
                        command,
                        cwd=PATHS.workspace,
                        env=environment,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=300,
                        creationflags=flags,
                        check=False,
                    )
            except subprocess.TimeoutExpired:
                last_error = f"{engine.get('display_name') or engine_id} timed out"
                continue
            if result.returncode == 0 and output_path.is_file():
                payload = json.loads(output_path.read_text(encoding="utf-8"))
                segments = [
                    segment
                    for segment in (payload.get("segments") or [])
                    if isinstance(segment, dict)
                    and str(segment.get("text") or "").strip()
                ]
                text = " ".join(
                    str(segment.get("text") or "").strip()
                    for segment in segments
                ).strip()
                if not text:
                    raise ValueError(
                        "Whisper did not detect speech in this reference. "
                        "Use a cleaner recording or enter the text manually."
                    )
                return {
                    "text": text,
                    "language": payload.get("language") or normalized_language or None,
                    "engine_id": engine_id,
                    "engine_name": engine.get("display_name") or engine_id,
                    "device": payload.get("device") or device,
                    "compute_type": payload.get("compute_type"),
                    "segment_count": len(segments),
                    # Word timestamps let the cleanup stage select one short,
                    # complete and exactly transcribed take for zero-shot TTS.
                    "segments": segments,
                }
            last_error = (
                result.stderr
                or result.stdout
                or f"worker exited with code {result.returncode}"
            ).strip()
        raise RuntimeError(
            f"Automatic reference transcription failed: {last_error[-1200:]}"
        )
    finally:
        output_path.unlink(missing_ok=True)
