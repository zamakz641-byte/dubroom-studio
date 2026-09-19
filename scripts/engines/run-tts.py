from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import warnings
import wave
from dataclasses import asdict
from pathlib import Path
from typing import Any


LANGUAGE_NAMES = {
    "auto": "Auto",
    "zh": "Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "de": "German",
    "fr": "French",
    "ru": "Russian",
    "pt": "Portuguese",
    "es": "Spanish",
    "it": "Italian",
}
KOKORO_LANGUAGE_CODES = {
    "en": "a",
    "en-us": "a",
    "gb": "b",
    "en-gb": "b",
    "es": "e",
    "fr": "f",
    "hi": "h",
    "it": "i",
    "ja": "j",
    "jp": "j",
    "pt": "p",
    "zh": "z",
}
KOKORO_DEFAULT_VOICES = {
    "a": "af_heart",
    "b": "bf_emma",
    "e": "ef_dora",
    "f": "ff_siwis",
    "h": "hf_alpha",
    "i": "if_sara",
    "j": "jf_alpha",
    "p": "pf_dora",
    "z": "zf_xiaobei",
}
TADA_LANGUAGE_CODES = {
    "ar": "ar",
    "zh": "ch",
    "ch": "ch",
    "de": "de",
    "es": "es",
    "fr": "fr",
    "it": "it",
    "ja": "ja",
    "pl": "pl",
    "pt": "pt",
}


CHATTERBOX_EVENT_TAGS = (
    "[clear throat]", "[sigh]", "[shush]", "[cough]", "[groan]",
    "[sniff]", "[gasp]", "[chuckle]", "[laugh]",
)
CHATTERBOX_PAUSE_PATTERN = re.compile(
    r"\[pause(?:\s*:\s*(?P<seconds>\d+(?:\.\d+)?))?\]",
    flags=re.IGNORECASE,
)


def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _set_seed(value: Any) -> None:
    if value is None:
        return
    import random
    import numpy as np
    import torch

    seed = int(value)
    random.seed(seed)
    np.random.seed(seed % (2**32 - 1))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _chatterbox_pause_parts(text: str, default_seconds: float) -> list[tuple[str, Any]]:
    """Split DubRoom pause tags without touching native Turbo event tags."""
    parts: list[tuple[str, Any]] = []
    cursor = 0
    for match in CHATTERBOX_PAUSE_PATTERN.finditer(text):
        spoken = text[cursor:match.start()].strip()
        if spoken:
            parts.append(("text", spoken))
        seconds = _clamp_float(match.group("seconds"), default_seconds, 0.05, 3.0)
        parts.append(("pause", seconds))
        cursor = match.end()
    tail = text[cursor:].strip()
    if tail:
        parts.append(("text", tail))
    return parts or [("text", text.strip())]


