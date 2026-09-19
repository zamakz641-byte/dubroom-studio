from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import soundfile
import torch
import torchaudio


def _soundfile_load(path: str | Path, *args: object, **kwargs: object) -> tuple[torch.Tensor, int]:
    del args, kwargs
    samples, sample_rate = soundfile.read(str(path), dtype="float32", always_2d=True)
    return torch.from_numpy(samples.T.copy()), int(sample_rate)


# Torchaudio 2.11 delegates file decoding to TorchCodec, whose Windows wheels
# are not yet compatible with this shared CUDA runtime. F5 only needs a tensor
# and sample rate here, so SoundFile is a lossless and substantially lighter
# decoder for the temporary WAV prepared by F5.
torchaudio.load = _soundfile_load

from f5_tts.api import F5TTS


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark official F5-TTS voice cloning")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--reference-text", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--nfe", type=int, default=16)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    model = F5TTS(
        model="F5TTS_v1_Base",
        device="cuda",
        hf_cache_dir=str(Path("data/cache/huggingface").resolve()),
    )
    load_seconds = time.perf_counter() - started

    started = time.perf_counter()
    wav, sample_rate, _ = model.infer(
        ref_file=str(args.reference.resolve()),
        ref_text=args.reference_text,
        gen_text=args.text,
        nfe_step=args.nfe,
        file_wave=str(args.output.resolve()),
        seed=42,
    )
    generation_seconds = time.perf_counter() - started
    audio_seconds = len(wav) / sample_rate
    print(
        json.dumps(
            {
                "engine": "F5TTS_v1_Base",
                "license": "CC-BY-NC-4.0",
                "device": str(model.device),
                "nfe_step": args.nfe,
                "load_seconds": round(load_seconds, 3),
                "generation_seconds": round(generation_seconds, 3),
                "audio_seconds": round(audio_seconds, 3),
                "realtime_multiple": round(audio_seconds / generation_seconds, 3),
                "output_path": str(args.output.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
