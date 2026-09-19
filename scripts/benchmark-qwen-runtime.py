from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "scripts" / "engines" / "run-tts.py"
GENERATIONS = ROOT / "data" / "tts" / "generations"
OUTPUT_ROOT = ROOT / "data" / "test-runs"


def runtime_python(engine_id: str) -> Path:
    """Resolve the compatibility runtime instead of assuming a model folder."""
    catalog = json.loads(
        (ROOT / "models" / "tts-catalog.json").read_text(encoding="utf-8")
    )
    model = next(
        (item for item in catalog.get("models", []) if item.get("id") == engine_id),
        None,
    )
    if model is None:
        raise RuntimeError(f"Unknown Qwen model: {engine_id}")
    runtime_id = str(model.get("runtime_engine_id") or "tts-qwen3-0.6b-base")
    candidate = (
        ROOT / "data" / "environments" / runtime_id / "venv" / "Scripts" / "python.exe"
    )
    if not candidate.is_file():
        raise RuntimeError(f"Qwen runtime is not installed: {candidate}")
    return candidate


def request_engine_id(request: dict[str, Any]) -> str:
    model_root = Path(str(request.get("model_root") or ""))
    if model_root.name.startswith("tts-qwen3-"):
        return model_root.name
    for item in request.get("items") or []:
        candidate = str(item.get("engine") or "")
        if candidate.startswith("tts-qwen3-"):
            return candidate
    return "tts-qwen3-0.6b-base"


def text_for_member(segment: dict[str, Any]) -> str:
    if segment.get("voiceSkip"):
        return ""
    for key in ("adaptedText", "translatedText", "sourceText"):
        value = str(segment.get(key) or "").strip()
        if value:
            return value
    return ""


def request_from_project(project: Path) -> dict[str, Any]:
    state_path = project / "analysis" / "state.json"
    manifest_path = project / "audio" / "voice_manifest.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    state_segments = {
        str(segment.get("id")): segment for segment in state.get("segments") or []
    }
    voice_segments = manifest.get("segments") or []
    profile_ids = {
        str(segment.get("profile_id") or "").strip()
        for segment in voice_segments
        if str(segment.get("profile_id") or "").strip()
    }
    if len(profile_ids) != 1:
        raise RuntimeError("The benchmark project must use one voice profile")
    profile_id = next(iter(profile_ids))
    profiles = json.loads(
        (ROOT / "data" / "voice-profiles" / "profiles.json").read_text(
            encoding="utf-8"
        )
    )
    profile = next(
        (item for item in profiles if str(item.get("id")) == profile_id),
        None,
    )
    if not profile or not profile.get("samples"):
        raise RuntimeError(f"Voice profile {profile_id} has no reference sample")
    sample = profile["samples"][0]
    prompt_dir = ROOT / "data" / "voice-profiles" / profile_id / "prompts"
    prompt_caches = sorted(prompt_dir.glob("qwen-*.pt"))
    engine_id = str(profile.get("default_engine") or "tts-qwen3-1.7b-base")
    items: list[dict[str, Any]] = []
    for voice_segment in voice_segments:
        member_ids = voice_segment.get("member_ids") or [
            voice_segment.get("segment_id")
        ]
        text = " ".join(
            value
            for member_id in member_ids
            if (value := text_for_member(state_segments.get(str(member_id), {})))
        ).strip()
        if not text:
            continue
        items.append(
            {
                "id": str(voice_segment.get("segment_id") or f"line-{len(items) + 1}"),
                "profile_id": profile_id,
                "text": text,
                "language": str(
                    voice_segment.get("language")
                    or state.get("target_language")
                    or profile.get("language")
                    or "fr"
                ),
                "target_duration": voice_segment.get("target_duration"),
                "max_chunk_chars": 800,
                "crossfade_ms": 50,
                "normalize": True,
                "engine": engine_id,
                "sample": {
                    "path": str(sample["path"]),
                    "reference_text": str(
                        sample.get("reference_text")
                        or sample.get("transcription", {}).get("text")
                        or ""
                    ),
                    "prompt_cache_path": (
                        str(prompt_caches[0]) if prompt_caches else None
                    ),
                },
                "seed": profile.get("design_seed", 42),
            }
        )
    if len(items) < 6:
        raise RuntimeError("The project needs at least six voiced lines")
    return {
        "family": "qwen3",
        "variant": "clone",
        "model_root": str(ROOT / "models" / engine_id),
        "output_path": str(project / "audio" / "benchmark-unused.wav"),
        "items": items,
    }


