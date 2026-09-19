from __future__ import annotations

import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.api.app import library_service, local_voice_service


with tempfile.TemporaryDirectory(prefix="dubroom-library-") as folder:
    root = Path(folder)
    library_service.LIBRARY_ROOT = root / "library"
    library_service.INDEX_PATH = library_service.LIBRARY_ROOT / "assets.json"
    sample = root / "authorized-sample.wav"
    sample.write_bytes(b"RIFF" + b"\0" * 64)

    capture = library_service.create_asset({"kind": "captures", "name": "Capture test", "path": str(sample)})
    glossary = library_service.create_asset({"kind": "glossaries", "name": "Noms", "content": "Jin-Woo = djin wou"})
    assert Path(capture["path"]).is_file()
    assert library_service.list_assets("captures")[0]["id"] == capture["id"]
    assert library_service.list_assets("glossaries")[0]["content"] == glossary["content"]
    assert library_service.delete_asset(capture["id"])
    assert not Path(capture["path"]).exists()
    assert len(library_service.list_assets()) == 1

print("Library persistence: capture copy, glossary save, filtering and deletion passed")

with tempfile.TemporaryDirectory(prefix="dubroom-voices-") as folder:
    root = Path(folder)
    local_voice_service.ROOT = root / "voice-profiles"
    local_voice_service.INDEX_PATH = local_voice_service.ROOT / "profiles.json"
    sample = root / "authorized-sample.wav"
    sample.write_bytes(b"RIFF" + b"\0" * 64)
    profile = local_voice_service.create_profile({
        "name": "Narratrice locale",
        "language": "fr",
        "voice_type": "cloned",
        "default_engine": "tts-qwen3-1.7b-base",
    })
    result = local_voice_service.add_sample(profile["id"], str(sample), "Phrase de référence")
    saved = local_voice_service.get(profile["id"])
    assert saved is not None
    assert saved["origin"] == "dubroom-native"
    assert saved["default_engine"] == "tts-qwen3-1.7b-base"
    assert saved["sample_count"] == 1
    assert Path(result["sample"]["path"]).is_file()

print("Local voice profiles: offline creation and authorized sample persistence passed")
