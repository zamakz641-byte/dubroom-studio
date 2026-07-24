from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--language")
    return parser.parse_args()


def run_ctranslate(model_path: str, args: argparse.Namespace) -> dict:
    from faster_whisper import WhisperModel

    compute_type = "float16" if args.device == "cuda" else "int8"
    model = WhisperModel(model_path, device=args.device, compute_type=compute_type)
    segments, info = model.transcribe(args.audio, language=args.language, vad_filter=True, word_timestamps=True)
    rows = []
    for segment in segments:
        rows.append({"start": segment.start, "end": segment.end, "text": segment.text, "words": [{"start": word.start, "end": word.end, "word": word.word, "probability": word.probability} for word in (segment.words or [])]})
    return {"device": args.device, "compute_type": compute_type, "language": info.language, "duration": info.duration, "segments": rows}


def run_transformers(model_path: str, runtime: str, args: argparse.Namespace) -> dict:
    from transformers import AutoProcessor, pipeline

    processor = AutoProcessor.from_pretrained(model_path)
    if runtime == "onnx":
        from optimum.onnxruntime import ORTModelForSpeechSeq2Seq
        model = ORTModelForSpeechSeq2Seq.from_pretrained(model_path, provider="CUDAExecutionProvider" if args.device == "cuda" else "CPUExecutionProvider")
        device = -1
    else:
        from transformers import AutoModelForSpeechSeq2Seq
        model = AutoModelForSpeechSeq2Seq.from_pretrained(model_path, device_map="auto" if args.device == "cuda" else None, torch_dtype="auto")
        device = 0 if args.device == "cuda" else -1
    pipe = pipeline("automatic-speech-recognition", model=model, tokenizer=processor.tokenizer, feature_extractor=processor.feature_extractor, device=device, chunk_length_s=30, return_timestamps=True)
    kwargs = {"generate_kwargs": {"language": args.language}} if args.language else {}
    result = pipe(args.audio, **kwargs)
    rows = []
    for chunk in result.get("chunks", []):
        start, end = chunk.get("timestamp") or (0.0, 0.0)
        rows.append({"start": float(start or 0), "end": float(end or start or 0) + (0.1 if end is None else 0), "text": chunk.get("text", ""), "words": []})
    if not rows and result.get("text"):
        rows = [{"start": 0.0, "end": 0.1, "text": result["text"], "words": []}]
    return {"device": args.device, "compute_type": runtime, "language": args.language, "duration": None, "segments": rows}


def main() -> None:
    args = parse_args()
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    runtime = manifest.get("runtime", "ctranslate2")
    model_path = manifest.get("model_path") or manifest.get("snapshot")
    result = run_ctranslate(str(model_path), args) if runtime == "ctranslate2" else run_transformers(str(model_path), runtime, args)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
