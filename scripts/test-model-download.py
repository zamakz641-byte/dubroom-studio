from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app import engine_service  # noqa: E402


def main() -> None:
    checks = []
    for engine_id in (
        "faster-whisper-tiny",
        "translation-qwen3-0.6b-q8",
        "translation-nllb-600m-int8",
    ):
        result = engine_service.validate_model_source(engine_id)
        assert result["has_model"], result
        assert result["reachable"], result
        assert result["revision"], result
        checks.append({
            "engine_id": engine_id,
            "repo_id": result["repo_id"],
            "file_name": result["file_name"],
            "revision": str(result["revision"])[:12],
        })

    # Exercise the same HTTPS, redirect, local-write and checksum path used by
    # model installers with a tiny repository file, never with model weights.
    source = "https://huggingface.co/Systran/faster-whisper-tiny/resolve/main/README.md"
    request = urllib.request.Request(source, headers={"User-Agent": "Dubroom/0.1 download-test"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read(1_000_000)
    assert payload.startswith(b"---") or b"faster-whisper" in payload.lower()
    with tempfile.TemporaryDirectory(prefix="dubroom-model-download-") as folder:
        target = Path(folder) / "README.md"
        target.write_bytes(payload)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        assert target.stat().st_size == len(payload)
        assert len(digest) == 64

    installable_models = [
        engine
        for engine in engine_service.load_registry()["engines"]
        if engine.get("installable") and engine.get("model")
    ]
    for engine in installable_models:
        preview = engine_service.installation_preview(str(engine["id"]))
        script = ROOT / "scripts" / "engines" / str(preview["script"])
        assert script.is_file(), f"Missing installer: {script}"

    print(json.dumps({
        "ok": True,
        "remote_sources": checks,
        "lightweight_download_bytes": len(payload),
        "sha256": digest,
        "installers_validated": len(installable_models),
        "model_weights_downloaded": False,
    }, indent=2))


if __name__ == "__main__":
    main()
