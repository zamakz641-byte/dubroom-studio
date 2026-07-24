from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from .config import PATHS
except ImportError:
    from config import PATHS


LIBRARY_ROOT = PATHS.data / "library"
INDEX_PATH = LIBRARY_ROOT / "assets.json"
KINDS = {"captures", "glossaries", "audio", "presets"}


def _read() -> list[dict[str, Any]]:
    if not INDEX_PATH.exists():
        return []
    try:
        payload = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write(items: list[dict[str, Any]]) -> None:
    LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
    temp = INDEX_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(INDEX_PATH)


def list_assets(kind: str | None = None) -> list[dict[str, Any]]:
    items = _read()
    return [item for item in items if not kind or item.get("kind") == kind]


def create_asset(payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload.get("kind") or "")
    name = str(payload.get("name") or "").strip()
    if kind not in KINDS:
        raise ValueError("Unsupported library asset kind")
    if not name:
        raise ValueError("Asset name is required")
    asset_id = uuid4().hex
    stored_path: str | None = None
    source = payload.get("path")
    if source:
        source_path = Path(str(source)).expanduser().resolve()
        if not source_path.is_file():
            raise ValueError("Selected asset file does not exist")
        target_dir = LIBRARY_ROOT / kind
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{asset_id}{source_path.suffix.lower()}"
        shutil.copy2(source_path, target)
        stored_path = str(target)
    now = datetime.now(timezone.utc).isoformat()
    asset = {
        "id": asset_id,
        "kind": kind,
        "name": name,
        "path": stored_path,
        "content": str(payload.get("content") or ""),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        "created_at": now,
        "updated_at": now,
    }
    items = _read()
    items.insert(0, asset)
    _write(items)
    return asset


def delete_asset(asset_id: str) -> bool:
    items = _read()
    target = next((item for item in items if item.get("id") == asset_id), None)
    if not target:
        return False
    stored = target.get("path")
    if stored:
        path = Path(str(stored)).resolve()
        root = LIBRARY_ROOT.resolve()
        if root in path.parents and path.is_file():
            path.unlink()
    _write([item for item in items if item.get("id") != asset_id])
    return True
