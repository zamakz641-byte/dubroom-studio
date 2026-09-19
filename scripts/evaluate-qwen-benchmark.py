from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TEXTS = [
    "La nuit semblait paisible, mais quelque chose attendait derrière les remparts.",
    "Lorsque la cloche sonna, chacun comprit que la bataille avait commencé.",
    "Il releva lentement les yeux et répondit avec un calme presque inquiétant.",
    "Personne ne savait encore que cette décision allait bouleverser tout le royaume.",
]
_DLL_HANDLES = []


def configure_nvidia_runtime() -> None:
    if os.name != "nt":
        return
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    for folder in (
        site_packages / "nvidia" / "cublas" / "bin",
        site_packages / "nvidia" / "cudnn" / "bin",
        ROOT
        / "data"
        / "environments"
        / "rvc-runtime"
        / "venv"
        / "Lib"
        / "site-packages"
        / "torch"
        / "lib",
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
        (ROOT / "data" / "test-runs").glob("qwen-batching-*"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("No Qwen benchmark output was found")
    benchmark_root = candidates[0]
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
    for batch_size in (1, 2, 3):
        rows = []
        for index, reference in enumerate(TEXTS, start=1):
            audio = benchmark_root / f"batch-{batch_size}" / f"line-{index}.wav"
            segments, _ = model.transcribe(
                str(audio),
                language="fr",
                vad_filter=True,
            )
            hypothesis = " ".join(segment.text.strip() for segment in segments).strip()
            rows.append(
                {
                    "line": index,
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
                "batch_size": batch_size,
                "average_word_error_rate": round(
                    sum(row["word_error_rate"] for row in rows) / len(rows),
                    4,
                ),
                "lines": rows,
            }
        )
    print(
        json.dumps(
            {
                "ok": True,
                "benchmark_root": str(benchmark_root),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
