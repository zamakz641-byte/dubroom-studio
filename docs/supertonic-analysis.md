# Supertonic 3 TTS analysis

## Local clone

- Repository: `models/research/supertonic`
- Upstream: https://github.com/supertone-inc/supertonic
- Python package docs: https://supertone-inc.github.io/supertonic-py
- Public model assets: https://huggingface.co/Supertone/supertonic-3
- Voice Builder: https://supertonic.supertone.ai/voice-builder

## What it gives us

Supertonic 3 is a local, ONNX-based multilingual TTS engine. The repository describes it as CPU-friendly, with public assets around 99M parameters, and outputs 44.1 kHz WAV audio.

The Python SDK path is the simplest integration for Dub Studio. The current upstream README shows a language-aware call, but the installed PyPI package on this workstation exposes `synthesize(text, voice_style, total_steps, speed, ...)` without `lang`. The backend adapter detects the available signature and passes the language only when the installed package supports it.

```python
from supertonic import TTS

tts = TTS(auto_download=True)
style = tts.get_voice_style(voice_name="M1")
wav, duration = tts.synthesize(
    text="Bonjour, ceci est un test.",
    lang="fr",
    voice_style=style,
    total_steps=8,
    speed=1.05,
)
tts.save_audio(wav, "output.wav")
```

The first run can download model assets from Hugging Face. For the desktop app, Supertonic must therefore stay opt-in until Settings has a clear download/install flow.

## Languages

The public helper lists these supported language tags:

`ar`, `bg`, `cs`, `da`, `de`, `el`, `en`, `es`, `et`, `fi`, `fr`, `hi`, `hr`, `hu`, `id`, `it`, `ja`, `ko`, `lt`, `lv`, `nl`, `pl`, `pt`, `ro`, `ru`, `sk`, `sl`, `sv`, `tr`, `uk`, `vi`, plus `na` for language-agnostic input.

Chinese is not in that public Supertonic 3 list, so the backend adapter maps `zh` to `na`.

## Voices

The repo and Hugging Face notes mention preset voice styles including:

- `M1`, `F1`, `M2`, `F2`
- newer styles: `M3`, `M4`, `M5`, `F3`, `F4`, `F5`

The app adapter defaults to `M1`. Later, Settings should expose these presets per speaker and allow importing custom Voice Builder JSON files.

## Voice Builder

The open-weight repository is fixed-voice TTS. It does not include the official voice cloning/training pipeline.

Voice Builder is a separate web workflow. It turns a short reference recording into a permanent custom voice profile and lets the user download version-specific JSON files for Supertonic 2 and Supertonic 3. For Dub Studio, the expected future UX is:

1. User creates voice in Voice Builder.
2. User downloads the Supertonic 3 JSON file.
3. User imports that JSON into Dub Studio as a speaker voice style.
4. Backend passes that JSON path to the Supertonic adapter.

## Integration decision

- Added `supertonic` to backend requirements.
- Added `engine="supertonic"` support in `services/api/app/tts_service.py`.
- Supertonic assets are directed to `models/supertonic` instead of the default user cache, so desktop installs stay self-contained and avoid Windows cache permission issues.
- Added `DUB_TTS_ENGINE=supertonic` override for backend testing.
- Added `supertonic_3` to `models/registry.json`.
- Not default yet: this avoids surprising model downloads during normal voice generation.

## License/product note

The repository sample code is MIT, but the model assets have their own model terms/OpenRAIL-M notes. Before commercial packaging, recheck the latest model license and whether bundling/distributing the weights inside an installer is allowed.
