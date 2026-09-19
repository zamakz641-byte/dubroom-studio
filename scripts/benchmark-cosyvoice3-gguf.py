from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True)
    parser.add_argument("--reference-text", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", choices=("cpu", "cuda", "vulkan"), default="cpu")
    parser.add_argument("--flow-steps", type=int, choices=(5, 10), default=10)
    args = parser.parse_args()

    runtime_root = (
        ROOT / "data" / "runtimes" / "crispasr-cuda-v0.8.25"
        if args.device == "cuda"
        else ROOT / "data" / "runtimes" / "crispasr-vulkan"
    )
    executable = next(runtime_root.rglob("crispasr.exe"))
    model = ROOT / "models" / "tts-cosyvoice3-gguf" / "cosyvoice3-llm-q4_k.gguf"
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(executable),
        "--backend",
        "cosyvoice3-tts",
        "-m",
        str(model),
        "--voice",
        str(Path(args.reference).resolve()),
        "--ref-text",
        args.reference_text,
        "--i-have-rights",
        "--tts",
        args.text,
        "--tts-output",
        str(output),
        "--tts-steps",
        str(args.flow_steps),
    ]
    environment = os.environ.copy()
    model_dir = model.parent
    environment["CRISPASR_COSYVOICE3_CAMPPLUS_PATH"] = str(
        model_dir / "cosyvoice3-campplus-f16.gguf"
    )
    environment["CRISPASR_COSYVOICE3_S3TOK_PATH"] = str(
        model_dir / "cosyvoice3-s3tok-q4_k.gguf"
    )
    environment["CRISPASR_COSYVOICE3_HIFT_PATH"] = str(
        model_dir / "cosyvoice3-hift-f16.gguf"
    )
    environment["CRISPASR_COSYVOICE3_VOICES_PATH"] = str(
        model_dir / "cosyvoice3-voices.gguf"
    )
    environment["CRISPASR_COSYVOICE3_FLOW_STEPS"] = str(args.flow_steps)
    # v0.8.25 still reads the legacy spelling for this particular option.
    environment["COSYVOICE3_FLOW_STEPS"] = str(args.flow_steps)
    if args.device == "cpu":
        command.append("--no-gpu")
    elif args.device == "vulkan":
        command.extend(["--gpu-backend", "vulkan", "--device", "1"])
        environment["CRISPASR_COSYVOICE3_VULKAN_NATIVE"] = "1"
    else:
        command.extend(["--gpu-backend", "cuda", "--device", "0", "--verbose"])

    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=360,
        check=False,
    )
    elapsed = time.perf_counter() - started
    log_path = output.with_suffix(".log")
    log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit((result.stderr or result.stdout)[-3000:])
    with wave.open(str(output), "rb") as audio:
        duration = audio.getnframes() / audio.getframerate()
        sample_rate = audio.getframerate()
    print(
        json.dumps(
            {
                "device": args.device,
                "flow_steps": args.flow_steps,
                "wall_seconds": round(elapsed, 3),
                "audio_seconds": round(duration, 3),
                "rtf": round(elapsed / max(duration, 0.001), 3),
                "sample_rate": sample_rate,
                "output": str(output),
                "log": str(log_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
