from __future__ import annotations

import argparse
import inspect
from pathlib import Path

from supertonic import TTS


def main() -> None:
    parser = argparse.ArgumentParser(description="Dub Studio Supertonic worker")
    parser.add_argument("--model", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--language", default="fr")
    parser.add_argument("--voice", default="M1")
    parser.add_argument("--speed", type=float, default=1.05)
    args = parser.parse_args()
    tts = TTS(model_dir=Path(args.model), auto_download=False)
    voice_style = tts.get_voice_style(voice_name=args.voice)
    kwargs = {"text": args.text, "voice_style": voice_style, "total_steps": 8, "speed": max(0.7, min(2.0, args.speed))}
    parameters = inspect.signature(tts.synthesize).parameters
    if "lang" in parameters:
        kwargs["lang"] = args.language
    elif "language" in parameters:
        kwargs["language"] = args.language
    wav, _duration = tts.synthesize(**kwargs)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tts.save_audio(wav, str(output))


if __name__ == "__main__":
    main()
