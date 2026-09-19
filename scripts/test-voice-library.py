from __future__ import annotations

import json
import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from services.api.app import native_tts_service, voice_library_service
from services.api.app.main import app


models = native_tts_service.models()["models"]
catalog = voice_library_service.catalog(models)
templates = catalog["templates"]
profiles = native_tts_service.profiles()
omnivoice_profiles = [
    profile
    for profile in profiles
    if profile.get("origin") == "dubroom-omnivoice-library"
]
routes = {route.path for route in app.routes}
required_routes = {
    "/tts/voice-library",
    "/tts/voice-library/omnivoice/build",
    "/tts/voice-library/omnivoice/cancel",
}

assert len(templates) == 18
assert len({item["id"] for item in templates}) == 18
assert all(item["speaker_mode"] == "single-speaker" for item in templates)
assert all(item["multi_speaker_compatible"] for item in templates)
assert catalog["runtime"]["ready"] is True
assert catalog["runtime"]["local_only"] is True
assert Path(catalog["runtime"]["model_path"]).is_dir()
assert len(models) == len(catalog["engines"])
assert all(model.get("speaker_mode") for model in models)
assert all(model.get("multi_speaker_compatible") for model in models)
assert required_routes <= routes

generated = int(catalog["summary"]["generated"])
if generated:
    assert len(omnivoice_profiles) == generated
    assert all(profile.get("prompt_ready") for profile in omnivoice_profiles)
    assert all(profile.get("default_engine") == "tts-omnivoice-hq" for profile in omnivoice_profiles)

builder_source = voice_library_service.BUILDER_PATH.read_text(encoding="utf-8")
assert 'HF_HUB_OFFLINE", "1"' in builder_source
assert "load_omnivoice_local_only" in builder_source
assert "--model-path" in builder_source

print(
    json.dumps(
        {
            "configured_profiles": len(templates),
            "generated_profiles": generated,
            "classified_engines": len(models),
            "runtime_device": catalog["runtime"]["device"],
            "local_only": catalog["runtime"]["local_only"],
            "routes": sorted(required_routes),
        },
        ensure_ascii=False,
        indent=2,
    )
)
