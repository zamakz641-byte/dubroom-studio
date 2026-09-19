from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.request
import urllib.error
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORT = 18767
REFERENCE_TEXT = (
    "Ce type est couvert de runes maudites et de cicatrices, et son équipe le "
    "traite comme un déchet."
)
TEXT = "La nuit semblait calme, mais personne n'osait détourner le regard."


def _wait_ready(process: subprocess.Popen[str]) -> float:
    started = time.perf_counter()
    for _ in range(240):
        if process.poll() is not None:
            raise RuntimeError("CosyVoice server exited before becoming ready")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/v1/voices", timeout=1
            ) as response:
                if response.status == 200:
                    return time.perf_counter() - started
        except Exception:
            time.sleep(0.25)
    raise TimeoutError("CosyVoice server did not become ready")


def _request(index: int, run_dir: Path) -> dict[str, float | str]:
    payload = json.dumps(
        {
            "input": TEXT,
            "voice": "test.wav",
            "ref_text": REFERENCE_TEXT,
            "consent_attestation": "Authorized local DubRoom voice profile",
            "spoken_disclaimer": False,
            "marking_attestation": "DubRoom test output is visibly identified as AI-generated and retains embedded provenance",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/audio/speech",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=360) as response:
            audio = response.read()
    except urllib.error.HTTPError as error:
        raise RuntimeError(error.read().decode("utf-8", "replace")) from error
    elapsed = time.perf_counter() - started
    output = run_dir / f"warm-{index}.wav"
    output.write_bytes(audio)
    with wave.open(str(output), "rb") as source:
        duration = source.getnframes() / source.getframerate()
    return {
        "wall_seconds": round(elapsed, 3),
        "audio_seconds": round(duration, 3),
        "rtf": round(elapsed / max(duration, 0.001), 3),
        "output": str(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--flow-steps", type=int, default=5)
    args = parser.parse_args()
    run_dir = ROOT / "data" / "test-runs" / "cosyvoice3-gguf" / f"server-{args.device}-flow{args.flow_steps}"
    voice_dir = run_dir / "voices"
    run_dir.mkdir(parents=True, exist_ok=True)
    voice_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        ROOT / "data" / "test-runs" / "voice-cleanup" / "optimized-balanced.wav",
        voice_dir / "test.wav",
    )
    (voice_dir / "test.txt").write_text(REFERENCE_TEXT, encoding="utf-8")
    runtime_root = ROOT / "data" / "runtimes" / (
        "crispasr-cuda-v0.8.25" if args.device == "cuda" else "crispasr-vulkan"
    )
    executable = next(runtime_root.rglob("crispasr.exe"))
    model_dir = ROOT / "models" / "tts-cosyvoice3-gguf"
    environment = os.environ.copy()
    environment.update(
        {
            "CRISPASR_COSYVOICE3_CAMPPLUS_PATH": str(model_dir / "cosyvoice3-campplus-f16.gguf"),
            "CRISPASR_COSYVOICE3_S3TOK_PATH": str(model_dir / "cosyvoice3-s3tok-q4_k.gguf"),
            "CRISPASR_COSYVOICE3_HIFT_PATH": str(model_dir / "cosyvoice3-hift-f16.gguf"),
            "CRISPASR_COSYVOICE3_VOICES_PATH": str(model_dir / "cosyvoice3-voices.gguf"),
            "CRISPASR_COSYVOICE3_FLOW_STEPS": str(args.flow_steps),
            "COSYVOICE3_FLOW_STEPS": str(args.flow_steps),
        }
    )
    command = [
        str(executable),
        "--server",
        "--backend",
        "cosyvoice3-tts",
        "-m",
        str(model_dir / "cosyvoice3-llm-q4_k.gguf"),
        "--voice-dir",
        str(voice_dir),
        "--port",
        str(PORT),
        "--i-have-rights",
        "--tts-steps",
        str(args.flow_steps),
    ]
    if args.device == "cpu":
        command.append("--no-gpu")
    else:
        command.extend(["--gpu-backend", "cuda", "--device", "0", "--verbose"])
    log_path = run_dir / "server.log"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            # CosyVoice3 v0.8.25 does not yet resolve a bare WAV name through
            # --voice-dir, so run beside the authorized reference file.
            cwd=voice_dir,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            load_seconds = _wait_ready(process)
            requests = [_request(1, run_dir), _request(2, run_dir)]
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
    print(
        json.dumps(
            {
                "server_load_seconds": round(load_seconds, 3),
                "device": args.device,
                "flow_steps": args.flow_steps,
                "requests": requests,
                "log": str(log_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