def _strip_chatterbox_event_tags(text: str) -> str:
    """Multilingual V3 does not natively implement Turbo's event tags."""
    for tag in CHATTERBOX_EVENT_TAGS:
        text = re.sub(re.escape(tag), " ", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def _request(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("The TTS request must be a JSON object")
    items = value.get("items")
    if not str(value.get("text") or "").strip() and not (
        isinstance(items, list) and items
    ):
        raise ValueError("Text or a non-empty items list is required")
    return value


def _reference(request: dict[str, Any], required: bool = False) -> tuple[str | None, str]:
    sample = request.get("sample") or {}
    path = str(sample.get("path") or "").strip()
    text = str(sample.get("reference_text") or "").strip()
    if path and not Path(path).is_file():
        raise FileNotFoundError(f"Reference audio is missing: {path}")
    if required and not path:
        raise ValueError("This engine requires a voice reference")
    return path or None, text


def _device() -> str:
    import torch

    requested = str(os.environ.get("DUBROOM_DEVICE") or "").strip().lower()
    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("This TTS engine was assigned to GPU, but CUDA is unavailable in its runtime")
        return "cuda"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _save_torch_audio(wav: Any, output: Path, sample_rate: int) -> None:
    import torchaudio

    if getattr(wav, "dim", lambda: 1)() == 1:
        wav = wav.unsqueeze(0)
    torchaudio.save(str(output), wav.detach().cpu().float(), sample_rate)


def _duration(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as source:
            return source.getnframes() / float(source.getframerate())
    except (OSError, wave.Error, ZeroDivisionError):
        # Torchaudio may write WAVE_FORMAT_EXTENSIBLE, which Python 3.11's
        # stdlib wave reader cannot parse even though the WAV is valid.
        try:
            import soundfile as sf

            return float(sf.info(str(path)).duration)
        except Exception:
            return None


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _max_new_tokens(request: dict[str, Any]) -> int:
    explicit = request.get("max_new_tokens")
    if explicit is not None:
        return max(48, min(2400, int(explicit)))
    text = str(request.get("text") or "")
    language = str(request.get("language") or "auto").lower().split("-", 1)[0]
    units = len(text.strip()) if language in {"zh", "ja", "ko"} else len(text.split())
    # Qwen3-TTS emits acoustic tokens at 12 Hz. This leaves generous breathing
    # room while preventing a short line from running to the model's 8192-token
    # default (more than eleven minutes of audio).
    text_limit = max(
        72,
        min(2400, units * (8 if language in {"zh", "ja", "ko"} else 12) + 48),
    )
    try:
        target_duration = float(request.get("target_duration") or 0)
    except (TypeError, ValueError):
        target_duration = 0
    if target_duration <= 0:
        return text_limit
    # One codec frame is emitted at 12 Hz. Give the actor up to 50% breathing
    # room plus two seconds, while stopping rare runaway samples long before
    # they can generate tens of seconds beyond the available video segment.
    duration_limit = max(48, min(2400, round(target_duration * 12 * 1.5 + 24)))
    return min(text_limit, duration_limit)


def _qwen_fast_enabled() -> bool:
    value = str(os.environ.get("DUBROOM_QWEN_FAST") or "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _qwen_is_fast(model: Any) -> bool:
    return bool(getattr(model, "_dubroom_cuda_graphs", False))


def _qwen_non_streaming_mode(request: dict[str, Any], *, default: bool) -> bool:
    value = request.get("non_streaming_mode")
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _qwen_clone_mode(request: dict[str, Any]) -> str:
    value = str(
        request.get("clone_mode")
        or os.environ.get("DUBROOM_QWEN_CLONE_MODE")
        or "icl"
    ).strip().lower()
    return "xvector" if value in {"xvector", "x-vector", "speaker", "fast"} else "icl"


def _supertonic(request: dict[str, Any], model_root: Path, output: Path) -> int:
    from supertonic import TTS

    model_dir = model_root / "model"
    tts = TTS(model_dir=model_dir, auto_download=False)
    voice = str(request.get("voice") or "M1")
    voice_path = Path(voice)
    style = None
    if voice_path.suffix.lower() == ".json" and voice_path.is_file():
        for method_name in ("get_voice_style_from_path", "load_voice_style"):
            method = getattr(tts, method_name, None)
            if callable(method):
                style = method(str(voice_path))
                break
    if style is None:
        style = tts.get_voice_style(voice_name=voice)
    kwargs: dict[str, Any] = {
        "text": request["text"],
        "voice_style": style,
        "total_steps": max(5, min(12, int(request.get("quality_steps") or 8))),
        "speed": max(0.7, min(2.0, float(request.get("speed") or 1.0))),
    }
    language = str(request.get("language") or "en").lower().split("-", 1)[0]
    parameters = inspect.signature(tts.synthesize).parameters
    kwargs["lang" if "lang" in parameters else "language"] = language
    wav, _ = tts.synthesize(**kwargs)
    tts.save_audio(wav, str(output))
    return 44100


def _load_kokoro(model_root: Path) -> tuple[Any, Path, str]:
    warnings.filterwarnings(
        "ignore",
        message=r"dropout option adds dropout after all but last recurrent layer.*",
        category=UserWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"`torch\.nn\.utils\.weight_norm` is deprecated.*",
        category=FutureWarning,
    )
    from kokoro import KModel

    local = model_root / "model"
    model = KModel(
        config=str(local / "config.json"),
        model=str(local / "kokoro-v1_0.pth"),
    ).to(_device()).eval()
    return model, local, _device()


def _kokoro_generate(
    request: dict[str, Any],
    model: Any,
    local: Path,
    device: str,
    pipelines: dict[str, Any],
    output: Path,
) -> int:
    import numpy as np
    import soundfile as sf
    import torch
    from kokoro import KPipeline

    language = str(request.get("language") or "en").lower()
    language_code = KOKORO_LANGUAGE_CODES.get(
        language,
        KOKORO_LANGUAGE_CODES.get(language.split("-", 1)[0], "a"),
    )
    pipeline = pipelines.get(language_code)
    if pipeline is None:
        pipeline = KPipeline(lang_code=language_code, model=model, device=device)
        pipelines[language_code] = pipeline
    voice = str(request.get("voice") or KOKORO_DEFAULT_VOICES[language_code])
    voice_path = Path(voice)
    if not voice_path.is_file():
        voice_path = local / "voices" / f"{voice.removesuffix('.pt')}.pt"
    if not voice_path.is_file():
        raise FileNotFoundError(f"Kokoro voice is missing: {voice_path}")
    chunks = []
    with torch.inference_mode():
        for _, _, audio in pipeline(
            request["text"],
            voice=str(voice_path),
            speed=max(0.5, min(2.0, float(request.get("speed") or 1.0))),
        ):
            if audio is not None:
                chunks.append(np.asarray(audio))
    if not chunks:
        raise RuntimeError("Kokoro returned no audio")
    sf.write(str(output), np.concatenate(chunks), 24000)
    return 24000


def _kokoro(request: dict[str, Any], model_root: Path, output: Path) -> int:
    model, local, device = _load_kokoro(model_root)
    return _kokoro_generate(request, model, local, device, {}, output)


def _luxtts(request: dict[str, Any], model_root: Path, output: Path) -> int:
    import soundfile as sf
    from zipvoice.luxvoice import LuxTTS

    reference, _ = _reference(request, required=True)
    device = _device()
    kwargs: dict[str, Any] = {"device": device}
    if device == "cpu":
        kwargs["threads"] = max(1, min(8, os.cpu_count() or 2))
    tts = LuxTTS(str(model_root / "model"), **kwargs)
    encoded = tts.encode_prompt(
        reference,
        duration=float(request.get("reference_duration") or 5),
        rms=float(request.get("rms") or 0.01),
    )
    wav = tts.generate_speech(
        request["text"],
        encoded,
        num_steps=max(3, min(8, int(request.get("quality_steps") or 4))),
        t_shift=float(request.get("t_shift") or 0.9),
        speed=max(0.5, min(2.0, float(request.get("speed") or 1.0))),
        return_smooth=bool(request.get("smooth", False)),
    )
    sf.write(str(output), wav.detach().cpu().numpy().squeeze(), 48000)
    return 48000


def _load_qwen(model_root: Path) -> Any:
    import torch

    device = _device()
    if device == "cuda":
        torch.set_grad_enabled(False)
        torch.set_float32_matmul_precision("high")
        torch.backends.cuda.matmul.allow_tf32 = True
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cudnn.benchmark = True

    if device == "cuda" and _qwen_fast_enabled():
        try:
            from faster_qwen3_tts import FasterQwen3TTS

            max_seq_len = max(
                512,
                min(
                    2048,
                    int(os.environ.get("DUBROOM_QWEN_FAST_MAX_SEQ") or 1024),
                ),
            )
            _emit(
                {
                    "event": "loading_fast_qwen",
                    "runtime": "cuda_graphs",
                    "max_seq_len": max_seq_len,
                },
            )
            model = FasterQwen3TTS.from_pretrained(
                str(model_root / "model"),
                device="cuda",
                dtype=torch.bfloat16,
                attn_implementation="sdpa",
                max_seq_len=max_seq_len,
                local_files_only=True,
            )
            # Capture once during model loading so an unsupported driver or an
            # 8 GB VRAM overflow falls back before any project line can fail.
            model.warmup(prefill_len=min(128, max_seq_len // 2))
            model._dubroom_cuda_graphs = True
            model._dubroom_runtime = "cuda_graphs"
            return model
        except Exception as exc:
            _emit(
                {
                    "event": "fast_qwen_fallback",
                    "runtime": "upstream",
                    "reason": str(exc)[-800:],
                },
            )
            _clear_cuda_cache()

    from qwen_tts import Qwen3TTSModel

    load_kwargs: dict[str, Any] = {
        "device_map": "cuda:0" if device == "cuda" else "cpu",
        "dtype": torch.bfloat16 if device == "cuda" else torch.float32,
    }
    if device == "cuda":
        load_kwargs["attn_implementation"] = "sdpa"
    model = Qwen3TTSModel.from_pretrained(str(model_root / "model"), **load_kwargs)
    model._dubroom_cuda_graphs = False
    model._dubroom_runtime = "upstream"
    return model


def _load_qwen_clone_prompt(cache_path: Path) -> Any:
    import torch
    from qwen_tts import VoiceClonePromptItem

    try:
        payload = torch.load(str(cache_path), map_location="cpu", weights_only=True)
    except TypeError:
        # PyTorch versions predating weights_only still need the legacy call.
        payload = torch.load(str(cache_path), map_location="cpu")
    except Exception as exc:
        # Some PyTorch builds reject a safe tensor-only payload with the newer
        # weights-only unpickler. Retry the local DubRoom-owned cache normally.
        if "weights only" not in str(exc).casefold():
            raise
        payload = torch.load(str(cache_path), map_location="cpu", weights_only=False)

    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("Invalid cached Qwen voice prompt")
    restored = []
    for item in items:
        restored.append(
            VoiceClonePromptItem(
                ref_code=item.get("ref_code"),
                ref_spk_embedding=item["ref_spk_embedding"],
                x_vector_only_mode=bool(item.get("x_vector_only_mode", False)),
                icl_mode=bool(item.get("icl_mode", not item.get("x_vector_only_mode", False))),
                ref_text=item.get("ref_text"),
            ),
        )
    return restored


def _save_qwen_clone_prompt(cache_path: Path, prompt: Any) -> None:
    import torch

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".tmp")
    torch.save(
        {
            "schema_version": 1,
            "items": [asdict(item) for item in prompt],
        },
        str(temporary),
    )
    os.replace(temporary, cache_path)


def _qwen_language(request: dict[str, Any]) -> str:
    value = str(request.get("language") or "auto").lower().split("-", 1)[0]
    return LANGUAGE_NAMES.get(value, "Auto")


def _batch_item_id(item: dict[str, Any]) -> str:
    value = item.get("id")
    if value not in {None, ""}:
        return str(value)
    return str(item.get("_batch_index", ""))


def _qwen_clone_identity(
    request: dict[str, Any],
) -> tuple[str, str, bool, str, int | None]:
    reference, reference_text = _reference(request, required=True)
    sample = request.get("sample") or {}
    cache_path = str(sample.get("prompt_cache_path") or "").strip()
    x_vector_only = _qwen_clone_mode(request) == "xvector" or not bool(reference_text)
    if x_vector_only:
        reference_text = ""
        if cache_path:
            cache = Path(cache_path)
            cache_path = str(cache.with_name(f"{cache.stem}-xvector{cache.suffix}"))
    seed_value = request.get("seed")
    seed = int(seed_value) if seed_value is not None else None
    return str(reference), reference_text, x_vector_only, cache_path, seed


def _qwen_clone_prompt(
    request: dict[str, Any],
    model: Any,
    clone_prompts: dict[tuple[str, str, bool, str], Any],
) -> Any:
    reference, reference_text, x_vector_only, cache_value, _ = _qwen_clone_identity(
        request,
    )
    key = (reference, reference_text, x_vector_only, cache_value)
    prompt = clone_prompts.get(key)
    if prompt is not None:
        return prompt

    cache_path = Path(cache_value) if cache_value else None
    if cache_path and cache_path.is_file():
        try:
            prompt = _load_qwen_clone_prompt(cache_path)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            cache_path.unlink(missing_ok=True)
            prompt = None

    if prompt is None:
        prompt_model = model.model if _qwen_is_fast(model) else model
        prompt = prompt_model.create_voice_clone_prompt(
            ref_audio=reference,
            ref_text=reference_text or None,
            x_vector_only_mode=x_vector_only,
        )
        if cache_path:
            _save_qwen_clone_prompt(cache_path, prompt)

    clone_prompts[key] = prompt
    return prompt


def _qwen_micro_batch_size(request: dict[str, Any]) -> int:
    explicit = request.get("micro_batch_size")
    if explicit is None:
        explicit = os.environ.get("DUBROOM_QWEN_BATCH_SIZE")
    if explicit not in {None, ""}:
        try:
            return max(1, min(8, int(explicit)))
        except (TypeError, ValueError):
            pass

    import torch

    if _device() != "cuda" or not torch.cuda.is_available():
        return 1
    try:
        total_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    except Exception:
        return 2

    # Conservative defaults. A laptop RTX 4060 with 8 GB uses two lines.
    if total_gb < 7.0:
        return 1
    if total_gb < 10.5:
        return 2
    if total_gb < 16.0:
        return 3
    return 4


def _clear_cuda_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception:
        pass


def _qwen_wav_list(wavs: Any, expected: int) -> list[Any]:
    if isinstance(wavs, (list, tuple)):
        values = list(wavs)
    else:
        shape = getattr(wavs, "shape", None)
        if shape is not None and len(shape) >= 2 and int(shape[0]) == expected:
            values = [wavs[index] for index in range(expected)]
        else:
            values = [wavs]
    if len(values) != expected:
        raise RuntimeError(
            f"Qwen returned {len(values)} audio outputs for {expected} texts",
        )
    return values


def _qwen_clone_microbatch(
    items: list[dict[str, Any]],
    model: Any,
    clone_prompts: dict[tuple[str, str, bool, str], Any],
) -> list[dict[str, Any]]:
    import soundfile as sf
    import torch

    if not items:
        return []

    identity = _qwen_clone_identity(items[0])
    for item in items[1:]:
        if _qwen_clone_identity(item) != identity:
            raise ValueError("A Qwen clone micro-batch must use one locked voice")

    seed = identity[-1]
    if seed is not None:
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)

    prompt = _qwen_clone_prompt(items[0], model, clone_prompts)
    if _qwen_is_fast(model):
        results: list[dict[str, Any]] = []
        for item in items:
            started = time.perf_counter()
            wavs, sample_rate = model.generate_voice_clone(
                text=str(item["text"]),
                language=_qwen_language(item),
                voice_clone_prompt=prompt,
                ref_text=str((item.get("sample") or {}).get("reference_text") or ""),
                # The CUDA-graph runtime is substantially faster when it can
                # stream the text path. It still returns one complete WAV, so
                # DubRoom's duration fitting and export behavior stay intact.
                non_streaming_mode=_qwen_non_streaming_mode(item, default=False),
                append_silence=False,
                max_new_tokens=_max_new_tokens(item),
            )
            wav = wavs[0]
            output = Path(str(item.get("output_path") or "")).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(output), wav, sample_rate)
            if not output.is_file() or output.stat().st_size < 44:
                raise RuntimeError("The fast Qwen engine did not produce a valid WAV file")
            generation_seconds = time.perf_counter() - started
            duration = _duration(output)
            results.append(
                {
                    "id": _batch_item_id(item),
                    "status": "completed",
                    "output_path": str(output),
                    "sample_rate": int(sample_rate),
                    "duration": duration,
                    "runtime": "cuda_graphs",
                    "generation_seconds": round(generation_seconds, 3),
                    "audio_realtime_multiple": (
                        round(float(duration) / generation_seconds, 3)
                        if duration and generation_seconds > 0
                        else None
                    ),
                },
            )
        return results

    texts = [str(item["text"]) for item in items]
    languages = [_qwen_language(item) for item in items]
    max_new_tokens = max(_max_new_tokens(item) for item in items)

    wavs, sample_rate = model.generate_voice_clone(
        text=texts,
        language=languages,
        voice_clone_prompt=prompt,
        non_streaming_mode=True,
        max_new_tokens=max_new_tokens,
    )
    wav_list = _qwen_wav_list(wavs, len(items))

    results: list[dict[str, Any]] = []
    for item, wav in zip(items, wav_list, strict=True):
        output = Path(str(item.get("output_path") or "")).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output), wav, sample_rate)
        if not output.is_file() or output.stat().st_size < 44:
            raise RuntimeError("The TTS engine did not produce a valid WAV file")
        results.append(
            {
                "id": _batch_item_id(item),
                "status": "completed",
                "output_path": str(output),
                "sample_rate": int(sample_rate),
                "duration": _duration(output),
            },
        )
    return results


def _qwen_clone_microbatch_with_fallback(
    items: list[dict[str, Any]],
    model: Any,
    clone_prompts: dict[tuple[str, str, bool, str], Any],
) -> list[dict[str, Any]]:
    try:
        return _qwen_clone_microbatch(items, model, clone_prompts)
    except Exception as exc:
        if len(items) == 1:
            item = items[0]
            return [
                {
                    "id": _batch_item_id(item),
                    "status": "failed",
                    "output_path": str(
                        Path(str(item.get("output_path") or "")).resolve(),
                    ),
                    "error": str(exc),
                },
            ]

        # Qwen batches are sensitive to line length and available VRAM. Instead
        # of killing 256 lines because one pair was too ambitious, split the
        # failed batch until a safe size is found.
        _clear_cuda_cache()
        midpoint = max(1, len(items) // 2)
        _emit(
            {
                "event": "micro_batch_fallback",
                "size": len(items),
                "next_size": midpoint,
                "reason": str(exc)[-500:],
            },
        )
        return [
            *_qwen_clone_microbatch_with_fallback(
                items[:midpoint],
                model,
                clone_prompts,
            ),
            *_qwen_clone_microbatch_with_fallback(
                items[midpoint:],
                model,
                clone_prompts,
            ),
        ]


def _run_qwen_clone_batches(
    request: dict[str, Any],
    items: list[dict[str, Any]],
    model: Any,
    clone_prompts: dict[tuple[str, str, bool, str], Any],
) -> list[dict[str, Any]]:
    # Group by locked speaker prompt. generate_batch may contain several
    # speakers using the same Base model, and Qwen can only reuse one prompt
    # across a given prompt-single/synthesis-batch call.
    groups: dict[
        tuple[str, str, bool, str, int | None],
        list[dict[str, Any]],
    ] = {}
    for item in items:
        try:
            key = _qwen_clone_identity(item)
        except Exception as exc:
            item["_identity_error"] = str(exc)
            key = ("", "", False, f"invalid:{item.get('_batch_index')}", None)
        groups.setdefault(key, []).append(item)

    batch_size = _qwen_micro_batch_size(request)
    if _qwen_is_fast(model):
        batch_size = 1
    _emit(
        {
            "event": "micro_batch_config",
            "batch_size": batch_size,
            "voice_groups": len(groups),
            "total": len(items),
            "runtime": getattr(model, "_dubroom_runtime", "upstream"),
        },
    )

    by_index: dict[int, dict[str, Any]] = {}
    completed = 0

    def record(item: dict[str, Any], result: dict[str, Any]) -> None:
        nonlocal completed
        by_index[int(item["_batch_index"])] = result
        completed += 1
        _emit(
            {
                "event": "item_completed",
                "index": completed,
                "total": len(items),
                **result,
            },
        )

    for key, group in groups.items():
        # Similar-length lines waste less padding inside the same GPU call.
        group.sort(key=_max_new_tokens)
        if key[3].startswith("invalid:"):
            for item in group:
                result = {
                    "id": _batch_item_id(item),
                    "status": "failed",
                    "output_path": str(
                        Path(str(item.get("output_path") or "")).resolve(),
                    ),
                    "error": str(item.get("_identity_error") or "Invalid voice reference"),
                }
                record(item, result)
            continue

        for start in range(0, len(group), batch_size):
            chunk = group[start : start + batch_size]
            chunk_results = _qwen_clone_microbatch_with_fallback(
                chunk,
                model,
                clone_prompts,
            )
            for item, result in zip(chunk, chunk_results, strict=True):
                record(item, result)

    return [
        by_index.get(
            int(item["_batch_index"]),
            {
                "id": _batch_item_id(item),
                "status": "failed",
                "output_path": str(
                    Path(str(item.get("output_path") or "")).resolve(),
                ),
                "error": "Qwen returned no result for this line",
            },
        )
        for item in items
    ]


def _qwen_generate(
    request: dict[str, Any],
    model: Any,
    output: Path,
    mode: str,
    clone_prompts: dict[tuple[str, str, bool, str], Any] | None = None,
) -> int:
    import soundfile as sf
    import torch

    seed = request.get("seed")
    if seed is not None:
        torch.manual_seed(int(seed))
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(int(seed))
    language = _qwen_language(request)
    generation_kwargs = {
        "max_new_tokens": _max_new_tokens(request),
    }
    if mode == "clone":
        prompt_store = clone_prompts if clone_prompts is not None else {}
        prompt = _qwen_clone_prompt(request, model, prompt_store)
        wavs, sample_rate = model.generate_voice_clone(
            text=request["text"],
            language=language,
            voice_clone_prompt=prompt,
            ref_text=(
                str((request.get("sample") or {}).get("reference_text") or "")
                if _qwen_is_fast(model)
                else None
            ),
            non_streaming_mode=_qwen_non_streaming_mode(
                request,
                default=not _qwen_is_fast(model),
            ),
            **({"append_silence": False} if _qwen_is_fast(model) else {}),
            **generation_kwargs,
        )
    elif mode == "design":
        instruction = str(request.get("instruct") or request.get("design_prompt") or "").strip()
        if not instruction:
            raise ValueError("Qwen VoiceDesign requires a voice description")
        wavs, sample_rate = model.generate_voice_design(
            text=request["text"],
            language=language,
            instruct=instruction,
            **generation_kwargs,
        )
    else:
        wavs, sample_rate = model.generate_custom_voice(
            text=request["text"],
            language=language,
            speaker=str(request.get("voice") or "Ryan"),
            instruct=str(request.get("instruct") or ""),
            non_streaming_mode=_qwen_non_streaming_mode(request, default=True),
            **generation_kwargs,
        )
    sf.write(str(output), wavs[0], sample_rate)
    return int(sample_rate)


def _qwen(request: dict[str, Any], model_root: Path, output: Path, mode: str) -> int:
    model = _load_qwen(model_root)
    return _qwen_generate(request, model, output, mode, {})


def _load_kyutai_pocket(language_model: str) -> Any:
    from pocket_tts import TTSModel

    return TTSModel.load_model(language=language_model or "french_24l")


def _kyutai_pocket_voice(request: dict[str, Any]) -> str:
    sample = request.get("sample")
    if isinstance(sample, dict) and str(sample.get("path") or "").strip():
        return str(sample["path"])
    return str(request.get("voice") or "estelle")


def _kyutai_pocket_generate(
    request: dict[str, Any],
    model: Any,
    output: Path,
    voice_states: dict[str, Any],
) -> int:
    import scipy.io.wavfile

    voice = _kyutai_pocket_voice(request)
    state = voice_states.get(voice)
    if state is None:
        try:
            state = model.get_state_for_audio_prompt(voice)
        except ValueError as exc:
            if "voice cloning" in str(exc).lower():
                raise RuntimeError(
                    "Le clonage Kyutai doit d'abord être autorisé sur "
                    "https://huggingface.co/kyutai/pocket-tts puis connecté localement."
                ) from exc
            raise
        voice_states[voice] = state
        _emit({"event": "kyutai_voice_conditioned", "voice": voice})
    audio = model.generate_audio(
        state,
        str(request["text"]),
        max_tokens=max(10, min(500, int(request.get("max_tokens") or 100))),
    )
    scipy.io.wavfile.write(
        str(output),
        int(model.sample_rate),
        audio.detach().cpu().numpy(),
    )
    return int(model.sample_rate)


def _kyutai_pocket(
    request: dict[str, Any], model_root: Path, output: Path, language_model: str
) -> int:
    del model_root
    model = _load_kyutai_pocket(language_model)
    return _kyutai_pocket_generate(request, model, output, {})


def _cosyvoice3_executable() -> Path:
    root = Path(__file__).resolve().parents[2]
    cuda_root = root / "data" / "runtimes" / "crispasr-cuda-v0.8.25"
    if shutil.which("nvidia-smi") and cuda_root.is_dir():
        candidates = list(cuda_root.rglob("crispasr.exe"))
        if candidates:
            return candidates[0]
    candidates = list((root / "data" / "runtimes" / "crispasr-vulkan").rglob("crispasr.exe"))
    if not candidates:
        raise FileNotFoundError("The compact CosyVoice 3 runtime is not installed")
    return candidates[0]


def _cosyvoice3_environment(model_root: Path, flow_steps: int = 5) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "CRISPASR_COSYVOICE3_CAMPPLUS_PATH": str(
                model_root / "cosyvoice3-campplus-f16.gguf"
            ),
            "CRISPASR_COSYVOICE3_S3TOK_PATH": str(
                model_root / "cosyvoice3-s3tok-q4_k.gguf"
            ),
            "CRISPASR_COSYVOICE3_HIFT_PATH": str(
                model_root / "cosyvoice3-hift-f16.gguf"
            ),
            "CRISPASR_COSYVOICE3_VOICES_PATH": str(
                model_root / "cosyvoice3-voices.gguf"
            ),
            "CRISPASR_COSYVOICE3_FLOW_STEPS": str(flow_steps),
            # CrispASR 0.8.25 still reads the legacy spelling for this option.
            "COSYVOICE3_FLOW_STEPS": str(flow_steps),
            "CUDA_VISIBLE_DEVICES": "0",
        }
    )
    return environment


