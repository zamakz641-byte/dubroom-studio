from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENTS = ROOT / "data" / "environments"
CATALOG = ROOT / "models" / "tts-catalog.json"


def directory_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def python_packages(python: Path) -> dict[str, str]:
    source = (
        "import importlib.metadata as m,json;"
        "print(json.dumps({(d.metadata.get('Name') or '').lower():d.version "
        "for d in m.distributions() if d.metadata.get('Name')},sort_keys=True))"
    )
    try:
        result = subprocess.run(
            [str(python), "-c", source],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=True,
        )
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError):
        return {}


def catalog_runtime_groups() -> dict[str, list[str]]:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    defaults = {
        "supertonic": "tts-supertonic-3",
        "kokoro": "tts-kokoro-82m",
        "luxtts": "tts-luxtts",
        "qwen3": "tts-qwen3-0.6b-base",
        "chatterbox": "tts-chatterbox-turbo",
        "tada": "tts-tada-1b",
    }
    groups: dict[str, list[str]] = defaultdict(list)
    for model in payload.get("models") or []:
        runtime = str(
            model.get("runtime_engine_id")
            or defaults.get(str(model.get("family")))
            or model["id"]
        )
        groups[runtime].append(str(model["id"]))
    return dict(groups)


def audit() -> dict[str, Any]:
    groups = catalog_runtime_groups()
    runtime_ids = set(groups)
    environments: list[dict[str, Any]] = []
    versions: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for root in sorted(ENVIRONMENTS.glob("tts-*")):
        if not root.is_dir():
            continue
        python = root / "venv" / "Scripts" / "python.exe"
        packages = python_packages(python) if python.is_file() else {}
        size = directory_bytes(root)
        for name, version in packages.items():
            versions[name][version].append(root.name)
        environments.append(
            {
                "id": root.name,
                "role": "shared-runtime" if root.name in runtime_ids else "model-marker",
                "apparent_bytes": size,
                "apparent_gib": round(size / (1024**3), 3),
                "python": str(python) if python.is_file() else None,
                "package_count": len(packages),
                "key_versions": {
                    name: packages.get(name)
                    for name in (
                        "torch",
                        "torchaudio",
                        "numpy",
                        "transformers",
                        "qwen-tts",
                        "faster-qwen3-tts",
                        "chatterbox-tts",
                        "onnxruntime-gpu",
                    )
                    if packages.get(name)
                },
            }
        )
    conflicts = {
        name: dict(by_version)
        for name, by_version in versions.items()
        if len(by_version) > 1
        and name
        in {
            "torch",
            "torchaudio",
            "numpy",
            "transformers",
            "onnxruntime-gpu",
        }
    }
    same_version_shared = {
        name: next(iter(by_version))
        for name, by_version in versions.items()
        if len(by_version) == 1
        and sum(len(items) for items in by_version.values()) > 1
    }
    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime_groups": groups,
        "environments": environments,
        "apparent_total_gib": round(
            sum(item["apparent_bytes"] for item in environments) / (1024**3), 3
        ),
        "version_conflicts_requiring_isolation": conflicts,
        "same_version_packages_reusable_via_uv_cache": same_version_shared,
        "policy": {
            "shared_store": "data/cache/uv on the same drive, UV_LINK_MODE=hardlink",
            "runtime_boundary": "share only within a catalog compatibility group",
            "specialized_stacks": [
                "Chatterbox PyTorch: Python 3.11, NumPy 1.26.4, Torch/Torchaudio 2.6.0 cu124",
                "Qwen Faster: Python 3.12, Torch CUDA 12.8, qwen-tts and faster-qwen3-tts 0.3.2",
                "Chatterbox ONNX: Python 3.11, NumPy 2 and onnxruntime-gpu without PyTorch",
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit DubRoom TTS runtime storage")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit()
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(serialized)


if __name__ == "__main__":
    main()
