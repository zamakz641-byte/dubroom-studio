from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "apps" / "desktop" / "public"
BRAND_CATALOG = ROOT / "models" / "brand-catalog.json"
TTS_CATALOG = ROOT / "models" / "tts-catalog.json"


def main() -> None:
    payload = json.loads(BRAND_CATALOG.read_text(encoding="utf-8"))
    brands = payload.get("brands", {})
    assert payload.get("schema_version") == 2
    assert isinstance(brands, dict) and brands

    verified = 0
    for brand_id, brand in brands.items():
        asset = str(brand.get("asset", ""))
        assert asset.startswith("/"), f"{brand_id}: asset is not a public path"
        path = PUBLIC / asset.lstrip("/")
        assert path.is_file(), f"{brand_id}: missing {path}"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == brand.get("checksum"), f"{brand_id}: checksum mismatch"
        assert brand.get("asset_type") in {
            "official-project-icon",
            "verified-owner-mark",
            "verified-publisher-mark",
            "generated-fallback",
        }
        if brand.get("asset_type") == "generated-fallback":
            assert brand.get("asset_source") == "local"
        else:
            assert str(brand.get("official_url", "")).startswith("https://")
            assert str(brand.get("asset_source", "")).startswith("https://")
        verified += 1

    engine_to_brand = {
        "qwen": "qwen",
        "qwen_custom_voice": "qwen",
        "qwen_voice_design": "qwen",
        "chatterbox": "chatterbox",
        "chatterbox_turbo": "chatterbox",
        "chatterbox_nano": "chatterbox",
        "supertonic": "dubroom",
        "tada": "tada",
        "kokoro": "kokoro",
        "luxtts": "luxtts",
    }
    tts = json.loads(TTS_CATALOG.read_text(encoding="utf-8"))
    voice_models = tts.get("models", [])
    for model in voice_models:
        engine = model.get("engine")
        assert engine in engine_to_brand, f"No brand mapping for TTS engine {engine}"
        assert engine_to_brand[engine] in brands

    print(
        json.dumps(
            {
                "ok": True,
                "verified_local_assets": verified,
                "voice_models_covered": len(voice_models),
                "remote_runtime_assets": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
