from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "tts-cosyvoice3-0.5b"

os.environ.setdefault("HF_HOME", str(ROOT / "data" / "cache" / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# huggingface_hub reads these flags while importing its constants module.
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="FunAudioLLM/Fun-CosyVoice3-0.5B-2512",
    local_dir=MODEL_DIR,
    allow_patterns=[
        "README.md",
        "config.json",
        "configuration.json",
        "cosyvoice3.yaml",
        "campplus.onnx",
        "speech_tokenizer_v3.onnx",
        "llm.pt",
        "flow.pt",
        "hift.pt",
        "CosyVoice-BlankEN/*",
    ],
)

required = [
    "cosyvoice3.yaml",
    "campplus.onnx",
    "speech_tokenizer_v3.onnx",
    "llm.pt",
    "flow.pt",
    "hift.pt",
    "CosyVoice-BlankEN/model.safetensors",
]
missing = [name for name in required if not (MODEL_DIR / name).is_file()]
if missing:
    raise SystemExit(f"CosyVoice 3 incomplet: {', '.join(missing)}")

print(f"COSYVOICE3_READY={MODEL_DIR}")
