from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app import native_tts_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and time one DubRoom TTS sample")
    parser.add_argument("--engine", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    started = time.perf_counter()
    record = native_tts_service.generate(
        {
            "engine_id": args.engine,
            "profile_id": args.profile,
            "language": args.language,
            "text": args.text,
            "seed": 42,
            "normalize": True,
        }
    )
    deadline = time.monotonic() + args.timeout
    while record.get("status") not in {"completed", "failed"}:
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Generation timed out: {record['id']}")
        time.sleep(0.5)
        record = native_tts_service.generation(str(record["id"]))
    elapsed = time.perf_counter() - started
    result = {
        "id": record.get("id"),
        "status": record.get("status"),
        "engine_id": record.get("engine_id"),
        "device": record.get("device"),
        "elapsed_seconds": round(elapsed, 3),
        "audio_seconds": record.get("duration"),
        "realtime_multiple": (
            round(float(record["duration"]) / elapsed, 3)
            if record.get("duration") and elapsed
            else None
        ),
        "audio_path": record.get("audio_path"),
        "error": record.get("error"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if record.get("status") != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
