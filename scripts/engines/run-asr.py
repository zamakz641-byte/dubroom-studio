from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from services.api.app.segmentation import resegment_for_dubbing


_DLL_DIRECTORY_HANDLES: list[Any] = []
_PRELOADED_DLLS: list[Any] = []


def _deduplicate_paths(paths: list[Path]) -> list[Path]:
    """Return existing directories once, preserving their priority order."""
    result: list[Path] = []
    seen: set[str] = set()

    for raw_path in paths:
        try:
            path = raw_path.expanduser().resolve()
        except OSError:
            path = raw_path.expanduser()

        key = str(path).casefold()
        if key in seen or not path.is_dir():
            continue

        seen.add(key)
        result.append(path)

    return result


def _cuda_candidate_directories() -> list[Path]:
    """Find directories that may contain CUDA 12 runtime DLLs.

    DubRoom uses isolated Python environments. CUDA libraries can therefore be
    located in the active Whisper environment, another engine environment,
    PyTorch's shared runtime, a system CUDA Toolkit installation, or PATH.
    """
    workspace = WORKSPACE_ROOT
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    environments_root = workspace / "data" / "environments"

    candidates: list[Path] = [
        # Active Faster Whisper environment.
        site_packages / "nvidia" / "cublas" / "bin",
        site_packages / "nvidia" / "cudnn" / "bin",
        site_packages / "torch" / "lib",

        # Shared runtime historically used by DubRoom.
        environments_root
        / "rvc-runtime"
        / "venv"
        / "Lib"
        / "site-packages"
        / "torch"
        / "lib",
    ]

    # Search other isolated DubRoom runtimes without recursively scanning every
    # package file. This catches CUDA packages installed with TTS, RVC, ASR, etc.
    if environments_root.is_dir():
        patterns = (
            "*/venv/Lib/site-packages/nvidia/cublas/bin",
            "*/venv/Lib/site-packages/nvidia/cudnn/bin",
            "*/venv/Lib/site-packages/torch/lib",
        )
        for pattern in patterns:
            candidates.extend(environments_root.glob(pattern))

    # Explicit CUDA Toolkit locations.
    cuda_path = os.environ.get("CUDA_PATH")
    if cuda_path:
        candidates.append(Path(cuda_path) / "bin")

    program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    toolkit_root = program_files / "NVIDIA GPU Computing Toolkit" / "CUDA"
    if toolkit_root.is_dir():
        # Prefer the newest toolkit directory first.
        candidates.extend(
            sorted(
                (path / "bin" for path in toolkit_root.iterdir() if path.is_dir()),
                reverse=True,
            )
        )

    # Finally preserve useful directories already present in PATH.
    for item in os.environ.get("PATH", "").split(os.pathsep):
        item = item.strip().strip('"')
        if item:
            candidates.append(Path(item))

    return _deduplicate_paths(candidates)


