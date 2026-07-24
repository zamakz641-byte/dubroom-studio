from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import PATHS


RUNTIME_ROOT = PATHS.environments / "rvc-runtime"
SOURCE_ROOT = RUNTIME_ROOT / "source"
PYTHON_EXE = RUNTIME_ROOT / "venv" / "Scripts" / "python.exe"
READY_PATH = RUNTIME_ROOT / "ready.json"
MODEL_ROOT = PATHS.models / "rvc"
STATE_ROOT = PATHS.data / "rvc" / "jobs"
OUTPUT_ROOT = PATHS.data / "rvc" / "outputs"
WORKER = PATHS.installers / "run-rvc.py"
_processes: dict[str, subprocess.Popen[str]] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def status() -> dict[str, Any]:
    runtime_ready = PYTHON_EXE.is_file() and READY_PATH.is_file() and (SOURCE_ROOT / "infer" / "modules" / "vc" / "modules.py").is_file()
    core_candidates = [
        SOURCE_ROOT / "assets" / "hubert" / "hubert_base.pt",
        SOURCE_ROOT / "assets" / "rmvpe" / "rmvpe.pt",
    ]
    return {
        "runtime_ready": runtime_ready,
        "core_assets_ready": all(path.is_file() for path in core_candidates),
        "runtime_root": str(RUNTIME_ROOT),
        "models_root": str(MODEL_ROOT),
        "model_count": len(models()),
        "worker_ready": WORKER.is_file(),
    }


def models() -> list[dict[str, Any]]:
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    result: list[dict[str, Any]] = []
    for model_path in sorted(MODEL_ROOT.glob("*.pth")):
        model_id = model_path.stem
        metadata_path = MODEL_ROOT / f"{model_id}.json"
        metadata: dict[str, Any] = {}
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                metadata = {}
        index_path = next(iter(sorted(MODEL_ROOT.glob(f"{model_id}*.index"))), None)
        result.append({
            "id": model_id,
            "name": metadata.get("name") or model_id.replace("_", " ").title(),
            "model_path": str(model_path),
            "index_path": str(index_path) if index_path else None,
            "size_bytes": model_path.stat().st_size,
            "author": metadata.get("author"),
            "language": metadata.get("language"),
            "license": metadata.get("license"),
            "authorized": bool(metadata.get("authorized", False)),
            "created_at": metadata.get("created_at"),
        })
    return result


def import_model(model_path: str, index_path: str | None, name: str, author: str | None, license_name: str | None, authorized: bool) -> dict[str, Any]:
    source = Path(model_path).resolve()
    if not source.is_file() or source.suffix.lower() != ".pth":
        raise RuntimeError("Select a valid RVC .pth model")
    if not authorized:
        raise RuntimeError("Confirm that you are authorized to use this voice model")
    model_id = re.sub(r"[^a-z0-9-]+", "-", (name or source.stem).lower()).strip("-") or uuid4().hex[:10]
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    destination = MODEL_ROOT / f"{model_id}.pth"
    shutil.copy2(source, destination)
    imported_index: Path | None = None
    if index_path:
        source_index = Path(index_path).resolve()
        if source_index.is_file() and source_index.suffix.lower() == ".index":
            imported_index = MODEL_ROOT / f"{model_id}.index"
            shutil.copy2(source_index, imported_index)
    metadata = {
        "id": model_id,
        "name": name or source.stem,
        "author": author,
        "license": license_name,
        "authorized": True,
        "source_file": str(source),
        "created_at": _now(),
    }
    (MODEL_ROOT / f"{model_id}.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return next(item for item in models() if item["id"] == model_id)


def start(source_path: str, model_id: str, pitch: int = 0, f0_method: str = "rmvpe", index_rate: float = 0.75, protect: float = 0.33) -> dict[str, Any]:
    runtime = status()
    if not runtime["runtime_ready"]:
        raise RuntimeError("Install and validate RVC Runtime first")
    source = Path(source_path).resolve()
    if not source.is_file():
        raise RuntimeError("The source audio file does not exist")
    model = next((item for item in models() if item["id"] == model_id), None)
    if not model:
        raise RuntimeError("RVC model not found")
    job_id = uuid4().hex
    output = OUTPUT_ROOT / f"{job_id}.wav"
    state = {
        "id": job_id, "status": "queued", "progress": 0, "message": "RVC conversion queued",
        "source_path": str(source), "model_id": model_id, "output_path": str(output),
        "pitch": pitch, "f0_method": f0_method, "index_rate": index_rate, "protect": protect,
        "error": None, "created_at": _now(), "updated_at": _now(),
    }
    _write(job_id, state)
    return state


def run(job_id: str) -> None:
    state = get(job_id)
    model = next(item for item in models() if item["id"] == state["model_id"])
    output = Path(state["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(PYTHON_EXE), str(WORKER), "--runtime", str(SOURCE_ROOT), "--model", model["model_path"],
        "--input", state["source_path"], "--output", str(output), "--pitch", str(state["pitch"]),
        "--f0-method", state["f0_method"], "--index-rate", str(state["index_rate"]), "--protect", str(state["protect"]),
    ]
    if model.get("index_path"):
        command.extend(["--index", model["index_path"]])
    _patch(job_id, status="running", progress=12, message="Loading the RVC model")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(command, cwd=PATHS.workspace, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=flags)
    with _lock:
        _processes[job_id] = process
    lines: list[str] = []
    try:
        _patch(job_id, progress=45, message="Converting the voice timbre")
        assert process.stdout is not None
        for line in process.stdout:
            lines = (lines + [line.strip()])[-20:]
        code = process.wait()
        current = get(job_id)
        if current["status"] == "cancelled":
            return
        if code != 0 or not output.is_file():
            raise RuntimeError("\n".join(lines)[-1400:] or f"RVC exited with code {code}")
        _patch(job_id, status="completed", progress=100, message="RVC take ready", output_path=str(output.resolve()))
    except Exception as exc:
        if get(job_id)["status"] != "cancelled":
            _patch(job_id, status="failed", progress=0, message="RVC conversion failed", error=str(exc))
    finally:
        with _lock:
            _processes.pop(job_id, None)


def cancel(job_id: str) -> dict[str, Any]:
    get(job_id)
    with _lock:
        process = _processes.get(job_id)
    if process and process.poll() is None:
        process.terminate()
    _patch(job_id, status="cancelled", message="RVC conversion cancelled", error=None)
    return get(job_id)


def get(job_id: str) -> dict[str, Any]:
    path = STATE_ROOT / f"{job_id}.json"
    if not path.is_file():
        raise KeyError(job_id)
    return json.loads(path.read_text(encoding="utf-8"))


def _write(job_id: str, value: dict[str, Any]) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    (STATE_ROOT / f"{job_id}.json").write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _patch(job_id: str, **patch: Any) -> None:
    value = get(job_id)
    value.update(patch)
    value["updated_at"] = _now()
    _write(job_id, value)
