from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import scipy.io.wavfile
from pocket_tts import TTSModel


DEFAULT_LINES = [
    "La nuit semblait calme, mais personne n'osait détourner le regard.",
    "Aujourd'hui a lieu la cérémonie de majorité de Damien, mais personne ne le bénit.",
    "Pas même Sa Majesté, son propre père, ne lui adresse un seul mot.",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Kyutai Pocket TTS in one process")
    parser.add_argument("--language", default="french_24l")
    parser.add_argument("--voice", default="estelle")
    parser.add_argument("--output", type=Path, default=Path("data/test-runs/kyutai-pocket"))
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    model = TTSModel.load_model(language=args.language)
    load_seconds = time.perf_counter() - started

    started = time.perf_counter()
    voice_state = model.get_state_for_audio_prompt(args.voice)
    voice_state_seconds = time.perf_counter() - started

    rows = []
    for index, text in enumerate(DEFAULT_LINES, start=1):
        started = time.perf_counter()
        audio = model.generate_audio(voice_state, text)
        generation_seconds = time.perf_counter() - started
        audio_seconds = audio.numel() / model.sample_rate
        output_path = args.output / f"warm-{index}.wav"
        scipy.io.wavfile.write(output_path, model.sample_rate, audio.numpy())
        rows.append(
            {
                "line": index,
                "text": text,
                "generation_seconds": round(generation_seconds, 3),
                "audio_seconds": round(audio_seconds, 3),
                "realtime_multiple": round(audio_seconds / generation_seconds, 3),
                "output_path": str(output_path.resolve()),
            }
        )

    total_generation = sum(row["generation_seconds"] for row in rows)
    total_audio = sum(row["audio_seconds"] for row in rows)
    print(
        json.dumps(
            {
                "engine": "kyutai-pocket-tts",
                "language": args.language,
                "voice": args.voice,
                "sample_rate": model.sample_rate,
                "load_seconds": round(load_seconds, 3),
                "voice_state_seconds": round(voice_state_seconds, 3),
                "total_generation_seconds": round(total_generation, 3),
                "total_audio_seconds": round(total_audio, 3),
                "realtime_multiple": round(total_audio / total_generation, 3),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
