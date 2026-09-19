from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterator


_GPU_SLOT = threading.Semaphore(1)
_LIGHT_CPU_SLOTS = threading.Semaphore(2)
_HEAVY_CPU_SLOT = threading.Semaphore(1)
_STATE_LOCK = threading.Lock()
_ACTIVE: dict[int, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def model_slot(
    workload: str,
    *,
    device: str,
    light: bool = False,
    on_wait: Callable[[str], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Iterator[None]:
    """Serialize heavy model work so only one large model occupies VRAM at once."""
    normalized_device = "cuda" if str(device).lower() == "cuda" else "cpu"
    semaphore = _GPU_SLOT if normalized_device == "cuda" else (_LIGHT_CPU_SLOTS if light else _HEAVY_CPU_SLOT)
    wait_message = (
        f"Waiting for GPU: another model is finishing before {workload}"
        if normalized_device == "cuda"
        else f"Waiting for a CPU worker before {workload}"
    )
    notified = False
    while not semaphore.acquire(timeout=0.5):
        if is_cancelled and is_cancelled():
            raise RuntimeError(f"{workload} cancelled while waiting for resources")
        if on_wait and not notified:
            on_wait(wait_message)
            notified = True

    token = id(threading.current_thread()) ^ int(time.time_ns())
    with _STATE_LOCK:
        _ACTIVE[token] = {
            "workload": workload,
            "device": normalized_device,
            "light": light,
            "started_at": _now(),
        }
    try:
        yield
    finally:
        with _STATE_LOCK:
            _ACTIVE.pop(token, None)
        semaphore.release()


def status() -> dict[str, Any]:
    with _STATE_LOCK:
        active = list(_ACTIVE.values())
    return {
        "active": active,
        "gpu_busy": any(item["device"] == "cuda" for item in active),
        "heavy_cpu_busy": any(item["device"] == "cpu" and not item["light"] for item in active),
        "light_cpu_active": sum(1 for item in active if item["device"] == "cpu" and item["light"]),
    }
