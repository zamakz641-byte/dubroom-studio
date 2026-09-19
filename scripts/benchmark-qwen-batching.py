from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app import local_voice_service, native_tts_service
from services.api.app.config import PATHS


PROFILE_ID = "local-d385d7af180d4fc8b24471a4fcfb20b8"
ENGINE_ID = "tts-qwen3-1.7b-base"
TEXTS = [
    "La nuit semblait paisible, mais quelque chose attendait derrière les remparts.",
    "Lorsque la cloche sonna, chacun comprit que la bataille avait commencé.",
    "Il releva lentement les yeux et répondit avec un calme presque inquiétant.",
    "Personne ne savait encore que cette décision allait bouleverser tout le royaume.",
]


def gpu_memory_mib() -> int:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        return max(int(line.strip()) for line in result.stdout.splitlines() if line.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def run_size(root: Path, batch_size: int, profile: dict) -> dict:
    output_root = root / f"batch-{batch_size}"
    output_root.mkdir(parents=True, exist_ok=True)
    request_path = output_root / "request.json"
    sample = {
        "path": str(profile["design_reference_path"]),
        "reference_text": str(profile["design_reference_text"]),
        "prompt_cache_path": str(profile["design_prompt_cache_path"]),
    }
    request = {
        "family": "qwen3",
        "variant": "clone",
        "model_root": str(PATHS.models / ENGINE_ID),
        "output_path": str(output_root / "unused.wav"),
        "micro_batch_size": batch_size,
        "items": [
            {
                "id": f"line-{index + 1}",
                "text": text,
                "language": "fr",
                "output_path": str(output_root / f"line-{index + 1}.wav"),
                "sample": sample,
                "seed": 42,
            }
            for index, text in enumerate(TEXTS)
        ],
    }
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "DUBROOM_DEVICE": "cuda",
            "DUBROOM_QWEN_BATCH_SIZE": str(batch_size),
            "HF_HOME": str(PATHS.cache / "huggingface"),
            "TORCH_HOME": str(PATHS.cache / "torch"),
        }
    )
    command = [
        str(native_tts_service._runtime_python(ENGINE_ID)),
        str(PATHS.installers / "run-tts.py"),
        "--request",
        str(request_path),
    ]
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    peak_memory = 0
    while process.poll() is None:
        peak_memory = max(peak_memory, gpu_memory_mib())
        time.sleep(0.2)
    stdout, _ = process.communicate()
    elapsed = time.perf_counter() - started
    events: list[dict] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    completed = [
        event
        for event in events
        if event.get("event") == "item_completed"
        and event.get("status") == "completed"
    ]
    fallbacks = [
        event for event in events if event.get("event") == "micro_batch_fallback"
    ]
    audio_seconds = sum(float(event.get("duration") or 0) for event in completed)
    return {
        "batch_size": batch_size,
        "return_code": process.returncode,
        "completed": len(completed),
        "elapsed_seconds": round(elapsed, 3),
        "audio_seconds": round(audio_seconds, 3),
        "real_time_factor": (
            round(elapsed / audio_seconds, 3) if audio_seconds > 0 else None
        ),
        "lines_per_minute": round(len(completed) * 60 / elapsed, 2),
        "peak_gpu_memory_mib": peak_memory,
        "fallback_count": len(fallbacks),
        "error_tail": (
            "\n".join(stdout.splitlines()[-20:])
            if process.returncode or len(completed) != len(TEXTS)
            else ""
        ),
    }


def main() -> None:
    profile = local_voice_service.get(PROFILE_ID)
    if not profile or profile.get("design_status") != "ready":
        raise RuntimeError("The benchmark requires the prepared Ben VoiceDesign profile")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_root = PATHS.data / "test-runs" / f"qwen-batching-{stamp}"
    output_root.mkdir(parents=True, exist_ok=False)
    results = [run_size(output_root, size, profile) for size in (1, 2, 3)]
    valid = [
        item
        for item in results
        if item["return_code"] == 0 and item["completed"] == len(TEXTS)
    ]
    if not valid:
        raise RuntimeError(json.dumps(results, ensure_ascii=False, indent=2))
    best = min(valid, key=lambda item: item["elapsed_seconds"])
    report = {
        "ok": True,
        "engine_id": ENGINE_ID,
        "profile_id": PROFILE_ID,
        "line_count": len(TEXTS),
        "output_root": str(output_root),
        "results": results,
        "recommended_batch_size": best["batch_size"],
    }
    (output_root / "benchmark.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
