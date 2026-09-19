from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import subprocess
import time
import urllib.request
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "data" / "test-runs" / "cosyvoice3-gguf" / "parallel-cuda"
VOICE_DIR = RUN_DIR / "voices"
PORTS = (18771, 18772)
REFERENCE_TEXT = "Ce type est couvert de runes maudites et de cicatrices, et son équipe le traite comme un déchet."
TEXTS = (
    "La nuit semblait calme, mais personne n'osait détourner le regard.",
    "Tout à coup, une voix froide résonna derrière eux.",
    "Le héros serra les poings avant de franchir la porte.",
    "Personne ne savait encore ce qui les attendait au sommet.",
)


def wait_ready(process: subprocess.Popen[str], port: int) -> float:
    started = time.perf_counter()
    for _ in range(240):
        if process.poll() is not None:
            raise RuntimeError(f"CosyVoice replica on {port} exited")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                if response.status == 200:
                    return time.perf_counter() - started
        except Exception:
            time.sleep(0.25)
    raise TimeoutError(f"CosyVoice replica on {port} timed out")


def synthesize(index: int, port: int) -> dict[str, float | str]:
    payload = json.dumps({
        "input": TEXTS[index],
        "voice": "test.wav",
        "ref_text": REFERENCE_TEXT,
        "consent_attestation": "Authorized local DubRoom voice profile",
        "response_format": "wav",
    }).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/audio/speech",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=360) as response:
        audio = response.read()
    elapsed = time.perf_counter() - started
    output = RUN_DIR / f"line-{index + 1}.wav"
    output.write_bytes(audio)
    with wave.open(str(output), "rb") as source:
        duration = source.getnframes() / source.getframerate()
    return {"wall_seconds": round(elapsed, 3), "audio_seconds": round(duration, 3), "output": str(output)}


def main() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "data/test-runs/voice-cleanup/optimized-balanced.wav", VOICE_DIR / "test.wav")
    (VOICE_DIR / "test.txt").write_text(REFERENCE_TEXT, encoding="utf-8")
    executable = next((ROOT / "data/runtimes/crispasr-cuda-v0.8.25").rglob("crispasr.exe"))
    model_dir = ROOT / "models/tts-cosyvoice3-gguf"
    environment = os.environ.copy()
    environment.update({
        "CRISPASR_COSYVOICE3_CAMPPLUS_PATH": str(model_dir / "cosyvoice3-campplus-f16.gguf"),
        "CRISPASR_COSYVOICE3_S3TOK_PATH": str(model_dir / "cosyvoice3-s3tok-q4_k.gguf"),
        "CRISPASR_COSYVOICE3_HIFT_PATH": str(model_dir / "cosyvoice3-hift-f16.gguf"),
        "CRISPASR_COSYVOICE3_VOICES_PATH": str(model_dir / "cosyvoice3-voices.gguf"),
        "CRISPASR_COSYVOICE3_FLOW_STEPS": "5",
        "CUDA_VISIBLE_DEVICES": "0",
    })
    processes: list[subprocess.Popen[str]] = []
    logs = []
    try:
        for replica, port in enumerate(PORTS, start=1):
            log = (RUN_DIR / f"server-{replica}.log").open("w", encoding="utf-8")
            logs.append(log)
            process = subprocess.Popen([
                str(executable), "--server", "--backend", "cosyvoice3-tts",
                "-m", str(model_dir / "cosyvoice3-llm-q4_k.gguf"),
                "--voice-dir", str(VOICE_DIR), "--port", str(port),
                "--i-have-rights", "--gpu-backend", "cuda", "--device", "0",
            ], cwd=VOICE_DIR, env=environment, stdout=log, stderr=subprocess.STDOUT, text=True)
            processes.append(process)
        loads = [wait_ready(process, port) for process, port in zip(processes, PORTS)]
        started = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(synthesize, index, PORTS[index % 2]) for index in range(len(TEXTS))]
            results = [future.result() for future in futures]
        wall = time.perf_counter() - started
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for log in logs:
            log.close()
    audio_seconds = sum(float(item["audio_seconds"]) for item in results)
    print(json.dumps({
        "replicas": 2,
        "load_seconds": [round(value, 3) for value in loads],
        "wall_seconds": round(wall, 3),
        "audio_seconds": round(audio_seconds, 3),
        "aggregate_rtf": round(wall / audio_seconds, 3),
        "results": results,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
