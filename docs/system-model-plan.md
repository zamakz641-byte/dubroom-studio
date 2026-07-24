# System and model plan

Date: 2026-05-17

## Detected machine

The current machine is not the RTX 4050 target machine.

- Model: Dell Latitude E7270
- CPU: Intel Core i5-6300U, 2 cores / 4 threads
- RAM: about 8 GB
- GPU: Intel HD Graphics 520
- CUDA/NVIDIA: not detected (`nvidia-smi` not found)
- OS: Windows 10 Pro 64-bit

This machine is good for product development, UI work, FFmpeg media preparation, backend routing, and small CPU model tests. It is not a realistic machine for high-quality multi-speaker AI dubbing.

## Target machine assumption

The planned RTX 4050 laptop should be treated as the real local AI target.

- Expected VRAM: usually around 6 GB on laptop RTX 4050 configurations.
- Minimum RAM: 16 GB.
- Preferred RAM: 32 GB.
- Strategy: chunk long videos, unload models between pipeline stages, prefer INT8/quantized inference, and keep one heavy model active at a time.

## Recommended model stack

### Current Dell CPU fallback

- Media: FFmpeg.
- ASR: `whisper.cpp` tiny/base quantized.
- Translation: Argos Translate.
- TTS preview: Piper first, Kokoro ONNX short-line experiments second.
- Diarization: only simple VAD/heuristic segmentation for now.
- LLM adaptation: avoid except tiny GGUF tests.

### RTX 4050 balanced target

- Media: FFmpeg.
- ASR: faster-whisper small/medium with INT8 first.
- Alignment: WhisperX-style alignment later, only after ASR jobs are stable.
- Diarization: pyannote community pipeline, with chunking and Hugging Face token handling.
- Translation: Argos Translate baseline, then local small LLM for adaptation.
- Adaptation LLM: llama.cpp with 1.5B-4B GGUF Q4 class models.
- TTS preview: Piper/Kokoro.
- Voice cloning research: F5-TTS and CosyVoice, but not as commercial defaults until model licenses are cleared.

## Commercial caution

The app goal is sellable desktop software, so model licenses matter as much as performance.

- Piper code is MIT, but voice/model packages still need per-voice checks.
- Argos Translate is offline and open source, with model package checks still required.
- pyannote code is MIT, but pretrained pipeline terms and Hugging Face access conditions must be accepted.
- F5-TTS code is MIT, but its README says pretrained models are CC-BY-NC, so they are research-only for this project unless replaced.
- CosyVoice requires a separate license/model-terms review before any commercial shipping.

## Sources checked

- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- pyannote.audio: https://github.com/pyannote/pyannote-audio
- Argos Translate: https://github.com/argosopentech/argos-translate
- Piper: https://github.com/rhasspy/piper
- Kokoro ONNX: https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX
- F5-TTS: https://github.com/SWivid/F5-TTS
- CosyVoice: https://github.com/FunAudioLLM/CosyVoice
- llama.cpp: https://github.com/ggml-org/llama.cpp

## Next implementation step

Add model registry reading to the backend and expose it in Settings, then implement the first real analysis job:

1. `GET /models/registry`
2. `POST /jobs/asr`
3. CPU fallback adapter for `whisper.cpp`
4. job status polling
5. transcript JSON saved under `projects/<id>/analysis/transcript.json`