def gpu_memory_mib() -> int:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        return max(int(line.strip()) for line in result.stdout.splitlines() if line.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def latest_qwen_request() -> Path:
    candidates: list[Path] = []
    for path in GENERATIONS.glob("batch-*.request.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("family") == "qwen3" and payload.get("variant") == "clone":
            candidates.append(path)
    if not candidates:
        raise RuntimeError("No Qwen clone batch request is available")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def benchmark_request(
    source: dict[str, Any], root: Path, mode: str, line_count: int = 6
) -> dict[str, Any]:
    mode_root = root / mode
    mode_root.mkdir(parents=True, exist_ok=False)
    source_items = [item for item in source.get("items") or [] if str(item.get("text") or "").strip()]
    source_items.sort(key=lambda item: len(str(item.get("text") or "").split()))
    line_count = max(1, min(line_count, len(source_items)))
    if not source_items:
        raise RuntimeError("The source request has no voiced lines")
    if line_count == 1:
        spread = [source_items[0]]
    else:
        spread = [
            source_items[round(index * (len(source_items) - 1) / (line_count - 1))]
            for index in range(line_count)
        ]
    items = []
    for index, item in enumerate(spread, start=1):
        items.append(
            {
                **item,
                "id": f"{mode}-{index}",
                "output_path": str(mode_root / f"line-{index}.wav"),
                "clone_mode": "xvector" if mode.endswith("-xvector") else "icl",
                "non_streaming_mode": not (
                    mode.endswith("-streamtext") or mode.endswith("-xvector")
                ),
            }
        )
    request = {
        **{key: value for key, value in source.items() if key != "items"},
        "output_path": str(mode_root / "unused.wav"),
        "micro_batch_size": 2,
        "items": items,
    }
    request_path = mode_root / "request.json"
    request_path.write_text(
        json.dumps(request, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "DUBROOM_DEVICE": "cuda",
            "DUBROOM_QWEN_FAST": "1" if mode.startswith("cuda-graphs") else "0",
            "DUBROOM_QWEN_FAST_MAX_SEQ": "512",
            "DUBROOM_QWEN_BATCH_SIZE": "2",
            "HF_HOME": str(ROOT / "data" / "cache" / "huggingface"),
            "TORCH_HOME": str(ROOT / "data" / "cache" / "torch"),
        }
    )
    started = time.perf_counter()
    worker_log = mode_root / "worker.log"
    with worker_log.open("w", encoding="utf-8") as output_stream:
        process = subprocess.Popen(
            [
                str(runtime_python(request_engine_id(source))),
                str(WORKER),
                "--request",
                str(request_path),
            ],
            cwd=ROOT,
            env=environment,
            stdout=output_stream,
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
    stdout = worker_log.read_text(encoding="utf-8", errors="replace")
    elapsed = time.perf_counter() - started
    events: list[dict[str, Any]] = []
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
        if event.get("event") == "item_completed" and event.get("status") == "completed"
    ]
    audio_seconds = sum(float(event.get("duration") or 0) for event in completed)
    runtime_events = [
        event
        for event in events
        if event.get("event")
        in {"loading_fast_qwen", "fast_qwen_fallback", "micro_batch_config"}
    ]
    return {
        "mode": mode,
        "return_code": process.returncode,
        "completed": len(completed),
        "elapsed_seconds": round(elapsed, 3),
        "audio_seconds": round(audio_seconds, 3),
        "generation_seconds_per_audio_second": (
            round(elapsed / audio_seconds, 3) if audio_seconds else None
        ),
        "audio_realtime_multiple": (
            round(audio_seconds / elapsed, 3) if elapsed else None
        ),
        "lines_per_minute": round(len(completed) * 60 / elapsed, 2),
        "peak_gpu_memory_mib": peak_memory,
        "runtime_events": runtime_events,
        "error_tail": (
            "\n".join(stdout.splitlines()[-30:])
            if process.returncode or len(completed) != len(items)
            else ""
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--lines", type=int, default=6)
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=[
            "upstream",
            "cuda-graphs",
            "cuda-graphs-streamtext",
            "cuda-graphs-xvector",
        ],
        default=[
            "upstream",
            "cuda-graphs",
            "cuda-graphs-streamtext",
            "cuda-graphs-xvector",
        ],
    )
    args = parser.parse_args()
    if args.project:
        project_path = args.project.resolve()
        source = request_from_project(project_path)
        source_label = str(project_path)
    else:
        request_path = (args.request or latest_qwen_request()).resolve()
        source = json.loads(request_path.read_text(encoding="utf-8"))
        source_label = str(request_path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    root = OUTPUT_ROOT / f"qwen-runtime-{stamp}"
    root.mkdir(parents=True, exist_ok=False)
    (root / "source-request.json").write_text(
        json.dumps(source, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    line_count = max(1, args.lines)
    results = [
        benchmark_request(source, root, mode, line_count=line_count)
        for mode in args.modes
    ]
    upstream = next((item for item in results if item["mode"] == "upstream"), None)
    accelerated = next(
        (item for item in results if item["mode"] == "cuda-graphs"), None
    )
    speedup = None
    if upstream and accelerated and upstream["elapsed_seconds"] and accelerated["elapsed_seconds"]:
        speedup = round(
            upstream["elapsed_seconds"] / accelerated["elapsed_seconds"],
            3,
        )
    report = {
        "ok": all(
            item["return_code"] == 0 and item["completed"] == line_count
            for item in results
        ),
        "source_request": source_label,
        "output_root": str(root),
        "line_count": line_count,
        "results": results,
        "speedup": speedup,
    }
    (root / "benchmark.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