def configure_nvidia_runtime() -> dict[str, Any]:
    """Expose and preload CUDA 12 DLLs required by CTranslate2 on Windows.

    Returns diagnostic information that is stored in the ASR output manifest.
    On non-Windows systems no special DLL handling is needed.
    """
    if os.name != "nt":
        return {
            "platform": os.name,
            "status": "not-required",
            "directories": [],
            "loaded": {},
        }

    candidate_dirs = _cuda_candidate_directories()
    required_dlls = (
        "cublasLt64_12.dll",
        "cublas64_12.dll",
    )
    optional_dlls = (
        "cudnn64_9.dll",
    )

    # Only keep directories containing at least one relevant CUDA DLL.
    cuda_dirs = [
        folder
        for folder in candidate_dirs
        if any(
            (folder / dll_name).is_file()
            for dll_name in (*required_dlls, *optional_dlls)
        )
    ]

    if cuda_dirs:
        current_path = os.environ.get("PATH", "")
        path_entries = [str(folder) for folder in cuda_dirs]
        os.environ["PATH"] = os.pathsep.join([*path_entries, current_path])

        # Python 3.8+ on Windows no longer searches PATH alone for dependent
        # DLLs. Keep the returned handles alive for the lifetime of the worker.
        for folder in cuda_dirs:
            try:
                _DLL_DIRECTORY_HANDLES.append(
                    os.add_dll_directory(str(folder))
                )
            except (AttributeError, FileNotFoundError, OSError):
                # The explicit WinDLL preload below still has a chance to work.
                pass

    loaded: dict[str, str] = {}
    load_errors: dict[str, str] = {}

    # cublas64_12 depends on cublasLt64_12, so load Lt first.
    for dll_name in (*required_dlls, *optional_dlls):
        located_path: Path | None = None
        for folder in cuda_dirs:
            candidate = folder / dll_name
            if candidate.is_file():
                located_path = candidate
                break

        if located_path is None:
            continue

        try:
            handle = ctypes.WinDLL(str(located_path))
            _PRELOADED_DLLS.append(handle)
            loaded[dll_name] = str(located_path)
        except OSError as exc:
            load_errors[dll_name] = f"{located_path}: {exc}"

    missing_required = [
        dll_name for dll_name in required_dlls if dll_name not in loaded
    ]

    diagnostics = {
        "platform": os.name,
        "status": "ready" if not missing_required else "missing-required-dll",
        "directories": [str(folder) for folder in cuda_dirs],
        "loaded": loaded,
        "load_errors": load_errors,
        "missing_required": missing_required,
    }

    if missing_required:
        searched = "\n".join(f"  - {folder}" for folder in candidate_dirs[:40])
        errors = "\n".join(
            f"  - {dll_name}: {message}"
            for dll_name, message in load_errors.items()
        )
        error_suffix = f"\nLoad errors:\n{errors}" if errors else ""
        raise RuntimeError(
            "CUDA transcription cannot start because the required CUDA 12 "
            f"libraries were not loaded: {', '.join(missing_required)}.\n"
            "Install or repair the Faster Whisper CUDA runtime, or ensure the "
            "NVIDIA cuBLAS 12 DLLs are available in a DubRoom environment.\n"
            f"Searched directories:\n{searched}{error_suffix}"
        )

    return diagnostics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--progress-file")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cpu")
    parser.add_argument("--language")
    return parser.parse_args()


def write_progress(
    args: argparse.Namespace,
    progress: int,
    message: str,
    **details: Any,
) -> None:
    if not args.progress_file:
        return

    progress_path = Path(args.progress_file)
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "progress": max(0, min(99, int(progress))),
        "message": message,
        "device": args.device,
        **details,
    }
    serialized = json.dumps(payload, ensure_ascii=False)

    # Progress is advisory: antivirus/indexer locks must never abort transcription.
    for attempt in range(3):
        try:
            progress_path.write_text(serialized, encoding="utf-8")
            return
        except OSError:
            if attempt < 2:
                time.sleep(0.05 * (attempt + 1))


def run_ctranslate(
    model_path: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    cuda_runtime: dict[str, Any] | None = None

    if args.device == "cuda":
        write_progress(
            args,
            7,
            "Locating and loading CUDA 12 libraries",
            compute_type="float16",
        )
        cuda_runtime = configure_nvidia_runtime()

    # Import only after CUDA DLL directories have been registered.
    from faster_whisper import WhisperModel

    compute_type = "float16" if args.device == "cuda" else "int8"
    write_progress(
        args,
        10,
        (
            "Loading Whisper on the GPU"
            if args.device == "cuda"
            else "Loading Whisper on the CPU"
        ),
        compute_type=compute_type,
        cuda_runtime=cuda_runtime,
    )

    model = WhisperModel(
        model_path,
        device=args.device,
        compute_type=compute_type,
    )

    write_progress(
        args,
        14,
        "Detecting language and speech",
        compute_type=compute_type,
        cuda_runtime=cuda_runtime,
    )

    segments, info = model.transcribe(
        args.audio,
        language=args.language,
        vad_filter=True,
        word_timestamps=True,
    )

    rows: list[dict[str, Any]] = []
    duration = max(float(info.duration or 0), 0.1)

    for segment in segments:
        rows.append(
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "words": [
                    {
                        "start": word.start,
                        "end": word.end,
                        "word": word.word,
                        "probability": word.probability,
                    }
                    for word in (segment.words or [])
                ],
            }
        )

        ratio = min(
            max(float(segment.end or 0) / duration, 0.0),
            1.0,
        )
        write_progress(
            args,
            14 + round(ratio * 82),
            f"Transcribing {int(ratio * 100)}% of the audio",
            compute_type=compute_type,
            audio_progress=round(ratio * 100, 1),
            segment_count=len(rows),
            cuda_runtime=cuda_runtime,
        )

    raw_segment_count = len(rows)
    rows = resegment_for_dubbing(rows)

    write_progress(
        args,
        97,
        "Building complete dubbing phrases",
        compute_type=compute_type,
        raw_segment_count=raw_segment_count,
        segment_count=len(rows),
        cuda_runtime=cuda_runtime,
    )

    return {
        "device": args.device,
        "compute_type": compute_type,
        "cuda_runtime": cuda_runtime,
        "language": info.language,
        "duration": info.duration,
        "segmentation": {
            "strategy": "semantic-word-timestamps-v1",
            "preferred_seconds": 4.8,
            "maximum_seconds": 6.0,
            "raw_segment_count": raw_segment_count,
            "segment_count": len(rows),
        },
        "segments": rows,
    }


