from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "data" / "test-runs"
_DLL_HANDLES = []


def configure_nvidia_runtime() -> None:
    if os.name != "nt":
        return
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    for folder in (
        ROOT
        / "data"
        / "environments"
        / "tts-qwen3-0.6b-base"
        / "venv"
        / "Lib"
        / "site-packages"
        / "torch"
        / "lib",
        site_packages / "nvidia" / "cublas" / "bin",
        site_packages / "nvidia" / "cudnn" / "bin",
        site_packages / "ctranslate2",
        site_packages / "torch" / "lib",
    ):
        if not folder.is_dir():
            continue
        os.environ["PATH"] = f"{folder}{os.pathsep}{os.environ.get('PATH', '')}"
        _DLL_HANDLES.append(os.add_dll_directory(str(folder)))


def words(value: str) -> list[str]:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.findall(r"[a-z0-9]+", value)


def word_error_rate(reference: str, hypothesis: str) -> float:
    expected = words(reference)
    actual = words(hypothesis)
    previous = list(range(len(actual) + 1))
    for row, expected_word in enumerate(expected, start=1):
        current = [row]
        for column, actual_word in enumerate(actual, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (expected_word != actual_word),
                )
            )
        previous = current
    return previous[-1] / max(1, len(expected))


def main() -> None:
    candidates = sorted(
        RUNS.glob("qwen-runtime-*"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("No Qwen runtime benchmark is available")
    root = candidates[0]
    manifest = json.loads(
        (ROOT / "models" / "faster-whisper-turbo" / "model.json").read_text(
            encoding="utf-8"
        )
    )
    configure_nvidia_runtime()
    from faster_whisper import WhisperModel

    model = WhisperModel(
        str(manifest["model_path"]),
        device="cuda",
        compute_type="float16",
    )
    results = []
    for mode_root in sorted(path for path in root.iterdir() if path.is_dir()):
        request = json.loads((mode_root / "request.json").read_text(encoding="utf-8"))
        rows = []
        for item in request.get("items") or []:
            audio = Path(str(item["output_path"]))
            segments, _ = model.transcribe(
                str(audio),
                language=str(item.get("language") or "fr").split("-", 1)[0],
                vad_filter=True,
            )
            hypothesis = " ".join(segment.text.strip() for segment in segments).strip()
            reference = str(item["text"])
            rows.append(
                {
                    "id": item["id"],
                    "reference": reference,
                    "transcript": hypothesis,
                    "word_error_rate": round(
                        word_error_rate(reference, hypothesis),
                        4,
                    ),
                }
            )
        results.append(
            {
                "mode": mode_root.name,
                "average_word_error_rate": round(
                    sum(row["word_error_rate"] for row in rows) / max(1, len(rows)),
                    4,
                ),
                "lines": rows,
            }
        )
    report = {
        "ok": True,
        "benchmark_root": str(root),
        "results": results,
    }
    (root / "quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
