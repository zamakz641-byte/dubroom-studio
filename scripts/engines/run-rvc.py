from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Dubroom RVC inference adapter")
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--index")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--pitch", type=int, default=0)
    parser.add_argument("--f0-method", default="rmvpe")
    parser.add_argument("--index-rate", type=float, default=0.75)
    parser.add_argument("--protect", type=float, default=0.33)
    parser.add_argument("--filter-radius", type=int, default=3)
    parser.add_argument("--resample-sr", type=int, default=0)
    parser.add_argument("--rms-mix-rate", type=float, default=0.25)
    args = parser.parse_args()

    runtime = Path(args.runtime).resolve()
    model = Path(args.model).resolve()
    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    if not (runtime / "infer" / "modules" / "vc" / "modules.py").is_file():
        raise RuntimeError("RVC source runtime is incomplete")
    if not model.is_file() or not source.is_file():
        raise RuntimeError("RVC model or source audio is missing")

    os.environ["weight_root"] = str(model.parent)
    os.environ["index_root"] = str(Path(args.index).resolve().parent if args.index else model.parent)
    sys.path.insert(0, str(runtime))
    os.chdir(runtime)

    from configs.config import Config
    from infer.modules.vc.modules import VC

    config = Config()
    converter = VC(config)
    converter.get_vc(model.name, args.protect, args.protect)
    info, audio = converter.vc_single(
        0,
        str(source),
        args.pitch,
        None,
        args.f0_method,
        str(Path(args.index).resolve()) if args.index else "",
        "",
        args.index_rate,
        args.filter_radius,
        args.resample_sr,
        args.rms_mix_rate,
        args.protect,
    )
    if audio is None:
        raise RuntimeError(str(info or "RVC did not return audio"))
    sample_rate, samples = audio
    output.parent.mkdir(parents=True, exist_ok=True)
    import soundfile as sf

    sf.write(str(output), samples, sample_rate)
    print(f"RVC_OUTPUT={output}")


if __name__ == "__main__":
    main()
