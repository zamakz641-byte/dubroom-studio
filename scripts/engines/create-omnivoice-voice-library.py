#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
DubRoom - OmniVoice Voice Library Builder

Recommended location inside the project:
  scripts/engines/create-omnivoice-voice-library.py

Run with DubRoom's existing OmniVoice environment:
  data\environments\tts-omnivoice-hq\venv\Scripts\python.exe ^
      scripts\engines\create-omnivoice-voice-library.py

What it does for each profile:
  1) Voice Design -> reference.wav
  2) reference.wav -> persistent VoiceClonePrompt -> prompt.pt
  3) Generate neutral EN + neutral FR smoke tests
  4) Generate official OmniVoice expressive-control tests
  5) Save profile.json and global voice_catalog.json

IMPORTANT:
- Voice Design uses ONLY documented attributes: gender, age, pitch.
- "cold", "angry", "wise", etc. are catalog metadata for GPT matching.
- Expressive tests use ONLY official OmniVoice inline tags.
"""

from __future__ import annotations

import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch

try:
    from omnivoice import OmniVoice, VoiceClonePrompt
except Exception as exc:
    print(
        "ERROR: OmniVoice is not importable.\n"
        "Run this script with DubRoom's tts-omnivoice-hq Python environment.\n"
        f"Original error: {exc}",
        file=sys.stderr,
    )
    raise


LOG = logging.getLogger("dubroom.voice_library")

SAMPLE_RATE = 24000

# These are the ACTUAL inline controls currently documented by OmniVoice.
OFFICIAL_TAGS = {
    "laughter": "[laughter]",
    "sigh": "[sigh]",
    "confirmation_en": "[confirmation-en]",
    "question_en": "[question-en]",
    "question_ah": "[question-ah]",
    "question_oh": "[question-oh]",
    "question_ei": "[question-ei]",
    "question_yi": "[question-yi]",
    "surprise_ah": "[surprise-ah]",
    "surprise_oh": "[surprise-oh]",
    "surprise_wa": "[surprise-wa]",
    "surprise_yo": "[surprise-yo]",
    "dissatisfaction_hnn": "[dissatisfaction-hnn]",
}

# Short suite: enough to quickly judge whether a voice is usable.
CORE_TESTS = {
    "neutral_en": "You came all this way just to challenge me. Then show me what you can do.",
    "neutral_fr": "Tu es venu jusqu'ici pour me défier. Alors montre-moi ce que tu sais faire.",
    "laughter": "[laughter] You really thought that would stop me?",
    "sigh": "[sigh] I knew this would happen eventually.",
    "question_en": "[question-en] You really think you can defeat me?",
    "surprise_ah": "[surprise-ah] What just happened?",
    "surprise_oh": "[surprise-oh] So that's what you were hiding.",
    "dissatisfaction_hnn": "[dissatisfaction-hnn] That's all you've got?",
}

# Complete documented tag suite.
FULL_TESTS = {
    **CORE_TESTS,
    "confirmation_en": "[confirmation-en] That's exactly what I expected.",
    "question_ah": "[question-ah] Is that really your final answer?",
    "question_oh": "[question-oh] So you knew about this already?",
    "question_ei": "[question-ei] You expect me to believe that?",
    "question_yi": "[question-yi] You were the one who did this?",
    "surprise_wa": "[surprise-wa] That power is incredible!",
    "surprise_yo": "[surprise-yo] You were here the whole time?",
}

def project_root_from_script() -> Path:
    """
    When installed in scripts/engines/, parents[2] is the DubRoom project root.
    When run elsewhere, fall back to current working directory.
    """
    p = Path(__file__).resolve()
    try:
        candidate = p.parents[2]
        if (candidate / "data").exists() or (candidate / "scripts").exists():
            return candidate
    except IndexError:
        pass
    return Path.cwd()

def default_config_path() -> Path:
    local = Path(__file__).resolve().with_name("omnivoice-voice-library.json")
    if local.exists():
        return local
    root = project_root_from_script()
    candidate = root / "scripts" / "engines" / "omnivoice-voice-library.json"
    if candidate.exists():
        return candidate
    return Path.cwd() / "omnivoice-voice-library.json"

def default_library_root() -> Path:
    return project_root_from_script() / "data" / "voice-library" / "omnivoice"

def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def save_wav(path: Path, audio: Any, sr: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(audio, (list, tuple)):
        if not audio:
            raise RuntimeError("OmniVoice returned an empty audio list.")
        audio = audio[0]
    if torch.is_tensor(audio):
        audio = audio.detach().float().cpu().numpy()
    audio = np.asarray(audio).squeeze()
    if audio.size == 0:
        raise RuntimeError("OmniVoice returned empty audio.")
    sf.write(str(path), audio, sr)


def _weight_bytes(folder: Path) -> int:
    total = 0
    for pattern in ("*.safetensors", "*.bin", "*.pt", "*.pth", "*.ckpt"):
        try:
            for path in folder.rglob(pattern):
                try:
                    total += path.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass
    return total


def _looks_like_model_folder(folder: Path) -> bool:
    try:
        if not folder.is_dir():
            return False
        if not (
            (folder / "config.json").exists()
            or (folder / "model_index.json").exists()
        ):
            return False
        return _weight_bytes(folder) >= 500 * 1024 * 1024
    except OSError:
        return False


def _hf_snapshot_dirs(cache_root: Path) -> list[Path]:
    repository = cache_root / "models--k2-fsa--OmniVoice" / "snapshots"
    if not repository.is_dir():
        return []
    try:
        return [
            path
            for path in repository.iterdir()
            if path.is_dir() and _looks_like_model_folder(path)
        ]
    except OSError:
        return []


def discover_local_model(
    project_root: Path,
    explicit: str | None = None,
) -> list[Path]:
    candidates: list[Path] = []
    seen: set[str] = set()

    def add(value: str | Path | None) -> None:
        if not value:
            return
        try:
            path = Path(value).expanduser().resolve()
        except (OSError, RuntimeError):
            return
        key = str(path).lower()
        if key in seen:
            return
        seen.add(key)
        if _looks_like_model_folder(path):
            candidates.append(path)

    add(explicit)
    if candidates:
        return candidates
    hub_cache = os.environ.get("HF_HUB_CACHE")
    hf_home = os.environ.get("HF_HOME")
    transformers_cache = os.environ.get("TRANSFORMERS_CACHE")
    if hub_cache:
        for path in _hf_snapshot_dirs(Path(hub_cache)):
            add(path)
    if hf_home:
        for path in _hf_snapshot_dirs(Path(hf_home) / "hub"):
            add(path)
    if transformers_cache:
        for path in _hf_snapshot_dirs(Path(transformers_cache)):
            add(path)

    standard_roots = [Path.home() / ".cache" / "huggingface" / "hub"]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        standard_roots.append(Path(local_app_data) / "huggingface" / "hub")
    for root in standard_roots:
        for path in _hf_snapshot_dirs(root):
            add(path)

    for root in (project_root / "models", project_root / "data"):
        if not root.exists():
            continue
        try:
            for repository in root.rglob("models--k2-fsa--OmniVoice"):
                snapshots = repository / "snapshots"
                if snapshots.is_dir():
                    for path in snapshots.iterdir():
                        add(path)
            for path in root.rglob("*"):
                if not path.is_dir() or "voice-library" in str(path).lower():
                    continue
                if "omnivoice" in path.name.lower():
                    add(path)
        except OSError:
            pass

    candidates.sort(key=_weight_bytes, reverse=True)
    return candidates


def load_omnivoice_local_only(
    project_root: Path,
    device: str,
    dtype: torch.dtype,
    explicit_model_path: str | None = None,
) -> tuple[OmniVoice, Path]:
    candidates = discover_local_model(project_root, explicit_model_path)
    if not candidates:
        raise RuntimeError(
            "No complete local OmniVoice model was found. No download was attempted. "
            "DubRoom checked its models/data folders and the existing Hugging Face caches."
        )
    LOG.info("LOCAL ONLY enabled: network downloads are disabled.")
    errors: list[str] = []
    for index, path in enumerate(candidates, start=1):
        LOG.info(
            "Local candidate %d: %s (%.2f GB)",
            index,
            path,
            _weight_bytes(path) / (1024**3),
        )
        try:
            placement = "auto" if os.environ.get("OMNIVOICE_AUTO_OFFLOAD") == "1" else device
            model = OmniVoice.from_pretrained(
                str(path),
                device_map=placement,
                dtype=dtype,
                load_asr=False,
            )
            return model, path
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            LOG.warning("Local OmniVoice candidate failed: %s", path)
    raise RuntimeError(
        "Local OmniVoice files were found but none could be loaded. "
        "No download was attempted.\n" + "\n".join(errors[:5])
    )

def select_device(requested: str) -> tuple[str, torch.dtype]:
    if requested != "auto":
        if requested.startswith("cuda"):
            return requested, torch.float16
        return requested, torch.float32

    if torch.cuda.is_available():
        return "cuda:0", torch.float16

    # Windows target is NVIDIA; CPU fallback keeps script debuggable.
    return "cpu", torch.float32

def design_instruct(profile: dict[str, Any]) -> str:
    # ONLY documented Voice Design categories.
    parts = [
        profile.get("gender"),
        profile.get("age"),
        profile.get("pitch"),
    ]
    if profile.get("style"):
        parts.append(profile["style"])
    if profile.get("accent"):
        parts.append(profile["accent"])
    return ", ".join(str(x) for x in parts if x)

def save_prompt(prompt: Any, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)

    # OmniVoice >= 0.2.1
    if hasattr(prompt, "save") and callable(prompt.save):
        prompt.save(str(path))
        return "VoiceClonePrompt.save"

    # Compatibility fallback for older installed versions.
    torch.save(prompt, str(path))
    return "torch.save_fallback"

def load_prompt(path: Path) -> Any:
    if hasattr(VoiceClonePrompt, "load") and callable(getattr(VoiceClonePrompt, "load")):
        return VoiceClonePrompt.load(str(path))

    # Torch 2.6+ defaults to weights_only=True, which is unsuitable for this object.
    try:
        return torch.load(str(path), map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(str(path), map_location="cpu")

def generate(model: OmniVoice, *, text: str, num_step: int, prompt: Any | None = None,
             instruct: str | None = None, speed: float = 1.0) -> Any:
    kwargs: dict[str, Any] = {
        "text": text,
        "num_step": num_step,
        "speed": speed,
        # English/Chinese normalization is an optional WeTextProcessing extra.
        # Library prompts contain no numeric tokens, so disabling it is both
        # deterministic and portable on Windows.
        "normalize_text": False,
    }
    if prompt is not None:
        kwargs["voice_clone_prompt"] = prompt
    if instruct is not None:
        kwargs["instruct"] = instruct
    return model.generate(**kwargs)

def build_profile(
    model: OmniVoice,
    profile: dict[str, Any],
    *,
    library_root: Path,
    reference_text: str,
    num_step: int,
    full_tests: bool,
    regenerate: bool,
    tests_only: bool,
) -> dict[str, Any]:
    voice_id = profile["id"]
    voice_dir = library_root / "voices" / voice_id
    tests_dir = voice_dir / "tests"
    voice_dir.mkdir(parents=True, exist_ok=True)
    tests_dir.mkdir(parents=True, exist_ok=True)

    ref_path = voice_dir / "reference.wav"
    prompt_path = voice_dir / "prompt.pt"
    profile_path = voice_dir / "profile.json"

    instruct = design_instruct(profile)

    LOG.info("[%s] %s", voice_id, profile.get("name", voice_id))
    LOG.info("[%s] Voice Design instruct: %s", voice_id, instruct)

    if regenerate and not tests_only:
        for p in (ref_path, prompt_path):
            if p.exists():
                p.unlink()

    if tests_only and not prompt_path.exists():
        raise RuntimeError(
            f"{voice_id}: --tests-only requested but {prompt_path} does not exist."
        )

    # STEP 1: Voice Design -> stable reference audio.
    if not tests_only and not ref_path.exists():
        LOG.info("[%s] Creating designed reference...", voice_id)
        t0 = time.perf_counter()
        audio = generate(
            model,
            text=reference_text,
            instruct=instruct,
            num_step=num_step,
        )
        save_wav(ref_path, audio)
        LOG.info("[%s] reference.wav ready in %.2fs", voice_id, time.perf_counter() - t0)
    else:
        LOG.info("[%s] Reusing reference.wav", voice_id)

    # STEP 2: reference -> persistent clone prompt.
    if not prompt_path.exists():
        LOG.info("[%s] Encoding persistent VoiceClonePrompt...", voice_id)
        prompt = model.create_voice_clone_prompt(
            ref_audio=str(ref_path),
            ref_text=reference_text,
        )
        save_method = save_prompt(prompt, prompt_path)
        LOG.info("[%s] prompt.pt ready (%s)", voice_id, save_method)
    else:
        LOG.info("[%s] Reusing prompt.pt", voice_id)
        prompt = load_prompt(prompt_path)
        save_method = "existing"

    # STEP 3: official expression tests.
    tests = FULL_TESTS if full_tests else CORE_TESTS
    test_results: dict[str, Any] = {}

    for test_id, text in tests.items():
        wav_path = tests_dir / f"{test_id}.wav"
        if wav_path.exists() and not regenerate:
            test_results[test_id] = {
                "path": str(wav_path.relative_to(library_root)),
                "text": text,
                "status": "cached",
            }
            continue

        LOG.info("[%s] Test: %s", voice_id, test_id)
        t0 = time.perf_counter()
        try:
            audio = generate(
                model,
                text=text,
                prompt=prompt,
                num_step=num_step,
            )
            save_wav(wav_path, audio)
            status = "generated"
            err = None
        except Exception as exc:
            LOG.exception("[%s] Test failed: %s", voice_id, test_id)
            status = "failed"
            err = str(exc)

        test_results[test_id] = {
            "path": str(wav_path.relative_to(library_root)),
            "text": text,
            "status": status,
            "error": err,
            "generation_seconds": round(time.perf_counter() - t0, 3),
        }

    payload = {
        **profile,
        "engine": "omnivoice",
        "model": "k2-fsa/OmniVoice",
        "voice_design_instruct": instruct,
        "reference_text": reference_text,
        "reference_path": str(ref_path.relative_to(library_root)),
        "prompt_path": str(prompt_path.relative_to(library_root)),
        "prompt_save_method": save_method,
        "num_step": num_step,
        "sample_rate": SAMPLE_RATE,
        "locked": False,
        "enabled": True,
        "tests": test_results,
        "official_expressive_controls": list(OFFICIAL_TAGS.values()),
    }
    write_json(profile_path, payload)
    return payload

def build_catalog(library_root: Path, results: list[dict[str, Any]]) -> None:
    catalog = {
        "version": 1,
        "engine": "omnivoice",
        "sample_rate": SAMPLE_RATE,
        "description": (
            "Persistent OmniVoice voice library for DubRoom. "
            "Semantic traits and roles are intended for GPT/Voice Mapping. "
            "Voice Design instructions only use OmniVoice-supported attributes."
        ),
        "official_expressive_controls": OFFICIAL_TAGS,
        "voices": {
            r["id"]: {
                "id": r["id"],
                "name": r.get("name"),
                "gender": r.get("gender"),
                "age": r.get("age"),
                "pitch": r.get("pitch"),
                "traits": r.get("traits", []),
                "roles": r.get("roles", []),
                "reference_path": r["reference_path"],
                "prompt_path": r["prompt_path"],
                "enabled": r.get("enabled", True),
                "locked": r.get("locked", False),
            }
            for r in results
        },
    }
    write_json(library_root / "voice_catalog.json", catalog)

def parse_ids(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {x.strip().upper() for x in value.split(",") if x.strip()}

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create DubRoom's persistent OmniVoice voice library."
    )
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--library-root", type=Path, default=default_library_root())
    parser.add_argument("--device", default="auto", help="auto, cuda:0, cpu, ...")
    parser.add_argument(
        "--model-path",
        default=None,
        help="Explicit local OmniVoice model path. Downloads remain disabled.",
    )
    parser.add_argument("--voices", help="Comma-separated IDs, e.g. M01,M02,F01")
    parser.add_argument("--full-tests", action="store_true",
                        help="Generate the complete documented OmniVoice tag test suite.")
    parser.add_argument("--regenerate", action="store_true",
                        help="Regenerate selected reference/prompt/tests.")
    parser.add_argument("--tests-only", action="store_true",
                        help="Do not Voice Design; regenerate tests from existing prompt.pt.")
    parser.add_argument("--list", action="store_true", help="List configured voices and exit.")
    parser.add_argument("--num-step", type=int, default=None,
                        help="Override config diffusion steps. Recommended quality setting: 32.")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    cfg = load_json(args.config)
    profiles = cfg["profiles"]

    if args.list:
        for p in profiles:
            print(
                f'{p["id"]:5s} | {p["name"]:24s} | '
                f'{p["gender"]:6s} | {p["age"]:12s} | {p["pitch"]}'
            )
        return 0

    selected = parse_ids(args.voices)
    if selected is not None:
        profiles = [p for p in profiles if p["id"].upper() in selected]
        missing = selected - {p["id"].upper() for p in profiles}
        if missing:
            raise SystemExit(f"Unknown voice IDs: {', '.join(sorted(missing))}")

    if not profiles:
        raise SystemExit("No voices selected.")

    device, dtype = select_device(args.device)
    num_step = int(args.num_step or cfg.get("num_step", 32))
    library_root = args.library_root.resolve()
    library_root.mkdir(parents=True, exist_ok=True)

    LOG.info("Config: %s", args.config.resolve())
    LOG.info("Library: %s", library_root)
    LOG.info("Device: %s | dtype=%s | num_step=%s", device, dtype, num_step)
    LOG.info("CUDA available: %s", torch.cuda.is_available())
    if torch.cuda.is_available():
        LOG.info("GPU: %s", torch.cuda.get_device_name(0))

    LOG.info("Loading OmniVoice once (LOCAL ONLY)...")
    model, resolved_model_path = load_omnivoice_local_only(
        project_root_from_script(),
        device,
        dtype,
        explicit_model_path=args.model_path,
    )
    LOG.info("Resolved local model path: %s", resolved_model_path)

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for index, profile in enumerate(profiles, start=1):
        LOG.info("==== Voice %d/%d: %s ====", index, len(profiles), profile["id"])
        try:
            result = build_profile(
                model,
                profile,
                library_root=library_root,
                reference_text=cfg["reference_text"],
                num_step=num_step,
                full_tests=args.full_tests,
                regenerate=args.regenerate,
                tests_only=args.tests_only,
            )
            results.append(result)
        except Exception as exc:
            LOG.exception("Voice %s failed", profile["id"])
            failures.append({"id": profile["id"], "error": str(exc)})

    # Keep existing catalog entries when only a subset was rebuilt.
    existing_catalog_path = library_root / "voice_catalog.json"
    if existing_catalog_path.exists():
        try:
            existing = load_json(existing_catalog_path)
            existing_voices = existing.get("voices", {})
        except Exception:
            existing_voices = {}
    else:
        existing_voices = {}

    # Convert rebuilt results to catalog records and merge.
    rebuilt = {}
    for r in results:
        rebuilt[r["id"]] = {
            "id": r["id"],
            "name": r.get("name"),
            "gender": r.get("gender"),
            "age": r.get("age"),
            "pitch": r.get("pitch"),
            "traits": r.get("traits", []),
            "roles": r.get("roles", []),
            "reference_path": r["reference_path"],
            "prompt_path": r["prompt_path"],
            "enabled": r.get("enabled", True),
            "locked": r.get("locked", False),
        }

    merged_voices = {**existing_voices, **rebuilt}
    write_json(
        existing_catalog_path,
        {
            "version": 1,
            "engine": "omnivoice",
            "sample_rate": SAMPLE_RATE,
            "official_expressive_controls": OFFICIAL_TAGS,
            "voices": merged_voices,
            "last_build_failures": failures,
        },
    )

    summary = {
        "ok": len(failures) == 0,
        "generated": [r["id"] for r in results],
        "failed": failures,
        "library_root": str(library_root),
        "catalog": str(existing_catalog_path),
        "full_tests": args.full_tests,
        "num_step": num_step,
        "device": device,
    }
    write_json(library_root / "last_build.json", summary)

    print("\n" + "=" * 72)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("=" * 72)

    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
