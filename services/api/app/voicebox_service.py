from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import PATHS, VOICEBOX_DATA, VOICEBOX_HOST, VOICEBOX_MODELS, VOICEBOX_PORT, VOICEBOX_SOURCE


BASE_URL = f"http://{VOICEBOX_HOST}:{VOICEBOX_PORT}"
CATALOG_PATH = PATHS.workspace / "models" / "voicebox-catalog.json"
BRAND_CATALOG_PATH = PATHS.workspace / "models" / "brand-catalog.json"
_process: subprocess.Popen[Any] | None = None
_lock = threading.Lock()


def _request(path: str, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 5) -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=body, method=method,
        headers={"Content-Type": "application/json", "X-Voicebox-Client-Id": "dubroom"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read()
            return json.loads(content.decode("utf-8")) if content else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Voicebox HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Voicebox is unavailable at {BASE_URL}: {exc.reason}") from exc


def is_online() -> bool:
    try:
        _request("/health", timeout=1.2)
        return True
    except RuntimeError:
        return False


def status() -> dict[str, Any]:
    python_executable = VOICEBOX_SOURCE / "backend" / "venv" / "Scripts" / "python.exe"
    ready_manifest = PATHS.environments / "voicebox-runtime" / "ready.json"
    return {
        "online": is_online(),
        "base_url": BASE_URL,
        "source": str(VOICEBOX_SOURCE),
        "source_ready": (VOICEBOX_SOURCE / ".git").exists(),
        "runtime_ready": python_executable.exists() and ready_manifest.exists(),
        "data": str(VOICEBOX_DATA),
        "models": str(VOICEBOX_MODELS),
        "pid": _process.pid if _process and _process.poll() is None else None,
    }


def start() -> dict[str, Any]:
    global _process
    with _lock:
        if is_online():
            return status()
        python_executable = VOICEBOX_SOURCE / "backend" / "venv" / "Scripts" / "python.exe"
        ready_manifest = PATHS.environments / "voicebox-runtime" / "ready.json"
        if not python_executable.exists() or not ready_manifest.exists():
            raise RuntimeError("Voicebox runtime is not prepared. Install Voicebox Runtime from Engines first.")
        env = os.environ.copy()
        env.update({"VOICEBOX_DATA_DIR": str(VOICEBOX_DATA), "VOICEBOX_MODELS_DIR": str(VOICEBOX_MODELS)})
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        _process = subprocess.Popen(
            [str(python_executable), "-m", "backend.main", "--host", VOICEBOX_HOST, "--port", str(VOICEBOX_PORT), "--data-dir", str(VOICEBOX_DATA)],
            cwd=VOICEBOX_SOURCE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
        )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if is_online():
            break
        if _process and _process.poll() is not None:
            raise RuntimeError(f"Voicebox exited during startup with code {_process.returncode}")
        time.sleep(0.4)
    return status()


def models() -> dict[str, Any]:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8")) if CATALOG_PATH.exists() else {"models": []}
    brand_catalog = json.loads(BRAND_CATALOG_PATH.read_text(encoding="utf-8")) if BRAND_CATALOG_PATH.exists() else {"brands": {}}
    brands = brand_catalog.get("brands", {})
    brand_by_engine = {
        "qwen": "qwen",
        "qwen_custom_voice": "qwen",
        "chatterbox": "chatterbox",
        "chatterbox_turbo": "chatterbox",
        "tada": "tada",
        "kokoro": "kokoro",
        "luxtts": "luxtts",
    }
    catalog_models = catalog.get("models", [])
    live_by_name: dict[str, dict[str, Any]] = {}
    if is_online():
        result = _request("/models/status")
        live_by_name = {item.get("model_name", ""): item for item in result.get("models", [])}
    merged = []
    for definition in catalog_models:
        live = live_by_name.get(definition.get("model_name"), {})
        brand_id = brand_by_engine.get(str(definition.get("engine", "")))
        merged.append({
            **definition,
            **live,
            "brand": brands.get(brand_id) if brand_id else None,
            "downloaded": bool(live.get("downloaded", False)),
            "downloading": bool(live.get("downloading", False)),
            "loaded": bool(live.get("loaded", False)),
        })
    return {"models": merged}


def download_model(model_name: str) -> dict[str, Any]:
    return _request("/models/download", "POST", {"model_name": model_name}, timeout=15)


def cancel_model_download(model_name: str) -> dict[str, Any]:
    return _request("/models/download/cancel", "POST", {"model_name": model_name})


def unload_model(model_name: str) -> dict[str, Any]:
    return _request(f"/models/{urllib.parse.quote(model_name, safe='')}/unload", "POST")


def profiles() -> list[dict[str, Any]]:
    result = _request("/profiles")
    return result if isinstance(result, list) else []


def create_profile(payload: dict[str, Any]) -> dict[str, Any]:
    return _request("/profiles", "POST", payload, timeout=15)


def preset_voices(engine: str) -> dict[str, Any]:
    return _request(f"/profiles/presets/{urllib.parse.quote(engine, safe='')}")


def add_profile_sample(profile_id: str, file_path: str, reference_text: str) -> dict[str, Any]:
    source = Path(file_path).resolve()
    if not source.is_file():
        raise RuntimeError("The selected voice sample does not exist")
    if source.stat().st_size > 50 * 1024 * 1024:
        raise RuntimeError("The voice sample exceeds Voicebox's 50 MB limit")
    boundary = f"----Dubroom{uuid4().hex}"
    mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"reference_text\"\r\n\r\n{reference_text}\r\n".encode("utf-8"),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{source.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode("utf-8"),
        source.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ])
    request = urllib.request.Request(
        f"{BASE_URL}/profiles/{urllib.parse.quote(profile_id, safe='')}/samples",
        data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "X-Voicebox-Client-Id": "dubroom"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Voicebox HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Voicebox sample upload failed: {exc.reason}") from exc


def generate(payload: dict[str, Any]) -> dict[str, Any]:
    return _request("/generate", "POST", payload, timeout=30)


def generation_status(generation_id: str) -> dict[str, Any]:
    return _request(f"/generate/{urllib.parse.quote(generation_id, safe='')}/status", timeout=30)


def generation(generation_id: str) -> dict[str, Any]:
    """Return a finite history snapshot; Voicebox's status route is an SSE stream."""
    return _request(f"/history/{urllib.parse.quote(generation_id, safe='')}", timeout=10)


def resolve_audio_path(storage_path: str | None) -> Path | None:
    if not storage_path:
        return None
    candidate = Path(storage_path)
    if not candidate.is_absolute():
        candidate = VOICEBOX_DATA / candidate
    resolved = candidate.resolve()
    data_root = VOICEBOX_DATA.resolve()
    if resolved != data_root and data_root not in resolved.parents:
        raise RuntimeError("Voicebox returned an audio path outside its configured data directory")
    return resolved
