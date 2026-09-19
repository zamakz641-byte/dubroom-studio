from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def human_bytes(value: float | int | None) -> str:
    if not value or value <= 0:
        return "?"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    return f"{size:.1f} {units[index]}" if index else f"{int(size)} B"


def human_eta(seconds: float | int | None) -> str:
    if seconds is None or seconds < 0:
        return "?"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def write_state(progress: int, message: str, **extra: Any) -> None:
    state_path = os.environ.get("DUB_ENGINE_STATE")
    if not state_path:
        return
    status = "repairing" if os.environ.get("DUB_ENGINE_REPAIR") == "1" else "installing"
    payload: dict[str, Any] = {
        "status": status,
        "progress": max(0, min(99, int(progress))),
        "message": message,
        "log_path": os.environ.get("DUB_ENGINE_LOG"),
        "updated_at": now(),
    }
    payload.update({key: value for key, value in extra.items() if value is not None})
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, indent=2)
    for attempt in range(5):
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(encoded, encoding="utf-8")
            tmp.replace(path)
            return
        except OSError:
            tmp.unlink(missing_ok=True)
            if attempt < 4:
                time.sleep(0.08 * (attempt + 1))


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def hf_total_bytes(repo_id: str, revision: str, file_name: str = "") -> int | None:
    from huggingface_hub import HfApi

    try:
        info = HfApi().model_info(repo_id=repo_id, revision=revision, files_metadata=True, token=os.environ.get("HF_TOKEN") or None)
    except Exception:
        return None
    total = 0
    for sibling in info.siblings or []:
        name = getattr(sibling, "rfilename", "") or ""
        size = getattr(sibling, "size", None)
        if file_name and name != file_name:
            continue
        if size:
            total += int(size)
    return total or None


class ProgressMonitor:
    def __init__(self, target: Path, total_bytes: int | None, start: int, end: int, label: str) -> None:
        self.target = target
        self.total_bytes = total_bytes
        self.start = start
        self.end = end
        self.label = label
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.last_bytes = directory_size(target)
        self.last_time = time.time()
        self.smoothed_speed = 0.0

    def __enter__(self) -> "ProgressMonitor":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        self.thread.join(timeout=2)

    def run(self) -> None:
        while not self.stop.is_set():
            current = directory_size(self.target)
            elapsed = max(0.001, time.time() - self.last_time)
            instant_speed = max(0.0, (current - self.last_bytes) / elapsed)
            if instant_speed > 0:
                self.smoothed_speed = (
                    instant_speed
                    if self.smoothed_speed <= 0
                    else self.smoothed_speed * 0.72 + instant_speed * 0.28
                )
            elif self.smoothed_speed > 0:
                self.smoothed_speed *= 0.985
            speed = self.smoothed_speed
            ratio = min(1.0, current / self.total_bytes) if self.total_bytes else 0.0
            progress = self.start + int((self.end - self.start) * ratio) if self.total_bytes else min(self.end - 1, self.start + int(current / (64 * 1024 * 1024)))
            remaining = max(0, (self.total_bytes or 0) - current) if self.total_bytes else None
            eta = remaining / speed if remaining is not None and speed > 1 else None
            total_text = human_bytes(self.total_bytes) if self.total_bytes else "taille inconnue"
            write_state(
                progress,
                f"{self.label}: {human_bytes(current)} / {total_text} - {human_bytes(speed)}/s - ETA {human_eta(eta)}",
                phase="download",
                downloaded_bytes=current,
                total_bytes=self.total_bytes,
                speed_bps=round(speed, 2),
                eta_seconds=round(eta, 1) if eta is not None else None,
            )
            self.last_bytes = current
            self.last_time = time.time()
            self.stop.wait(1.5)


def main() -> None:
    from huggingface_hub import hf_hub_download, snapshot_download

    target = Path(os.environ["DUB_ENGINE_MODELS"])
    target.mkdir(parents=True, exist_ok=True)
    local_subdir = str(os.environ.get("DUB_MODEL_LOCAL_SUBDIR") or "snapshot").strip()
    repo = os.environ["DUB_MODEL_REPO"]
    revision = os.environ.get("DUB_MODEL_REVISION", "main")
    runtime = os.environ.get("DUB_MODEL_RUNTIME", "")
    file_name = os.environ.get("DUB_MODEL_FILE", "")
    kind = os.environ.get("DUB_MODEL_KIND", "")
    helper_kind = os.environ.get("DUB_HELPER_KIND", "generic")

    total = hf_total_bytes(repo, revision, file_name)
    write_state(38, f"Verification du depot {repo}", phase="metadata", total_bytes=total)

    if runtime == "onnx":
        with ProgressMonitor(target, total, 40, 92, "Export ONNX"):
            from optimum.exporters.onnx import main_export

            output = target / "onnx"
            if helper_kind == "asr":
                task = "automatic-speech-recognition"
            else:
                task = "text2text-generation-with-past" if kind == "seq2seq" else "text-generation-with-past"
            main_export(model_name_or_path=repo, output=output, task=task)
            model_path = output
    elif file_name:
        with ProgressMonitor(target, total, 40, 94, "Telechargement du fichier modele"):
            model_path = hf_hub_download(repo_id=repo, filename=file_name, revision=revision, local_dir=target, token=os.environ.get("HF_TOKEN") or None)
    else:
        with ProgressMonitor(target, total, 40, 94, "Telechargement du modele"):
            model_path = snapshot_download(repo_id=repo, revision=revision, local_dir=target / local_subdir, token=os.environ.get("HF_TOKEN") or None)

    manifest = {
        "schema_version": 2,
        "engine_id": os.environ["DUB_ENGINE_ID"],
        "repo_id": repo,
        "original_repo_id": os.environ.get("DUB_MODEL_ORIGINAL_REPO", ""),
        "file_name": file_name or None,
        "model_path": str(model_path),
        "snapshot": str(model_path),
        "runtime": runtime,
        "family": os.environ.get("DUB_TTS_FAMILY") or None,
        "quantization": os.environ.get("DUB_MODEL_QUANTIZATION", ""),
        "downloaded_bytes": directory_size(target),
        "expected_bytes": total,
    }
    (target / "model.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_state(98, "Modele verifie localement", phase="validate", downloaded_bytes=manifest["downloaded_bytes"], total_bytes=total)


if __name__ == "__main__":
    main()