def _cosyvoice3_gguf(
    request: dict[str, Any], model_root: Path, output: Path
) -> int:
    reference, reference_text = _reference(request, required=True)
    assert reference is not None
    flow_steps = max(5, min(10, int(request.get("quality_steps") or 5)))
    command = [
        str(_cosyvoice3_executable()),
        "--backend",
        "cosyvoice3-tts",
        "-m",
        str(model_root / "cosyvoice3-llm-q4_k.gguf"),
        "--voice",
        reference,
        "--ref-text",
        reference_text,
        "--i-have-rights",
        "--no-spoken-disclaimer",
        "--accept-marking-responsibility",
        "--tts",
        str(request["text"]),
        "--tts-output",
        str(output),
        "--no-gpu",
    ]
    result = subprocess.run(
        command,
        cwd=model_root,
        env=_cosyvoice3_environment(model_root, flow_steps),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=360,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout)[-3000:])
    return 24000


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_cosyvoice3_server(process: subprocess.Popen[str], port: int) -> None:
    for _ in range(240):
        if process.poll() is not None:
            raise RuntimeError("CosyVoice 3 server exited during startup")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=1
            ) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise TimeoutError("CosyVoice 3 server startup timed out")


def _run_cosyvoice3_batch(
    items: list[dict[str, Any]], model_root: Path
) -> list[dict[str, Any]]:
    executable = _cosyvoice3_executable()
    cuda_enabled = "cuda" in str(executable).lower()
    port = _free_local_port()
    flow_steps = max(
        5,
        min(10, int(items[0].get("quality_steps") or 5)),
    )
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="dubroom-cosyvoice3-") as folder:
        voice_dir = Path(folder)
        voice_names: dict[tuple[str, str], str] = {}
        for item in items:
            reference, reference_text = _reference(item, required=True)
            assert reference is not None
            key = (str(Path(reference).resolve()), reference_text)
            if key in voice_names:
                continue
            name = f"voice-{len(voice_names) + 1}"
            destination = voice_dir / f"{name}.wav"
            try:
                os.link(Path(reference).resolve(), destination)
            except OSError:
                shutil.copy2(reference, destination)
            (voice_dir / f"{name}.txt").write_text(reference_text, encoding="utf-8")
            voice_names[key] = destination.name

        log_path = voice_dir / "server.log"
        with log_path.open("w", encoding="utf-8") as log:
            command = [
                    str(executable),
                    "--server",
                    "--backend",
                    "cosyvoice3-tts",
                    "-m",
                    str(model_root / "cosyvoice3-llm-q4_k.gguf"),
                    "--voice-dir",
                    str(voice_dir),
                    "--port",
                    str(port),
                    "--i-have-rights",
                ]
            if cuda_enabled:
                command.extend(["--gpu-backend", "cuda", "--device", "0"])
            else:
                command.append("--no-gpu")
            process = subprocess.Popen(
                command,
                cwd=voice_dir,
                env=_cosyvoice3_environment(model_root, flow_steps),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            try:
                _wait_cosyvoice3_server(process, port)
                _emit(
                    {
                        "event": "cosyvoice3_batch_config",
                        "runtime": "GGUF Q4/Q8 CUDA" if cuda_enabled else "GGUF Q4/Q8 CPU",
                        "device": "cuda" if cuda_enabled else "cpu",
                        "flow_steps": flow_steps,
                        "total": len(items),
                        "model_reused": True,
                        "voice_conditioning_cache": True,
                    }
                )
                for position, item in enumerate(items, start=1):
                    output = Path(str(item.get("output_path") or "")).resolve()
                    item_id = str(item.get("id") or item.get("_batch_index") or position)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    reference, reference_text = _reference(item, required=True)
                    assert reference is not None
                    key = (str(Path(reference).resolve()), reference_text)
                    payload = json.dumps(
                        {
                            "input": str(item["text"]),
                            "voice": voice_names[key],
                            "ref_text": reference_text,
                            "consent_attestation": "Authorized local DubRoom voice profile",
                            "spoken_disclaimer": False,
                            "marking_attestation": "DubRoom visibly identifies this track as AI-generated TTS and preserves embedded provenance",
                            "response_format": "wav",
                        }
                    ).encode("utf-8")
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/v1/audio/speech",
                        data=payload,
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(request, timeout=360) as response:
                            output.write_bytes(response.read())
                        result_item = {
                            "id": item_id,
                            "status": "completed",
                            "output_path": str(output),
                            "sample_rate": 24000,
                            "duration": _duration(output),
                        }
                    except urllib.error.HTTPError as exc:
                        detail = exc.read().decode("utf-8", "replace")
                        result_item = {
                            "id": item_id,
                            "status": "failed",
                            "output_path": str(output),
                            "error": detail[-2000:],
                        }
                    results.append(result_item)
                    _emit(
                        {
                            "event": "item_completed",
                            "index": position,
                            "total": len(items),
                            **result_item,
                        }
                    )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
    return results


def _batch_items(request: dict[str, Any]) -> list[dict[str, Any]]:
    common = {key: value for key, value in request.items() if key != "items"}
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(request.get("items") or []):
        if not isinstance(raw, dict):
            continue
        item = {**common, **raw}
        if not str(item.get("text") or "").strip():
            continue
        item["_batch_index"] = index
        items.append(item)
    return items


# STORYRECAP_PATCH046_OMNIVOICE_TRUE_MICROBATCH
# True GPU micro-batching for OmniVoice clone mode.
# The outer Story Recapper request already contains only the requested/missing
# units. This layer only changes how those items are synthesized on GPU.
def _omnivoice_patch046_batch_size(request: dict[str, Any]) -> int:
    explicit = (
        request.get("omnivoice_micro_batch_size")
        or os.environ.get("STORYRECAP_OMNIVOICE_BATCH_SIZE")
        or os.environ.get("DUBROOM_OMNIVOICE_BATCH_SIZE")
    )
    if explicit not in {None, ""}:
        try:
            return max(1, min(8, int(explicit)))
        except (TypeError, ValueError):
            pass

    try:
        import torch
        if _device() != "cuda" or not torch.cuda.is_available():
            return 1
        total_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    except Exception:
        # Conservative default for the target RTX 4060 Laptop 8 GB.
        return 2

    if total_gb < 7.0:
        return 1
    if total_gb < 10.5:
        return 2
    if total_gb < 16.0:
        return 3
    return 4


def _omnivoice_patch046_clear_cuda() -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception:
        pass


def _omnivoice_patch046_language(item: dict[str, Any]) -> str:
    return str(item.get("language") or "fr").lower().split("-", 1)[0]


def _omnivoice_patch046_signature(
    item: dict[str, Any],
    variant: str,
) -> tuple[Any, ...]:
    sample = item.get("sample") or {}
    cache_value = str(sample.get("prompt_cache_path") or "").strip()
    sample_value = str(sample.get("path") or sample.get("audio_path") or "").strip()
    ref_text = str(sample.get("reference_text") or "").strip()

    # A manually seeded request stays single-item so batching never changes its
    # deterministic semantics.
    seed = item.get("seed")
    if seed is not None:
        seed_key: Any = ("single_seed", item.get("_batch_index"))
    else:
        seed_key = None

    return (
        variant,
        _omnivoice_patch046_language(item),
        cache_value,
        sample_value,
        ref_text,
        bool(item.get("preprocess_prompt", True)),
        max(16, min(64, int(item.get("omnivoice_steps") or item.get("num_step") or 32))),
        float(item.get("guidance_scale") or 2.0),
        bool(item.get("denoise", True)),
        float(item.get("t_shift") or 0.1),
        float(item.get("position_temperature") or 5.0),
        float(item.get("class_temperature") or 0.0),
        float(item.get("layer_penalty_factor") or 5.0),
        bool(item.get("normalize_text", False)),
        bool(item.get("postprocess_output", True)),
        max(0.0, min(1.0, float(item.get("pad_duration") or 0.1))),
        max(0.0, min(0.5, float(item.get("fade_duration") or 0.1))),
        seed_key,
    )


def _omnivoice_patch046_size_hint(item: dict[str, Any]) -> tuple[int, int]:
    text = str(item.get("text") or "")
    # Similar lengths in the same GPU batch reduce padding/wasted compute.
    return (len(text.split()), len(text))


def _omnivoice_patch046_duration_value(item: dict[str, Any]) -> float | None:
    value = item.get("duration")
    if value in {None, ""}:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _omnivoice_patch046_generate_chunk(
    items: list[dict[str, Any]],
    model: Any,
    variant: str,
    prompt_cache: dict[str, Any],
) -> list[dict[str, Any]]:
    import soundfile as sf
    import time as _time046

    if not items:
        return []

    first = items[0]
    first_sig = _omnivoice_patch046_signature(first, variant)
    for item in items[1:]:
        if _omnivoice_patch046_signature(item, variant) != first_sig:
            raise ValueError("PATCH-046 OmniVoice batch mixed incompatible voice/config items")

    texts = [_omnivoice_text(item) for item in items]
    languages = [_omnivoice_patch046_language(item) for item in items]
    prompts = [_omnivoice_prompt(item, model, prompt_cache) for item in items]
    speeds = [max(0.5, min(2.0, float(item.get("speed") or 1.0))) for item in items]
    durations = [_omnivoice_patch046_duration_value(item) for item in items]

    language0 = languages[0]
    kwargs: dict[str, Any] = {
        "text": texts,
        "language": languages,
        "voice_clone_prompt": prompts,
        "speed": speeds,
        "num_step": max(
            16,
            min(64, int(first.get("omnivoice_steps") or first.get("num_step") or 32)),
        ),
        "guidance_scale": float(first.get("guidance_scale") or 2.0),
        "denoise": bool(first.get("denoise", True)),
        "t_shift": float(first.get("t_shift") or 0.1),
        "position_temperature": float(first.get("position_temperature") or 5.0),
        "class_temperature": float(first.get("class_temperature") or 0.0),
        "layer_penalty_factor": float(first.get("layer_penalty_factor") or 5.0),
        "normalize_text": _omnivoice_normalize_text(first, language0),
        "postprocess_output": bool(first.get("postprocess_output", True)),
        "pad_duration": max(0.0, min(1.0, float(first.get("pad_duration") or 0.1))),
        "fade_duration": max(0.0, min(0.5, float(first.get("fade_duration") or 0.1))),
    }
    if any(value is not None for value in durations):
        kwargs["duration"] = durations

    started = _time046.perf_counter()
    audios = model.generate(**kwargs)
    elapsed = _time046.perf_counter() - started

    if not isinstance(audios, (list, tuple)):
        raise RuntimeError("PATCH-046: OmniVoice batch did not return a list")
    if len(audios) != len(items):
        raise RuntimeError(
            f"PATCH-046: OmniVoice returned {len(audios)} audios for {len(items)} texts"
        )

    sample_rate = int(getattr(model, "sampling_rate", None) or 24000)
    results: list[dict[str, Any]] = []
    temp_paths: list[Path] = []
    try:
        for item, audio in zip(items, audios):
            output = Path(str(item.get("output_path") or "")).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            tmp = output.with_name(
                output.stem + f".patch046.{os.getpid()}.tmp.wav"
            )
            temp_paths.append(tmp)
            sf.write(str(tmp), audio, sample_rate)
            if not tmp.is_file() or tmp.stat().st_size < 44:
                raise RuntimeError("PATCH-046: OmniVoice produced an invalid temporary WAV")
            os.replace(tmp, output)
            duration = _duration(output)
            results.append(
                {
                    "id": str(item.get("id") or item.get("_batch_index") or ""),
                    "status": "completed",
                    "output_path": str(output),
                    "sample_rate": sample_rate,
                    "duration": duration,
                    "micro_batch_size": len(items),
                    "batch_generation_seconds": round(elapsed, 3),
                }
            )
    finally:
        for tmp in temp_paths:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    return results


def _omnivoice_patch046_generate_with_fallback(
    items: list[dict[str, Any]],
    model: Any,
    variant: str,
    prompt_cache: dict[str, Any],
) -> list[dict[str, Any]]:
    try:
        return _omnivoice_patch046_generate_chunk(
            items, model, variant, prompt_cache
        )
    except Exception as exc:
        if len(items) == 1:
            item = items[0]
            output = Path(str(item.get("output_path") or "")).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            try:
                sample_rate = _omnivoice_generate(
                    item, model, output, variant, prompt_cache
                )
                if not output.is_file() or output.stat().st_size < 44:
                    raise RuntimeError("OmniVoice did not produce a valid WAV file")
                return [
                    {
                        "id": str(item.get("id") or item.get("_batch_index") or ""),
                        "status": "completed",
                        "output_path": str(output),
                        "sample_rate": sample_rate,
                        "duration": _duration(output),
                        "micro_batch_size": 1,
                        "fallback_single": True,
                    }
                ]
            except Exception as single_exc:
                return [
                    {
                        "id": str(item.get("id") or item.get("_batch_index") or ""),
                        "status": "failed",
                        "output_path": str(output),
                        "error": str(single_exc),
                    }
                ]

        _omnivoice_patch046_clear_cuda()
        midpoint = max(1, len(items) // 2)
        _emit(
            {
                "event": "omnivoice_micro_batch_fallback",
                "size": len(items),
                "next_size": midpoint,
                "reason": str(exc)[-500:],
            }
        )
        return [
            *_omnivoice_patch046_generate_with_fallback(
                items[:midpoint], model, variant, prompt_cache
            ),
            *_omnivoice_patch046_generate_with_fallback(
                items[midpoint:], model, variant, prompt_cache
            ),
        ]


def _run_omnivoice_micro_batches(
    request: dict[str, Any],
    items: list[dict[str, Any]],
    model: Any,
    variant: str,
    prompt_cache: dict[str, Any],
) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for item in items:
        key = _omnivoice_patch046_signature(item, variant)
        groups.setdefault(key, []).append(item)

    batch_size = _omnivoice_patch046_batch_size(request)
    _emit(
        {
            "event": "omnivoice_micro_batch_config",
            "batch_size": batch_size,
            "voice_groups": len(groups),
            "total": len(items),
            "model_reused": True,
            "prompt_reused": True,
            "true_gpu_batch": batch_size > 1,
            "device": _device(),
        }
    )

    by_index: dict[int, dict[str, Any]] = {}
    completed_position = 0

    def record(item: dict[str, Any], result: dict[str, Any]) -> None:
        nonlocal completed_position
        index = int(item.get("_batch_index") or 0)
        by_index[index] = result
        completed_position += 1
        _emit(
            {
                "event": "item_completed",
                "index": completed_position,
                "total": len(items),
                **result,
            }
        )

    for _key046, group in groups.items():
        # Keep identical voice/config together, then put similar-length lines
        # next to each other to reduce padding inside OmniVoice's batch tensor.
        group = sorted(group, key=_omnivoice_patch046_size_hint)

        # Seeded requests received a unique signature above and therefore remain
        # singleton automatically.
        for start in range(0, len(group), batch_size):
            chunk = group[start : start + batch_size]
            chunk_results = _omnivoice_patch046_generate_with_fallback(
                chunk, model, variant, prompt_cache
            )
            for item, result in zip(chunk, chunk_results):
                record(item, result)

    results: list[dict[str, Any]] = []
    for item in items:
        index = int(item.get("_batch_index") or 0)
        result = by_index.get(index)
        if result is None:
            result = {
                "id": str(item.get("id") or index),
                "status": "failed",
                "output_path": str(Path(str(item.get("output_path") or "")).resolve()),
                "error": "PATCH-046: no result returned for this item",
            }
        results.append(result)
    return results


def _run_batch(
    request: dict[str, Any],
    model_root: Path,
    family: str,
    variant: str,
) -> list[dict[str, Any]]:
    items = _batch_items(request)
    if not items:
        raise ValueError("The TTS batch contains no valid text items")
    _emit({"event": "loading_model", "total": len(items)})
    if family == "cosyvoice3_gguf":
        return _run_cosyvoice3_batch(items, model_root)
    kokoro_runtime: tuple[Any, Path, str] | None = None
    qwen_model: Any = None
    omnivoice_model: Any = None
    omnivoice_prompts: dict[str, Any] = {}
    chatterbox_model: Any = None
    kyutai_model: Any = None
    pipelines: dict[str, Any] = {}
    clone_prompts: dict[tuple[str, str, bool, str], Any] = {}
    chatterbox_conditions: dict[tuple[str, float, bool], Any] = {}
    kyutai_voice_states: dict[str, Any] = {}
    if family == "kokoro":
        kokoro_runtime = _load_kokoro(model_root)
    elif family == "qwen3":
        qwen_model = _load_qwen(model_root)
    elif family == "omnivoice":
        omnivoice_model = _load_omnivoice(model_root)
    elif family == "chatterbox":
        chatterbox_model = _load_chatterbox(model_root, variant)
        _emit({
            "event": "chatterbox_batch_config",
            "runtime": variant,
            "total": len(items),
            "model_reused": True,
            "voice_conditioning_cache": True,
        })
    elif family == "kyutai_pocket":
        kyutai_model = _load_kyutai_pocket(variant)
        _emit({
            "event": "kyutai_batch_config",
            "runtime": variant,
            "total": len(items),
            "model_reused": True,
            "voice_conditioning_cache": True,
            "device": "cpu",
        })
    else:
        raise ValueError(f"Batch TTS is not implemented for family: {family}")

    _emit({
        "event": "model_loaded",
        "family": family,
        "variant": variant,
        "total": len(items),
        "device": _device(),
    })

    if family == "qwen3" and variant == "clone":
        return _run_qwen_clone_batches(
            request,
            items,
            qwen_model,
            clone_prompts,
        )

    if family == "omnivoice" and omnivoice_model is not None and variant == "clone":
        return _run_omnivoice_micro_batches(
            request,
            items,
            omnivoice_model,
            variant,
            omnivoice_prompts,
        )

    results: list[dict[str, Any]] = []
    for position, item in enumerate(items, start=1):
        output = Path(str(item.get("output_path") or "")).resolve()
        item_id = str(item.get("id") or item.get("_batch_index") or position)
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            if family == "kokoro" and kokoro_runtime is not None:
                model, local, device = kokoro_runtime
                sample_rate = _kokoro_generate(
                    item, model, local, device, pipelines, output
                )
            elif family == "qwen3":
                sample_rate = _qwen_generate(
                    item,
                    qwen_model,
                    output,
                    variant,
                    clone_prompts,
                )
            elif family == "omnivoice" and omnivoice_model is not None:
                sample_rate = _omnivoice_generate(
                    item,
                    omnivoice_model,
                    output,
                    variant,
                    omnivoice_prompts,
                )
            elif family == "chatterbox" and chatterbox_model is not None:
                sample_rate = _chatterbox_generate(
                    item,
                    chatterbox_model,
                    output,
                    variant,
                    chatterbox_conditions,
                )
            elif family == "kyutai_pocket" and kyutai_model is not None:
                sample_rate = _kyutai_pocket_generate(
                    item,
                    kyutai_model,
                    output,
                    kyutai_voice_states,
                )
            else:
                raise ValueError(f"Unsupported batch TTS family: {family}")
            if not output.is_file() or output.stat().st_size < 44:
                raise RuntimeError("The TTS engine did not produce a valid WAV file")
            result = {
                "id": item_id,
                "status": "completed",
                "output_path": str(output),
                "sample_rate": sample_rate,
                "duration": _duration(output),
            }
        except Exception as exc:
            result = {
                "id": item_id,
                "status": "failed",
                "output_path": str(output),
                "error": str(exc),
            }
        results.append(result)
        _emit(
            {
                "event": "item_completed",
                "index": position,
                "total": len(items),
                **result,
            }
        )
    return results



CHATTERBOX_ONNX_SAMPLE_RATE = 24000
CHATTERBOX_ONNX_START_TOKEN = 6561
CHATTERBOX_ONNX_STOP_TOKEN = 6562
CHATTERBOX_ONNX_SILENCE_TOKEN = 4299
CHATTERBOX_ONNX_KV_HEADS = 16
CHATTERBOX_ONNX_HEAD_DIM = 64


def _chatterbox_onnx_suffix(mode: str) -> str:
    if mode == "turbo_onnx_fp16":
        return "_fp16"
    if mode == "turbo_onnx_q4f16":
        return "_q4f16"
    raise ValueError(f"Unsupported Chatterbox ONNX mode: {mode}")


def _onnx_device(available_providers: set[str]) -> str:
    """Resolve the ONNX execution device without importing PyTorch.

    The dedicated Chatterbox ONNX environment intentionally does not install
    torch. CUDA availability must therefore be determined from ONNX Runtime's
    registered execution providers, not from torch.cuda.
    """
    requested = str(os.environ.get("DUBROOM_DEVICE") or "").strip().lower()
    cuda_available = "CUDAExecutionProvider" in available_providers
    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        if not cuda_available:
            raise RuntimeError(
                "This Chatterbox ONNX engine was assigned to GPU, but "
                "CUDAExecutionProvider is unavailable in ONNX Runtime. "
                "Repair the engine after checking the NVIDIA driver and CUDA runtime."
            )
        return "cuda"
    return "cuda" if cuda_available else "cpu"


def _load_chatterbox_onnx(model_root: Path, mode: str) -> dict[str, Any]:
    import onnxruntime as ort

    # ORT 1.21+ can preload the CUDA/cuDNN DLL wheels installed beside the
    # runtime. Merely listing CUDAExecutionProvider does not prove those DLLs
    # can be loaded; without this, ORT silently falls back to CPU on Windows.
    if hasattr(ort, "preload_dlls"):
        ort.preload_dlls(directory="")

    # AutoTokenizer works without a deep-learning backend. Suppress Transformers'
    # advisory warning because this runtime deliberately uses ONNX Runtime only.
    os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
    from transformers import AutoTokenizer

    local = model_root / "model"
    onnx_dir = local / "onnx"
    suffix = _chatterbox_onnx_suffix(mode)

    def graph(name: str) -> Path:
        path = onnx_dir / f"{name}{suffix}.onnx"
        data_path = Path(str(path) + "_data")
        if not path.is_file() or not data_path.is_file():
            raise FileNotFoundError(
                f"Chatterbox ONNX {mode} is incomplete: {path.name} or its external data file is missing"
            )
        return path

    available = set(ort.get_available_providers())
    device = _onnx_device(available)
    providers = (
        ["CUDAExecutionProvider", "CPUExecutionProvider"]
        if device == "cuda"
        else ["CPUExecutionProvider"]
    )
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.enable_mem_pattern = True
    options.enable_cpu_mem_arena = True

    sessions = {
        "speech_encoder": ort.InferenceSession(str(graph("speech_encoder")), sess_options=options, providers=providers),
        "embed_tokens": ort.InferenceSession(str(graph("embed_tokens")), sess_options=options, providers=providers),
        "language_model": ort.InferenceSession(str(graph("language_model")), sess_options=options, providers=providers),
        "decoder": ort.InferenceSession(str(graph("conditional_decoder")), sess_options=options, providers=providers),
    }
    if device == "cuda":
        inactive = [
            name
            for name, session in sessions.items()
            if "CUDAExecutionProvider" not in session.get_providers()
        ]
        if inactive:
            raise RuntimeError(
                "Chatterbox ONNX could not activate CUDA for: "
                + ", ".join(inactive)
                + ". Repair the ONNX engine to install its pinned CUDA 12 DLLs."
            )
    tokenizer = AutoTokenizer.from_pretrained(str(local), local_files_only=True)
    return {
        "runtime": "onnxruntime",
        "mode": mode,
        "sr": CHATTERBOX_ONNX_SAMPLE_RATE,
        "sessions": sessions,
        "tokenizer": tokenizer,
        "providers": {
            name: session.get_providers() for name, session in sessions.items()
        },
    }


def _chatterbox_onnx_max_tokens(request: dict[str, Any]) -> int:
    explicit = request.get("max_new_tokens")
    if explicit is not None:
        return max(48, min(2048, int(explicit)))
    text = str(request.get("text") or "")
    words = max(1, len(text.split()))
    text_limit = max(96, min(2048, words * 16 + 64))
    try:
        target = float(request.get("target_duration") or 0)
    except (TypeError, ValueError):
        target = 0
    if target <= 0:
        return text_limit
    duration_limit = max(64, min(2048, round(target * 25 * 1.45 + 32)))
    return min(text_limit, duration_limit)


def _chatterbox_onnx_repetition_penalty(
    generated: Any,
    logits: Any,
    penalty: float,
) -> Any:
    import numpy as np

    score = np.take_along_axis(logits, generated, axis=1)
    score = np.where(score < 0, score * penalty, score / penalty)
    result = logits.copy()
    np.put_along_axis(result, generated, score, axis=1)
    return result


def _chatterbox_onnx_sample(
    logits: Any,
    generated: Any,
    request: dict[str, Any],
    rng: Any,
) -> Any:
    import numpy as np

    penalty = _clamp_float(request.get("repetition_penalty"), 1.2, 1.0, 2.0)
    logits = _chatterbox_onnx_repetition_penalty(generated, logits, penalty)
    temperature = _clamp_float(request.get("temperature"), 0.8, 0.05, 2.0)
    top_p = _clamp_float(request.get("top_p"), 0.95, 0.0, 1.0)
    min_p = _clamp_float(request.get("min_p"), 0.0, 0.0, 1.0)
    top_k = max(0, min(1000, int(request.get("top_k") or 1000)))

    values = logits[0].astype(np.float64) / temperature
    if 0 < top_k < values.size:
        threshold = np.partition(values, -top_k)[-top_k]
        values[values < threshold] = -np.inf
    values -= np.nanmax(values)
    probs = np.exp(values)
    probs[~np.isfinite(probs)] = 0
    total = probs.sum()
    if total <= 0:
        return np.array([[int(np.argmax(logits[0]))]], dtype=np.int64)
    probs /= total
    if min_p > 0:
        probs[probs < probs.max() * min_p] = 0
    if 0 < top_p < 1:
        order = np.argsort(probs)[::-1]
        cumulative = np.cumsum(probs[order])
        remove = cumulative - probs[order] > top_p
        probs[order[remove]] = 0
    total = probs.sum()
    if total <= 0:
        return np.array([[int(np.argmax(logits[0]))]], dtype=np.int64)
    probs /= total
    token = int(rng.choice(probs.size, p=probs))
    return np.array([[token]], dtype=np.int64)


def _chatterbox_onnx_voice_key(request: dict[str, Any]) -> str:
    reference, _ = _reference(request, required=True)
    return str(Path(reference).resolve())


def _prepare_chatterbox_onnx_voice(
    request: dict[str, Any],
    runtime: dict[str, Any],
    cache: dict[str, Any],
) -> tuple[Any, Any, Any, Any]:
    import librosa
    import numpy as np

    key = _chatterbox_onnx_voice_key(request)
    cached = cache.get(key)
    if cached is not None:
        return cached
    audio, _ = librosa.load(key, sr=CHATTERBOX_ONNX_SAMPLE_RATE, mono=True)
    if audio.size < CHATTERBOX_ONNX_SAMPLE_RATE * 3:
        raise ValueError("Chatterbox requires at least three seconds of usable reference audio; five to ten seconds is recommended")
    audio_values = audio[np.newaxis, :].astype(np.float32)
    result = runtime["sessions"]["speech_encoder"].run(None, {"audio_values": audio_values})
    if len(result) != 4:
        raise RuntimeError("The Chatterbox ONNX speech encoder returned an unexpected output layout")
    cached = tuple(result)
    cache[key] = cached
    _emit({
        "event": "chatterbox_voice_conditioned",
        "runtime": runtime["mode"],
        "reference": key,
        "cached_profiles": len(cache),
    })
    return cached


def _chatterbox_onnx_generate_text(
    request: dict[str, Any],
    runtime: dict[str, Any],
    text: str,
    condition_cache: dict[str, Any],
) -> Any:
    import numpy as np

    language = str(request.get("language") or "en").lower().split("-", 1)[0]
    if language != "en":
        raise ValueError("Chatterbox Turbo ONNX supports English only")
    tokenizer = runtime["tokenizer"]
    sessions = runtime["sessions"]
    input_ids = tokenizer(text, return_tensors="np")["input_ids"].astype(np.int64)
    cond_emb, prompt_token, speaker_embeddings, speaker_features = _prepare_chatterbox_onnx_voice(
        request, runtime, condition_cache
    )
    generated = np.array([[CHATTERBOX_ONNX_START_TOKEN]], dtype=np.int64)
    seed = int(request.get("seed") or 0)
    rng = np.random.default_rng(seed)
    ended = False

    for index in range(_chatterbox_onnx_max_tokens(request)):
        inputs_embeds = sessions["embed_tokens"].run(None, {"input_ids": input_ids})[0]
        if index == 0:
            inputs_embeds = np.concatenate((cond_emb, inputs_embeds), axis=1)
            batch_size, seq_len, _ = inputs_embeds.shape
            past_key_values = {
                item.name: np.zeros(
                    [batch_size, CHATTERBOX_ONNX_KV_HEADS, 0, CHATTERBOX_ONNX_HEAD_DIM],
                    dtype=np.float16 if item.type == "tensor(float16)" else np.float32,
                )
                for item in sessions["language_model"].get_inputs()
                if "past_key_values" in item.name
            }
            attention_mask = np.ones((batch_size, seq_len), dtype=np.int64)
            position_ids = np.arange(seq_len, dtype=np.int64).reshape(1, -1).repeat(batch_size, axis=0)

        outputs = sessions["language_model"].run(None, {
            "inputs_embeds": inputs_embeds,
            "attention_mask": attention_mask,
            "position_ids": position_ids,
            **past_key_values,
        })
        logits, present = outputs[0][:, -1, :], outputs[1:]
        input_ids = _chatterbox_onnx_sample(logits, generated, request, rng)
        generated = np.concatenate((generated, input_ids), axis=-1)
        if int(input_ids[0, 0]) == CHATTERBOX_ONNX_STOP_TOKEN:
            ended = True
            break
        attention_mask = np.concatenate(
            [attention_mask, np.ones((attention_mask.shape[0], 1), dtype=np.int64)],
            axis=1,
        )
        position_ids = position_ids[:, -1:] + 1
        for offset, key in enumerate(past_key_values):
            past_key_values[key] = present[offset]

    speech_tokens = generated[:, 1:-1] if ended else generated[:, 1:]
    silence = np.full(
        (speech_tokens.shape[0], 3),
        CHATTERBOX_ONNX_SILENCE_TOKEN,
        dtype=np.int64,
    )
    speech_tokens = np.concatenate([prompt_token, speech_tokens, silence], axis=1)
    wav = sessions["decoder"].run(None, {
        "speech_tokens": speech_tokens,
        "speaker_embeddings": speaker_embeddings,
        "speaker_features": speaker_features,
    })[0]
    return np.asarray(wav).squeeze(axis=0).astype(np.float32, copy=False)


def _chatterbox_onnx_generate(
    request: dict[str, Any],
    runtime: dict[str, Any],
    output: Path,
    condition_cache: dict[str, Any] | None = None,
) -> int:
    import numpy as np
    import soundfile as sf

    cache = condition_cache if condition_cache is not None else {}
    default_pause = _clamp_float(request.get("pause_seconds"), 0.35, 0.05, 3.0)
    parts = _chatterbox_pause_parts(str(request["text"]), default_pause)
    rendered: list[Any] = []
    for kind, value in parts:
        if kind == "pause":
            rendered.append(np.zeros(max(1, round(float(value) * CHATTERBOX_ONNX_SAMPLE_RATE)), dtype=np.float32))
        else:
            spoken = str(value).strip()
            if spoken:
                rendered.append(_chatterbox_onnx_generate_text(request, runtime, spoken, cache))
    if not rendered:
        raise RuntimeError("Chatterbox ONNX returned no audio")
    sf.write(str(output), np.concatenate(rendered), CHATTERBOX_ONNX_SAMPLE_RATE)
    return CHATTERBOX_ONNX_SAMPLE_RATE


OMNIVOICE_EXPRESSIVE_PRESETS = {
    "neutral": "",
    "amused": "[laughter]",
    "laughter": "[laughter]",
    "sigh": "[sigh]",
    "surprised": "[surprise-ah]",
    "surprise": "[surprise-ah]",
    "dissatisfied": "[dissatisfaction-hnn]",
    "question": "[question-en]",
    "confirmation": "[confirmation-en]",
}
OMNIVOICE_ALLOWED_TAGS = {
    "[laughter]", "[sigh]", "[confirmation-en]", "[question-en]",
    "[question-ah]", "[question-oh]", "[question-ei]", "[question-yi]",
    "[surprise-ah]", "[surprise-oh]", "[surprise-wa]", "[surprise-yo]",
    "[dissatisfaction-hnn]",
}


def _load_omnivoice(model_root: Path) -> Any:
    # Transformers v5 materializes checkpoint tensors asynchronously by default.
    # On Windows + CUDA this can crash inside torch.storage while worker threads
    # move safetensor slices to the GPU (0xC0000005). OmniVoice is small enough
    # that sequential materialization is the safer production path.
    if os.name == "nt":
        os.environ["HF_DEACTIVATE_ASYNC_LOAD"] = "1"
        os.environ["HF_ENABLE_PARALLEL_LOADING"] = "false"

    import torch
    from omnivoice import OmniVoice

    device = _device()
    model_dir = model_root / "model"
    if not model_dir.is_dir():
        raise RuntimeError(f"OmniVoice model directory is missing: {model_dir}")
    if os.name == "nt":
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("MKL_NUM_THREADS", "1")
        torch.set_num_threads(1)
        torch.backends.mkldnn.enabled = False
        model = OmniVoice.from_pretrained(
            str(model_dir),
            dtype=torch.float16 if device == "cuda" else torch.float32,
            load_asr=False,
            low_cpu_mem_usage=False,
        )
        # Preserve native dtypes for tokenizer/audio preprocessing submodules.
        # The actual model weights were already requested as FP16 above.
        return model.to("cuda:0") if device == "cuda" else model
    return OmniVoice.from_pretrained(
        str(model_dir),
        device_map="cuda:0" if device == "cuda" else "cpu",
        dtype=torch.float16 if device == "cuda" else torch.float32,
        load_asr=False,
    )


def _omnivoice_text(request: dict[str, Any]) -> str:
    text = str(request.get("text") or "").strip()
    explicit = str(request.get("expressive_tag") or "").strip()
    if explicit:
        tag = explicit if explicit.startswith("[") else f"[{explicit}]"
        if tag not in OMNIVOICE_ALLOWED_TAGS:
            raise ValueError(f"Unsupported OmniVoice expressive tag: {tag}")
    else:
        preset = str(
            request.get("expressive_preset")
            or request.get("emotion")
            or "neutral"
        ).strip().lower()
        tag = OMNIVOICE_EXPRESSIVE_PRESETS.get(preset, "")
    if tag and not text.startswith(tag):
        return f"{tag} {text}"
    return text


def _omnivoice_normalize_text(request: dict[str, Any], language: str) -> bool:
    """Enable OmniVoice normalization only when its optional backend exists.

    OmniVoice uses num2words for most languages, but English and Chinese require
    the optional WeTextProcessing/Pynini stack. Pynini has no dependable native
    Windows wheel, so a missing optional extra must never abort voice synthesis.
    """
    requested = request.get("normalize_text")
    if requested is False:
        return False
    if language not in {"en", "zh"}:
        return True if requested is None else bool(requested)
    try:
        import importlib.util

        backend_ready = importlib.util.find_spec("tn") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        backend_ready = False
    return backend_ready and (True if requested is None else bool(requested))


def _omnivoice_prompt(
    request: dict[str, Any],
    model: Any,
    prompt_cache: dict[str, Any],
) -> Any:
    from omnivoice import VoiceClonePrompt

    sample = request.get("sample") or {}
    cache_value = str(sample.get("prompt_cache_path") or "").strip()
    reference, reference_text = _reference(request, required=True)
    if not reference_text.strip():
        raise ValueError(
            "OmniVoice requires the reference transcript in DubRoom. "
            "Transcribe the sample once so Whisper is not loaded inside this runtime."
        )

    key = cache_value or f"{reference}|{reference_text}"
    if key in prompt_cache:
        return prompt_cache[key]

    cache_path = Path(cache_value).resolve() if cache_value else None
    if cache_path and cache_path.is_file():
        try:
            prompt = VoiceClonePrompt.load(str(cache_path))
            prompt_cache[key] = prompt
            return prompt
        except Exception:
            # A profile may previously contain another engine's .pt cache.
            cache_path.unlink(missing_ok=True)

    prompt = model.create_voice_clone_prompt(
        ref_audio=reference,
        ref_text=reference_text,
        preprocess_prompt=bool(request.get("preprocess_prompt", True)),
    )
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        prompt.save(str(cache_path))
    prompt_cache[key] = prompt
    return prompt


# PATCH044_ALLOW_12_STEPS
def _omnivoice_generate(
    request: dict[str, Any],
    model: Any,
    output: Path,
    mode: str,
    prompt_cache: dict[str, Any],
) -> int:
    import soundfile as sf
    import torch

    seed = request.get("seed")
    if seed is not None:
        torch.manual_seed(int(seed))
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(int(seed))

    language = str(request.get("language") or "fr").lower().split("-", 1)[0]
    # PATCH041B_AUDIO_START_GUARD_ROBUST_FIX
    # None means use the engine default; explicit 0.0 must stay 0.0.
    audio_start_guard = bool(request.get("audio_start_guard", False))
    postprocess_value = request.get("postprocess_output")
    pad_value = request.get("pad_duration")
    fade_value = request.get("fade_duration")
    postprocess_default = False if audio_start_guard else True
    pad_default = 0.15 if audio_start_guard else 0.1
    fade_default = 0.0 if audio_start_guard else 0.1
    kwargs: dict[str, Any] = {
        "text": _omnivoice_text(request),
        "language": language,
        "num_step": max(
            12,
            min(64, int(request.get("omnivoice_steps") or request.get("num_step") or 12)),
        ),
        "guidance_scale": float(request.get("guidance_scale") or 2.0),
        "denoise": bool(request.get("denoise", True)),
        "t_shift": float(request.get("t_shift") or 0.1),
        "position_temperature": float(request.get("position_temperature") or 5.0),
        "class_temperature": float(request.get("class_temperature") or 0.0),
        "layer_penalty_factor": float(request.get("layer_penalty_factor") or 5.0),
        "speed": max(0.5, min(2.0, float(request.get("speed") or 1.0))),
        "normalize_text": _omnivoice_normalize_text(request, language),
        "postprocess_output": bool(postprocess_default if postprocess_value is None else postprocess_value),
        "pad_duration": max(0.0, min(1.0, float(pad_default if pad_value is None else pad_value))),
        "fade_duration": max(0.0, min(0.5, float(fade_default if fade_value is None else fade_value))),
    }

    duration = request.get("duration")
    if duration is not None:
        try:
            duration_value = float(duration)
            if duration_value > 0:
                kwargs["duration"] = duration_value
        except (TypeError, ValueError):
            pass

    if mode == "design":
        instruct = str(request.get("design_prompt") or request.get("instruct") or "").strip()
        if not instruct:
            raise ValueError("OmniVoice Voice Design requires a design prompt")
        kwargs["instruct"] = instruct
    elif request.get("sample") or mode == "clone":
        kwargs["voice_clone_prompt"] = _omnivoice_prompt(request, model, prompt_cache)

    audio = model.generate(**kwargs)
    if not audio:
        raise RuntimeError("OmniVoice returned no audio")
    sample_rate = int(getattr(model, "sampling_rate", None) or 24000)
    sf.write(str(output), audio[0], sample_rate)
    return sample_rate


def _omnivoice(
    request: dict[str, Any],
    model_root: Path,
    output: Path,
    mode: str,
) -> int:
    model = _load_omnivoice(model_root)
    return _omnivoice_generate(request, model, output, mode, {})


def _load_chatterbox(model_root: Path, mode: str) -> Any:
    if mode.startswith("turbo_onnx_"):
        return _load_chatterbox_onnx(model_root, mode)

    import torch

    device = _device()
    if device == "cuda":
        torch.set_grad_enabled(False)
        torch.set_float32_matmul_precision("high")
        torch.backends.cuda.matmul.allow_tf32 = True
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cudnn.benchmark = True

    local = model_root / "model"
    if mode in {"turbo", "nano"}:
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        return ChatterboxTurboTTS.from_local(
            local,
            device=device,
            nano=mode == "nano",
        )

    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    # Chatterbox Multilingual V3 support was added after some PyPI builds.
    # New builds accept t3_model="v3" directly. Older builds hard-code the
    # legacy V2 filename, so expose the downloaded V3 checkpoint through a
    # temporary NTFS hard link without copying another ~2 GB file.
    from_local_parameters = inspect.signature(
        ChatterboxMultilingualTTS.from_local
    ).parameters
    if "t3_model" in from_local_parameters:
        return ChatterboxMultilingualTTS.from_local(
            local,
            device=device,
            t3_model="v3",
        )

    v3_checkpoint = local / "t3_mtl23ls_v3.safetensors"
    legacy_checkpoint = local / "t3_mtl23ls_v2.safetensors"
    if not v3_checkpoint.is_file():
        raise FileNotFoundError(
            f"Chatterbox Multilingual V3 checkpoint is missing: {v3_checkpoint}"
        )

    created_legacy_alias = False
    if not legacy_checkpoint.exists():
        try:
            os.link(v3_checkpoint, legacy_checkpoint)
            created_legacy_alias = True
        except OSError as exc:
            raise RuntimeError(
                "The installed chatterbox-tts package is too old for Multilingual V3 "
                "and DubRoom could not create a zero-copy compatibility link. "
                "Upgrade chatterbox-tts from the official GitHub repository."
            ) from exc

    try:
        return ChatterboxMultilingualTTS.from_local(
            local,
            device=device,
        )
    finally:
        if created_legacy_alias:
            legacy_checkpoint.unlink(missing_ok=True)


def _chatterbox_condition_key(
    request: dict[str, Any],
    mode: str,
) -> tuple[str | None, float, bool]:
    reference, _ = _reference(request)
    if mode in {"turbo", "nano"}:
        exaggeration = 0.0
        normalize = bool(request.get("norm_loudness", True))
    else:
        exaggeration = _clamp_float(request.get("exaggeration"), 0.5, 0.0, 2.0)
        normalize = False
    resolved = str(Path(reference).resolve()) if reference else None
    return resolved, exaggeration, normalize


def _prepare_chatterbox_voice(
    request: dict[str, Any],
    model: Any,
    mode: str,
    condition_cache: dict[tuple[str, float, bool], Any],
) -> None:
    reference, exaggeration, normalize = _chatterbox_condition_key(request, mode)
    if reference is None:
        if getattr(model, "conds", None) is None:
            raise ValueError(
                "Chatterbox requires a voice reference of at least five seconds"
            )
        return

    key = (reference, exaggeration, normalize)
    cached = condition_cache.get(key)
    if cached is not None:
        model.conds = cached
        return

    if mode in {"turbo", "nano"}:
        model.prepare_conditionals(
            reference,
            exaggeration=0.0,
            norm_loudness=normalize,
        )
    else:
        model.prepare_conditionals(reference, exaggeration=exaggeration)
    condition_cache[key] = model.conds
    _emit({
        "event": "chatterbox_voice_conditioned",
        "reference": reference,
        "cached_profiles": len(condition_cache),
    })


def _chatterbox_generate_segment(
    request: dict[str, Any],
    model: Any,
    mode: str,
    text: str,
) -> Any:
    common = {
        "temperature": _clamp_float(request.get("temperature"), 0.8, 0.05, 2.0),
        "top_p": _clamp_float(
            request.get("top_p"),
            0.95 if mode in {"turbo", "nano"} else 1.0,
            0.0,
            1.0,
        ),
        "min_p": _clamp_float(
            request.get("min_p"),
            0.0 if mode in {"turbo", "nano"} else 0.05,
            0.0,
            1.0,
        ),
        "repetition_penalty": _clamp_float(
            request.get("repetition_penalty"), 1.2, 1.0, 2.0
        ),
    }
    if mode in {"turbo", "nano"}:
        language = str(request.get("language") or "en").lower().split("-", 1)[0]
        if language != "en":
            raise ValueError("Chatterbox Turbo and Nano support English only")
        return model.generate(
            text,
            **common,
            top_k=max(0, min(1000, int(request.get("top_k") or 1000))),
            norm_loudness=bool(request.get("norm_loudness", True)),
        )

    language = str(request.get("language") or "en").lower().split("-", 1)[0]
    text = _strip_chatterbox_event_tags(text)
    if not text:
        raise ValueError("The multilingual Chatterbox line is empty after removing unsupported event tags")
    return model.generate(
        text,
        language_id=language,
        exaggeration=_clamp_float(request.get("exaggeration"), 0.5, 0.0, 2.0),
        cfg_weight=_clamp_float(request.get("cfg_weight"), 0.5, 0.0, 1.0),
        **common,
    )


def _chatterbox_generate(
    request: dict[str, Any],
    model: Any,
    output: Path,
    mode: str,
    condition_cache: dict[Any, Any] | None = None,
) -> int:
    if mode.startswith("turbo_onnx_"):
        return _chatterbox_onnx_generate(request, model, output, condition_cache)

    import torch

    _set_seed(request.get("seed"))
    cache = condition_cache if condition_cache is not None else {}
    _prepare_chatterbox_voice(request, model, mode, cache)

    default_pause = _clamp_float(request.get("pause_seconds"), 0.35, 0.05, 3.0)
    parts = _chatterbox_pause_parts(str(request["text"]), default_pause)
    rendered: list[Any] = []
    with torch.inference_mode():
        for kind, value in parts:
            if kind == "pause":
                rendered.append(float(value))
                continue
            spoken = str(value).strip()
            if spoken:
                wav = _chatterbox_generate_segment(request, model, mode, spoken)
                if getattr(wav, "dim", lambda: 0)() == 1:
                    wav = wav.unsqueeze(0)
                rendered.append(wav)

    first_wav = next((item for item in rendered if torch.is_tensor(item)), None)
    if first_wav is None:
        total_seconds = sum(float(item) for item in rendered)
        first_wav = torch.zeros((1, max(1, round(total_seconds * int(model.sr)))))
        rendered = [first_wav]

    audio_parts = []
    for item in rendered:
        if torch.is_tensor(item):
            audio_parts.append(item)
        else:
            frames = max(1, round(float(item) * int(model.sr)))
            audio_parts.append(
                torch.zeros(
                    (first_wav.shape[0], frames),
                    dtype=first_wav.dtype,
                    device=first_wav.device,
                )
            )
    wav = torch.cat(audio_parts, dim=-1)
    _save_torch_audio(wav, output, int(model.sr))
    return int(model.sr)


def _chatterbox(request: dict[str, Any], model_root: Path, output: Path, mode: str) -> int:
    model = _load_chatterbox(model_root, mode)
    return _chatterbox_generate(request, model, output, mode, {})


def _tada(request: dict[str, Any], model_root: Path, output: Path) -> int:
    import torch
    import torchaudio
    from tada.modules.encoder import Encoder
    from tada.modules.tada import InferenceOptions, TadaForCausalLM

    reference, reference_text = _reference(request, required=True)
    device = _device()
    if device != "cuda":
        raise RuntimeError("TADA generation requires CUDA in DubRoom Studio")
    language = str(request.get("language") or "en").lower().split("-", 1)[0]
    language_code = TADA_LANGUAGE_CODES.get(language)
    encoder = Encoder.from_pretrained(
        str(model_root / "codec"),
        subfolder="encoder",
        language=language_code,
    ).to(device)
    model = TadaForCausalLM.from_pretrained(
        str(model_root / "model"),
        torch_dtype=torch.bfloat16,
    ).to(device)
    source, sample_rate = torchaudio.load(reference)
    source = source.mean(dim=0, keepdim=True).to(device)
    prompt = encoder(
        source,
        text=[reference_text] if reference_text else None,
        sample_rate=sample_rate,
    )
    result = model.generate(
        prompt=prompt,
        text=request["text"],
        inference_options=InferenceOptions(
            num_flow_matching_steps=max(5, min(20, int(request.get("quality_steps") or 10))),
            speed_up_factor=float(request.get("speed_up_factor")) if request.get("speed_up_factor") else None,
        ),
        system_prompt=str(request.get("instruct") or ""),
    )
    wav = result.audio[0].detach().cpu().float()
    _save_torch_audio(wav, output, 24000)
    return 24000


def main() -> None:
    parser = argparse.ArgumentParser(description="DubRoom native TTS worker")
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    request = _request(args.request)
    family = str(request["family"])
    variant = str(request.get("variant") or "")
    model_root = Path(request["model_root"]).resolve()
    output = Path(request["output_path"]).resolve()

    # PATCH044_PERSISTENT_OMNIVOICE
    if family == "omnivoice" and os.environ.get("DUBROOM_OMNIVOICE_DAEMON_CHILD") != "1":
        from omnivoice_persistent_proxy import submit_request
        proxied = submit_request(request)
        for event in proxied.pop("_events", []):
            print(json.dumps(event, ensure_ascii=False), flush=True)
        print(json.dumps(proxied, ensure_ascii=False), flush=True)
        return
    output.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(request.get("items"), list):
        results = _run_batch(request, model_root, family, variant)
        _emit(
            {
                "status": "completed",
                "batch": True,
                "completed": sum(item["status"] == "completed" for item in results),
                "failed": sum(item["status"] == "failed" for item in results),
                "results": results,
            }
        )
        return

    if family == "supertonic":
        sample_rate = _supertonic(request, model_root, output)
    elif family == "kokoro":
        sample_rate = _kokoro(request, model_root, output)
    elif family == "luxtts":
        sample_rate = _luxtts(request, model_root, output)
    elif family == "qwen3":
        sample_rate = _qwen(request, model_root, output, variant)
    elif family == "omnivoice":
        sample_rate = _omnivoice(request, model_root, output, variant)
    elif family == "chatterbox":
        sample_rate = _chatterbox(request, model_root, output, variant)
    elif family == "kyutai_pocket":
        sample_rate = _kyutai_pocket(request, model_root, output, variant)
    elif family == "cosyvoice3_gguf":
        sample_rate = _cosyvoice3_gguf(request, model_root, output)
    elif family == "tada":
        sample_rate = _tada(request, model_root, output)
    else:
        raise ValueError(f"Unsupported TTS family: {family}")

    if not output.is_file() or output.stat().st_size < 44:
        raise RuntimeError("The TTS engine did not produce a valid WAV file")
    print(json.dumps({
        "status": "completed",
        "output_path": str(output),
        "sample_rate": sample_rate,
        "duration": _duration(output),
    }))


if __name__ == "__main__":
    main()