def run_transformers(
    model_path: str,
    runtime: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    cuda_runtime: dict[str, Any] | None = None

    if args.device == "cuda":
        write_progress(
            args,
            7,
            "Locating and loading CUDA libraries",
            compute_type=runtime,
        )
        cuda_runtime = configure_nvidia_runtime()

    from transformers import AutoProcessor, pipeline

    write_progress(
        args,
        10,
        "Loading the transcription model",
        compute_type=runtime,
        cuda_runtime=cuda_runtime,
    )

    processor = AutoProcessor.from_pretrained(model_path)

    if runtime == "onnx":
        from optimum.onnxruntime import ORTModelForSpeechSeq2Seq

        provider = (
            "CUDAExecutionProvider"
            if args.device == "cuda"
            else "CPUExecutionProvider"
        )
        model = ORTModelForSpeechSeq2Seq.from_pretrained(
            model_path,
            provider=provider,
        )
        device = -1
    else:
        from transformers import AutoModelForSpeechSeq2Seq

        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_path,
            device_map="auto" if args.device == "cuda" else None,
            torch_dtype="auto",
        )
        device = 0 if args.device == "cuda" else -1

    pipe = pipeline(
        "automatic-speech-recognition",
        model=model,
        tokenizer=processor.tokenizer,
        feature_extractor=processor.feature_extractor,
        device=device,
        chunk_length_s=30,
        return_timestamps=True,
    )

    kwargs = (
        {"generate_kwargs": {"language": args.language}}
        if args.language
        else {}
    )
    result = pipe(args.audio, **kwargs)

    write_progress(
        args,
        92,
        "Finalizing the transcript",
        compute_type=runtime,
        cuda_runtime=cuda_runtime,
    )

    rows: list[dict[str, Any]] = []
    for chunk in result.get("chunks", []):
        start, end = chunk.get("timestamp") or (0.0, 0.0)
        rows.append(
            {
                "start": float(start or 0),
                "end": float(end or start or 0)
                + (0.1 if end is None else 0),
                "text": chunk.get("text", ""),
                "words": [],
            }
        )

    if not rows and result.get("text"):
        rows = [
            {
                "start": 0.0,
                "end": 0.1,
                "text": result["text"],
                "words": [],
            }
        ]

    return {
        "device": args.device,
        "compute_type": runtime,
        "cuda_runtime": cuda_runtime,
        "language": args.language,
        "duration": None,
        "segmentation": {
            "strategy": "provider-chunks-no-word-timestamps",
            "raw_segment_count": len(rows),
            "segment_count": len(rows),
        },
        "segments": rows,
    }


def main() -> None:
    args = parse_args()
    write_progress(args, 5, "Preparing the transcription worker")

    manifest_path = Path(args.manifest)
    audio_path = Path(args.audio)
    output_path = Path(args.output)

    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"ASR model manifest not found: {manifest_path}"
        )
    if not audio_path.is_file():
        raise FileNotFoundError(
            f"Audio file not found: {audio_path}"
        )

    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8-sig")
    )
    runtime = str(manifest.get("runtime") or "ctranslate2")
    model_path = manifest.get("model_path") or manifest.get("snapshot")

    if not model_path:
        raise RuntimeError(
            "The ASR model manifest does not define model_path or snapshot."
        )

    if runtime == "ctranslate2":
        result = run_ctranslate(str(model_path), args)
    else:
        result = run_transformers(
            str(model_path),
            runtime,
            args,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    write_progress(
        args,
        99,
        (
            "Transcript ready on GPU"
            if result.get("device") == "cuda"
            else "Transcript ready on CPU"
        ),
        compute_type=result.get("compute_type"),
        cuda_runtime=result.get("cuda_runtime"),
    )


if __name__ == "__main__":
    main()
