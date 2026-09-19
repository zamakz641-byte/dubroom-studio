from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "tts-cosyvoice3-gguf"

os.environ.setdefault("HF_HOME", str(ROOT / "data" / "cache" / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

from huggingface_hub import snapshot_download


FILES = [
    "cosyvoice3-llm-q4_k.gguf",
    "cosyvoice3-flow-q8_0.gguf",
    "cosyvoice3-s3tok-q4_k.gguf",
    "cosyvoice3-hift-f16.gguf",
    "cosyvoice3-campplus-f16.gguf",
    "cosyvoice3-voices.gguf",
]

snapshot_download(
    repo_id="cstr/cosyvoice3-0.5b-2512-GGUF",
    local_dir=MODEL_DIR,
    allow_patterns=FILES,
)

missing = [name for name in FILES if not (MODEL_DIR / name).is_file()]
if missing:
    raise SystemExit(f"CosyVoice 3 GGUF incomplet: {', '.join(missing)}")

print(f"COSYVOICE3_GGUF_READY={MODEL_DIR}")
