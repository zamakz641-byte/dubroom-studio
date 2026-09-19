from __future__ import annotations

import argparse
import importlib.metadata
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--output-dir")
    parser.add_argument("--output")
    parser.add_argument("--progress-file")
    parser.add_argument("--model", default="htdemucs")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--segment", type=float, default=7.0)
    parser.add_argument("--overlap", type=float, default=0.25)
    parser.add_argument("--shifts", type=int, default=1)
    parser.add_argument("--shared-site-packages", action="append", default=[])
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def add_shared_dependencies(paths: list[str]) -> None:
    for raw_path in paths:
        path = str(Path(raw_path).resolve())
        if Path(path).is_dir() and path not in sys.path:
            # Append after the engine's own packages. Missing compatible
            # dependencies can be shared without replacing its pinned ML stack.
            sys.path.append(path)


def write_progress(args: argparse.Namespace, progress: int, message: str, **details: Any) -> None:
    if not args.progress_file:
        return
    path = Path(args.progress_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {
                "progress": max(0, min(99, int(progress))),
                "message": message,
                **details,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def runtime_info() -> dict[str, Any]:
    import numpy
    import torch
    import demucs.separate  # noqa: F401

    return {
        "python": sys.executable,
        "demucs": importlib.metadata.version("demucs"),
        "torch": torch.__version__,
        "numpy": numpy.__version__,
        "cuda_available": bool(torch.cuda.is_available()),
    }


def run_separation(args: argparse.Namespace) -> dict[str, Any]:
    from demucs.separate import main as demucs_main
    import torch

    source = Path(str(args.input or "")).resolve()
    output_dir = Path(str(args.output_dir or "")).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Input audio not found: {source}")
    if not args.output_dir:
        raise ValueError("--output-dir is required")
    output_dir.mkdir(parents=True, exist_ok=True)

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    work_dir = output_dir / "demucs-work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    write_progress(args, 12, "Loading the shared Demucs model cache", device=device)
    command = [
        "demucs.separate",
        "--name",
        args.model,
        "--device",
        device,
        "--two-stems",
        "vocals",
        "--out",
        str(work_dir),
        "--filename",
        "{stem}.{ext}",
        "--shifts",
        str(max(0, args.shifts)),
        "--overlap",
        str(max(0.0, min(0.95, args.overlap))),
        "-j",
        "0",
    ]
    if args.segment > 0:
        # Demucs 4.1 accepts whole-second segments. Seven seconds also stays
        # below the historical 7.8 s htdemucs limit.
        command.extend(["--segment", str(max(1, int(args.segment)))])
    command.append(str(source))

    write_progress(args, 20, "Separating dialogue from music and sound effects", device=device)
    previous_argv = sys.argv
    try:
        sys.argv = command
        demucs_main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            raise RuntimeError(f"Demucs exited with code {exc.code}") from exc
    finally:
        sys.argv = previous_argv

    vocals_source = next(work_dir.rglob("vocals.wav"), None)
    bed_source = next(work_dir.rglob("no_vocals.wav"), None)
    if not vocals_source or not bed_source:
        raise RuntimeError("Demucs completed without the expected vocals/no_vocals stems")

    vocals_path = output_dir / "vocals.wav"
    bed_path = output_dir / "bed.wav"
    shutil.copy2(vocals_source, vocals_path)
    shutil.copy2(bed_source, bed_path)
    if vocals_path.stat().st_size < 1024 or bed_path.stat().st_size < 1024:
        raise RuntimeError("Demucs produced an empty stem")

    write_progress(args, 94, "Validating separated stems", device=device)
    result = {
        "status": "ready",
        "model": args.model,
        "device": device,
        "vocals": str(vocals_path),
        "bed": str(bed_path),
        "runtime": runtime_info(),
    }
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_progress(args, 99, "Audio preservation stems are ready", device=device)
    return result


def main() -> None:
    args = parse_args()
    add_shared_dependencies(args.shared_site_packages)
    info = runtime_info()
    if args.self_test:
        print(json.dumps({"status": "ready", "runtime": info}, ensure_ascii=False))
        return
    write_progress(args, 5, "Checking the shared separation runtime", runtime=info)
    run_separation(args)


if __name__ == "__main__":
    main()
