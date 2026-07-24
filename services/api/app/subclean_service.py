from __future__ import annotations

import json
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import PATHS


RUNTIME_ROOT = PATHS.environments / "subclean-runtime"
SOURCE_ROOT = RUNTIME_ROOT / "source"
PYTHON_EXE = RUNTIME_ROOT / "venv" / "Scripts" / "python.exe"
READY_PATH = RUNTIME_ROOT / "ready.json"
CLI_PATH = SOURCE_ROOT / "backend" / "main.py"
STATE_ROOT = PATHS.data / "subclean" / "jobs"
OUTPUT_ROOT = PATHS.data / "subclean" / "outputs"
_processes: dict[str, subprocess.Popen[str]] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def status() -> dict[str, Any]:
    ready = PYTHON_EXE.is_file() and READY_PATH.is_file() and CLI_PATH.is_file()
    profile = None
    if READY_PATH.is_file():
        try:
            profile = json.loads(READY_PATH.read_text(encoding="utf-8-sig")).get("profile")
        except (json.JSONDecodeError, OSError):
            pass
    return {"runtime_ready": ready, "profile": profile, "runtime_root": str(RUNTIME_ROOT), "output_root": str(OUTPUT_ROOT)}


def start(source_path: str, mode: str = "sttn-auto", areas: list[list[int]] | None = None) -> dict[str, Any]:
    if not status()["runtime_ready"]:
        raise RuntimeError("Install and validate SubClean Runtime first")
    source = Path(source_path).resolve()
    if not source.is_file():
        raise RuntimeError("The source video does not exist")
    allowed_modes = {"sttn-auto", "sttn-det", "lama", "propainter", "opencv"}
    if mode not in allowed_modes:
        raise RuntimeError("Unsupported SubClean mode")
    normalized_areas: list[list[int]] = []
    for area in areas or []:
        if len(area) != 4 or any(int(value) < 0 for value in area):
            raise RuntimeError("Each subtitle area must contain ymin, ymax, xmin and xmax")
        normalized_areas.append([int(value) for value in area])
    job_id = uuid4().hex
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", source.stem)[:80]
    output = OUTPUT_ROOT / job_id / f"{safe_stem}-clean.mp4"
    state = {
        "id": job_id, "status": "queued", "progress": 0, "message": "SubClean analysis queued",
        "source_path": str(source), "output_path": str(output), "mode": mode, "areas": normalized_areas,
        "error": None, "created_at": _now(), "updated_at": _now(),
    }
    _write(job_id, state)
    return state


def run(job_id: str) -> None:
    state = get(job_id)
    output = Path(state["output_path"])
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [str(PYTHON_EXE), str(CLI_PATH), "-i", state["source_path"], "-o", str(output), "--inpaint-mode", state["mode"]]
    for area in state.get("areas", []):
        command.extend(["-c", *[str(value) for value in area]])
    _patch(job_id, status="running", progress=8, message="Detecting embedded subtitle regions")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(command, cwd=SOURCE_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=flags)
    with _lock:
        _processes[job_id] = process
    lines: list[str] = []
    try:
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.strip()
            lines = (lines + [line])[-30:]
            match = re.search(r"(\d{1,3}(?:\.\d+)?)%", line)
            if match:
                progress = min(96, max(10, int(float(match.group(1)))))
                _patch(job_id, progress=progress, message="Reconstructing frames without subtitles")
        code = process.wait()
        current = get(job_id)
        if current["status"] == "cancelled":
            return
        if code != 0 or not output.is_file():
            raise RuntimeError("\n".join(lines)[-1600:] or f"SubClean exited with code {code}")
        _patch(job_id, status="completed", progress=100, message="Clean derived source ready", output_path=str(output.resolve()))
    except Exception as exc:
        if get(job_id)["status"] != "cancelled":
            _patch(job_id, status="failed", progress=0, message="SubClean failed", error=str(exc))
    finally:
        with _lock:
            _processes.pop(job_id, None)


def cancel(job_id: str) -> dict[str, Any]:
    get(job_id)
    with _lock:
        process = _processes.get(job_id)
    if process and process.poll() is None:
        process.terminate()
    _patch(job_id, status="cancelled", message="SubClean cancelled", error=None)
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
