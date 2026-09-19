from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = WORKSPACE_ROOT / "config" / "app.config.json"


def _load_file_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


FILE_CONFIG = _load_file_config()


def _configured_path(key: str, fallback: str) -> Path:
    relative = str((FILE_CONFIG.get("storage") or {}).get(key, fallback))
    return (WORKSPACE_ROOT / relative).resolve()


def _path_from_env(name: str, fallback: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser().resolve() if value else fallback.resolve()


@dataclass(frozen=True)
class AppPaths:
    workspace: Path
    data: Path
    models: Path
    projects: Path
    exports: Path
    cache: Path
    temp: Path
    environments: Path
    installers: Path

    def public(self) -> dict[str, str]:
        return {key: str(value) for key, value in asdict(self).items()}


def load_paths() -> AppPaths:
    data_root = _path_from_env("DUBSTUDIO_DATA_ROOT", _configured_path("data", "data"))
    paths = AppPaths(
        workspace=WORKSPACE_ROOT,
        data=data_root,
        models=_path_from_env("DUBSTUDIO_MODELS_ROOT", _configured_path("models", "models")),
        projects=_path_from_env("DUBSTUDIO_PROJECTS_ROOT", _configured_path("projects", "projects")),
        exports=_path_from_env("DUBSTUDIO_EXPORTS_ROOT", _configured_path("exports", "exports")),
        cache=_path_from_env("DUBSTUDIO_CACHE_ROOT", _configured_path("cache", "data/cache")),
        temp=_path_from_env("DUBSTUDIO_TEMP_ROOT", _configured_path("temp", "data/temp")),
        environments=_path_from_env("DUBSTUDIO_ENVS_ROOT", _configured_path("environments", "data/environments")),
        installers=WORKSPACE_ROOT / "scripts" / "engines",
    )
    for folder in (paths.data, paths.projects, paths.exports, paths.cache, paths.temp, paths.environments):
        folder.mkdir(parents=True, exist_ok=True)
    return paths


PATHS = load_paths()
API_HOST = os.getenv("DUBSTUDIO_API_HOST", str((FILE_CONFIG.get("api") or {}).get("host", "127.0.0.1")))
API_PORT = int(os.getenv("DUBSTUDIO_API_PORT", str((FILE_CONFIG.get("api") or {}).get("port", 8766))))


def load_runtime_config() -> dict[str, Any]:
    settings_path = PATHS.data / "settings.json"
    stored: dict[str, Any] = {}
    if settings_path.exists():
        try:
            stored = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            stored = {}
    return {
        "api": {"host": API_HOST, "port": API_PORT, "base_url": f"http://{API_HOST}:{API_PORT}"},
        "tts": {"runtime": "dubroom-native-tts", "data": str(PATHS.data / "tts"), "models": str(PATHS.models)},
        "paths": PATHS.public(),
        "preferences": stored,
    }
