from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .config import PATHS


_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _venv_root(python_executable: Path) -> Path:
    return python_executable.resolve().parent.parent


def _site_packages(venv_root: Path) -> Path:
    return venv_root / "Lib" / "site-packages"


def _python_version(venv_root: Path) -> str:
    config_path = venv_root / "pyvenv.cfg"
    if config_path.is_file():
        for line in config_path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip().lower() == "version":
                parts = value.strip().split(".")
                return ".".join(parts[:2])
    return ""


def _module_present(site_packages: Path, module: str) -> bool:
    top_level = module.split(".", 1)[0]
    return (site_packages / top_level).exists() or any(
        site_packages.glob(f"{top_level}.*")
    )


def _probe_imports(
    python_executable: Path,
    modules: list[str],
    shared_paths: list[Path],
) -> tuple[bool, str]:
    payload = json.dumps([str(path) for path in shared_paths])
    statements = [
        "import json,sys",
        f"[sys.path.append(p) for p in json.loads({payload!r}) if p not in sys.path]",
        *(f"import {module}" for module in modules),
        "print('ok')",
    ]
    code = ";".join(statements)
    completed = subprocess.run(
        [str(python_executable), "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    detail = (completed.stderr or completed.stdout).strip()
    return completed.returncode == 0, detail


def resolve_shared_dependencies(
    python_executable: Path,
    modules: list[str],
) -> dict[str, Any]:
    """Reuse missing modules from ABI-compatible local runtimes.

    The selected site-packages folders are appended after the target runtime's
    own packages, so an engine always keeps its pinned Torch/ML stack. This
    resolver never installs or downloads packages.
    """

    python_executable = python_executable.resolve()
    if not python_executable.is_file():
        return {
            "status": "missing-runtime",
            "paths": [],
            "providers": {},
            "missing": modules,
            "error": f"Python runtime not found: {python_executable}",
        }

    requested = list(dict.fromkeys(module for module in modules if _MODULE_NAME.fullmatch(module)))
    target_venv = _venv_root(python_executable)
    target_site = _site_packages(target_venv)
    target_version = _python_version(target_venv)
    selected_paths: list[Path] = []
    providers: dict[str, str] = {}
    missing: list[str] = []

    candidates: list[tuple[int, str, Path]] = []
    for environment in PATHS.environments.iterdir() if PATHS.environments.exists() else []:
        if not environment.is_dir():
            continue
        venv_root = environment / "venv"
        if not venv_root.is_dir() and (environment / "Lib" / "site-packages").is_dir():
            venv_root = environment
        site_packages = _site_packages(venv_root)
        if (
            not site_packages.is_dir()
            or site_packages.resolve() == target_site.resolve()
            or _python_version(venv_root) != target_version
        ):
            continue
        name = environment.name
        priority = 0 if name.startswith("shared-") else 1 if name.startswith("faster-whisper-") else 2
        candidates.append((priority, name, site_packages))
    candidates.sort(key=lambda item: (item[0], item[1]))

    for module in requested:
        local_ok, _ = _probe_imports(python_executable, [module], selected_paths)
        if local_ok:
            providers[module] = "target-runtime"
            continue

        found = False
        for _, environment_name, site_packages in candidates:
            if not _module_present(site_packages, module):
                continue
            trial_paths = [*selected_paths]
            if site_packages not in trial_paths:
                trial_paths.append(site_packages)
            import_ok, _ = _probe_imports(python_executable, [*providers.keys(), module], trial_paths)
            if not import_ok:
                continue
            selected_paths = trial_paths
            providers[module] = environment_name
            found = True
            break
        if not found:
            missing.append(module)

    final_ok, error = _probe_imports(
        python_executable,
        [module for module in requested if module not in missing],
        selected_paths,
    )
    return {
        "status": "ready" if not missing and final_ok else "missing-dependencies",
        "python": str(python_executable),
        "python_version": target_version,
        "paths": [str(path) for path in selected_paths],
        "providers": providers,
        "missing": missing,
        "error": "" if not missing and final_ok else error,
    }
