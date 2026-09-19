from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
import sentencepiece as spm
import soundfile as sf

MODEL_ID = "WhissleAI/STT-meta-ZH-150m"
SAMPLE_RATE = 16000
MAX_SAMPLES_PER_SPEAKER = 5
MAX_TOTAL_SECONDS_PER_SPEAKER = 30.0
MIN_SAMPLE_SECONDS = 1.5
MAX_SAMPLE_SECONDS = 10.0

GENDER_LABELS = {"GENDER_MALE", "GENDER_FEMALE"}
AGE_LABELS = {"AGE_<14", "AGE_14_25", "AGE_26_40", "AGE_>41"}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _resample_linear(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return audio.astype(np.float32, copy=False)
    if audio.size < 2:
        return audio.astype(np.float32, copy=False)
    target_size = max(1, round(audio.size * target_rate / source_rate))
    old_x = np.linspace(0.0, 1.0, audio.size, endpoint=False)
    new_x = np.linspace(0.0, 1.0, target_size, endpoint=False)
    return np.interp(new_x, old_x, audio).astype(np.float32)


def _preprocess(audio: np.ndarray, config: dict[str, Any]) -> tuple[np.ndarray, int]:
    prep = config["preprocessor"]
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio.size < 64:
        raise ValueError("Audio excerpt is too short")

    preemph = float(prep.get("preemph", 0.97))
    audio = np.concatenate(([audio[0]], audio[1:] - preemph * audio[:-1])).astype(np.float32)

    n_fft = int(prep["n_fft"])
    hop = int(prep["hop_length"])
    win = int(prep["win_length"])
    window = np.hanning(win + 1)[:-1].astype(np.float32)
    padded_window = np.pad(window, (0, max(0, n_fft - win)))[:n_fft]
    pad_len = max(0, (n_fft - hop) // 2)
    if audio.size <= pad_len:
        audio = np.pad(audio, (0, pad_len + 1 - audio.size))
    audio = np.pad(audio, (pad_len, pad_len), mode="reflect")

    frame_count = max(0, 1 + (len(audio) - n_fft) // hop)
    if frame_count <= 0:
        raise ValueError("Audio excerpt cannot form an STFT frame")
    frames = np.empty((frame_count, n_fft // 2 + 1), dtype=np.float32)
    for i in range(frame_count):
        start = i * hop
        frame = audio[start : start + n_fft] * padded_window
        spectrum = np.fft.rfft(frame)
        frames[i] = (np.abs(spectrum) ** 2).astype(np.float32)

    n_mels = int(prep["features"])
    fmin = float(prep.get("lowfreq") or 0.0)
    high = prep.get("highfreq")
    fmax = SAMPLE_RATE / 2 if high is None else float(high)
    mel_min = 2595.0 * np.log10(1.0 + fmin / 700.0)
    mel_max = 2595.0 * np.log10(1.0 + fmax / 700.0)
    mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
    hz_points = 700.0 * (10.0 ** (mel_points / 2595.0) - 1.0)
    bins = np.floor((n_fft + 1) * hz_points / SAMPLE_RATE).astype(int)
    bins = np.clip(bins, 0, n_fft // 2)
    fbank = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for i in range(n_mels):
        left, center, right = int(bins[i]), int(bins[i + 1]), int(bins[i + 2])
        if center > left:
            fbank[i, left:center] = np.arange(center - left, dtype=np.float32) / float(center - left)
        if right > center:
            fbank[i, center:right] = (right - np.arange(center, right, dtype=np.float32)) / float(right - center)

    mel_spec = frames @ fbank.T
    guard = float(prep.get("log_zero_guard_value") or 1e-5)
    log_mel = np.log(mel_spec + guard)
    mean = log_mel.mean(axis=0, keepdims=True)
    std = log_mel.std(axis=0, keepdims=True)
    log_mel = (log_mel - mean) / (std + 1e-5)

    valid_len = int(log_mel.shape[0])
    pad_to = int(prep.get("pad_to") or 16)
    if pad_to > 1 and valid_len % pad_to:
        pad_frames = pad_to - (valid_len % pad_to)
        log_mel = np.pad(log_mel, ((0, pad_frames), (0, 0)))
    features = log_mel.T[np.newaxis, :, :].astype(np.float32)
    return features, valid_len


def _softmax(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64).reshape(-1)
    values = values - np.max(values)
    exp = np.exp(values)
    denom = float(exp.sum())
    return (exp / denom if denom > 0 else np.ones_like(exp) / max(1, exp.size)).astype(np.float64)


def _turn_overlap(turn: dict[str, Any], turns: list[dict[str, Any]]) -> float:
    start = float(turn.get("start") or 0.0)
    end = float(turn.get("end") or start)
    speaker = str(turn.get("speaker") or "")
    overlap = 0.0
    for other in turns:
        if other is turn or str(other.get("speaker") or "") == speaker:
            continue
        o_start = float(other.get("start") or 0.0)
        o_end = float(other.get("end") or o_start)
        overlap += max(0.0, min(end, o_end) - max(start, o_start))
    return overlap


def _extract_candidates(audio: np.ndarray, sr: int, turns: list[dict[str, Any]], speaker: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for turn in turns:
        if str(turn.get("speaker") or "") != speaker:
            continue
        start_s = max(0.0, float(turn.get("start") or 0.0))
        end_s = max(start_s, float(turn.get("end") or start_s))
        duration = end_s - start_s
        if duration < MIN_SAMPLE_SECONDS:
            continue
        overlap = _turn_overlap(turn, turns)
        if overlap > min(0.35, duration * 0.15):
            continue
        if duration > MAX_SAMPLE_SECONDS:
            mid = (start_s + end_s) / 2.0
            start_s = max(start_s, mid - MAX_SAMPLE_SECONDS / 2.0)
            end_s = min(end_s, start_s + MAX_SAMPLE_SECONDS)
            duration = end_s - start_s
        a = max(0, round(start_s * sr))
        b = min(audio.size, round(end_s * sr))
        clip = np.asarray(audio[a:b], dtype=np.float32)
        if clip.size < int(MIN_SAMPLE_SECONDS * sr):
            continue
        rms = float(np.sqrt(np.mean(clip * clip)))
        if rms < 0.0025:
            continue
        preferred = 1.0 if 3.0 <= duration <= 8.0 else 0.82
        quality = preferred * min(1.0, rms / 0.02)
        candidates.append({"audio": clip, "duration": duration, "rms": rms, "quality": quality, "start": start_s})

    candidates.sort(key=lambda item: (item["quality"], min(item["duration"], 8.0)), reverse=True)
    selected: list[dict[str, Any]] = []
    total = 0.0
    for item in candidates:
        if len(selected) >= MAX_SAMPLES_PER_SPEAKER:
            break
        if selected and total + float(item["duration"]) > MAX_TOTAL_SECONDS_PER_SPEAKER:
            continue
        selected.append(item)
        total += float(item["duration"])
    return selected


def _decode_ctc(
    logprobs: np.ndarray,
    vocabulary: list[str],
    blank_id: int,
    tokenizer: spm.SentencePieceProcessor,
) -> tuple[str, dict[str, str]]:
    pred_ids = np.argmax(logprobs[0], axis=-1)
    decoded_ids: list[int] = []
    previous = -1
    for raw in pred_ids:
        idx = int(raw)
        if idx != previous and idx != blank_id and 0 <= idx < len(vocabulary):
            decoded_ids.append(idx)
        previous = idx

    transcript = ""
    try:
        transcript = tokenizer.DecodeIds(decoded_ids)
    except Exception:
        transcript = ""

    token_text = " ".join(
        str(vocabulary[idx]).replace("▁", " ").strip()
        for idx in decoded_ids
        if 0 <= idx < len(vocabulary)
    )
    combined = f"{transcript} {token_text}".upper().replace("  ", " ")

    gender = "NONE"
    age = "NONE"
    for label in sorted(GENDER_LABELS, key=len, reverse=True):
        if label in combined:
            gender = label
            break
    for label in sorted(AGE_LABELS, key=len, reverse=True):
        if label in combined:
            age = label
            break
    return transcript, {"GENDER": gender, "AGE": age}


def _classify_excerpt(
    clip: np.ndarray,
    sr: int,
    config: dict[str, Any],
    asr_session: ort.InferenceSession,
    cls_session: ort.InferenceSession,
    cls_meta: dict[str, Any],
    vocabulary: list[str],
    blank_id: int,
    tokenizer: spm.SentencePieceProcessor,
) -> dict[str, Any]:
    clip = _resample_linear(clip, sr, SAMPLE_RATE)
    features, valid_len = _preprocess(clip, config)
    length = np.array([features.shape[2]], dtype=np.int64)
    logprobs, encoder_output = asr_session.run(
        ["logprobs", "encoder_output"],
        {"audio_signal": features, "length": length},
    )

    transcript, ctc_tags = _decode_ctc(logprobs, vocabulary, blank_id, tokenizer)

    enc = encoder_output.transpose(0, 2, 1)
    usable = max(1, min(enc.shape[1], valid_len // 8))
    pooled = enc[:, :usable, :].mean(axis=1).astype(np.float32)
    tag_outputs = cls_session.run(None, {"pooled_encoder": pooled})

    categories = cls_meta["categories"]
    ordered = sorted(categories.keys())
    probabilities: dict[str, dict[str, float]] = {}
    for index, cat_name in enumerate(ordered):
        labels = list(categories[cat_name]["labels"])
        probs = _softmax(np.asarray(tag_outputs[index])[0])
        probabilities[cat_name.upper()] = {
            str(label): float(probs[i]) for i, label in enumerate(labels)
        }

    return {
        "probabilities": probabilities,
        "ctc_tags": ctc_tags,
        "ctc_transcript": transcript,
    }


def _sample_weight(item: dict[str, Any]) -> float:
    return max(0.2, min(8.0, float(item["duration"]))) * max(0.35, float(item["quality"]))


def _aggregate_classifier(samples: list[dict[str, Any]], category: str) -> tuple[str, float, float]:
    totals: dict[str, float] = {}
    total_weight = 0.0
    winners: list[str] = []
    for item in samples:
        probabilities = item["analysis"]["probabilities"].get(category, {})
        if not probabilities:
            continue
        weight = _sample_weight(item)
        total_weight += weight
        for label, probability in probabilities.items():
            totals[label] = totals.get(label, 0.0) + weight * float(probability)
        winners.append(max(probabilities, key=probabilities.get))
    if not totals or total_weight <= 0:
        return "NONE", 0.0, 0.0
    averaged = {label: value / total_weight for label, value in totals.items()}
    winner = max(averaged, key=averaged.get)
    agreement = sum(1 for value in winners if value == winner) / max(1, len(winners))
    raw_conf = float(averaged[winner])
    confidence = raw_conf * (0.70 + 0.30 * agreement)
    return winner, confidence, agreement


def _aggregate_ctc(samples: list[dict[str, Any]], category: str) -> tuple[str, float, float, float, int]:
    totals: dict[str, float] = {}
    total_weight = sum(_sample_weight(item) for item in samples)
    tagged_weight = 0.0
    winners: list[str] = []
    for item in samples:
        label = str(item["analysis"]["ctc_tags"].get(category) or "NONE")
        if label == "NONE":
            continue
        weight = _sample_weight(item)
        tagged_weight += weight
        totals[label] = totals.get(label, 0.0) + weight
        winners.append(label)

    if not totals or total_weight <= 0 or tagged_weight <= 0:
        return "NONE", 0.0, 0.0, 0.0, 0

    winner = max(totals, key=totals.get)
    winner_share = totals[winner] / tagged_weight
    agreement = sum(1 for value in winners if value == winner) / max(1, len(winners))
    coverage = tagged_weight / total_weight
    confidence = winner_share * (0.45 + 0.25 * agreement + 0.30 * coverage)
    if len(winners) == 1:
        confidence = min(confidence, 0.72)
    return winner, float(confidence), float(agreement), float(coverage), len(winners)


def _fuse(
    classifier_label: str,
    classifier_conf: float,
    ctc_label: str,
    ctc_conf: float,
    *,
    classifier_min: float,
    ctc_min: float,
) -> tuple[str, float, str]:
    cls_valid = classifier_label != "NONE" and classifier_conf >= classifier_min
    ctc_valid = ctc_label != "NONE" and ctc_conf >= ctc_min

    if cls_valid and ctc_valid:
        if classifier_label == ctc_label:
            return classifier_label, min(0.98, max(classifier_conf, ctc_conf) + 0.08), "ctc+classifier"
        if ctc_conf >= 0.84 and classifier_conf <= 0.58:
            return ctc_label, min(0.84, ctc_conf), "ctc_over_classifier_conflict"
        if classifier_conf >= 0.86 and ctc_conf <= 0.55:
            return classifier_label, min(0.86, classifier_conf), "classifier_over_ctc_conflict"
        return "NONE", 0.0, "conflict"

    if ctc_valid:
        return ctc_label, min(0.86, ctc_conf), "ctc"
    if cls_valid:
        return classifier_label, min(0.90, classifier_conf), "classifier"
    return "NONE", 0.0, "fallback"


def _map_age(label: str, confidence: float) -> tuple[str, list[str]]:
    if confidence < 0.52 or label == "NONE":
        return "unknown", []
    if label == "AGE_<14":
        return "child", ["child"]
    if label == "AGE_14_25":
        return "young_adult", ["teen", "young_adult"]
    if label == "AGE_26_40":
        return "adult", ["adult"]
    if label == "AGE_>41":
        return "adult", ["adult", "elderly"]
    return "unknown", []


def _map_gender(label: str, confidence: float) -> str:
    if confidence < 0.58:
        return "uncertain"
    if label == "GENDER_MALE":
        return "male"
    if label == "GENDER_FEMALE":
        return "female"
    return "uncertain"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--diarization-json", required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    model_root = Path(args.model_path).resolve()
    onnx_root = model_root / "onnx"
    model_path = onnx_root / "model.onnx"
    classifier_path = onnx_root / "tag_classifier.onnx"
    classifier_meta_path = onnx_root / "tag_classifier.json"
    config_path = onnx_root / "config.json"
    tokenizer_path = onnx_root / "tokenizer.model"
    vocabulary_path = onnx_root / "vocabulary.json"
    required = (
        model_path,
        classifier_path,
        classifier_meta_path,
        config_path,
        tokenizer_path,
        vocabulary_path,
    )
    missing = [p for p in required if not p.is_file()]
    if missing:
        raise RuntimeError("Whissle Mandarin model incomplete: " + ", ".join(str(p) for p in missing))

    manifest = _read_json(Path(args.diarization_json))
    turns = [item for item in manifest.get("turns") or [] if isinstance(item, dict)]
    speakers = sorted({str(item.get("speaker") or "") for item in turns if str(item.get("speaker") or "")})
    audio, sr = sf.read(args.input, dtype="float32", always_2d=True)
    mono = np.asarray(audio[:, 0], dtype=np.float32)

    config = _read_json(config_path)
    cls_meta = _read_json(classifier_meta_path)
    vocab_data = _read_json(vocabulary_path)
    vocabulary = [str(item) for item in (vocab_data.get("vocabulary") or [])]
    if not vocabulary:
        raise RuntimeError("Whissle vocabulary.json does not contain a vocabulary list")
    blank_id = int(vocab_data.get("blank_id", len(vocabulary)))
    tokenizer = spm.SentencePieceProcessor()
    if not tokenizer.Load(str(tokenizer_path)):
        raise RuntimeError("Could not load Whissle tokenizer.model")

    session_options = ort.SessionOptions()
    session_options.intra_op_num_threads = max(1, min(4, __import__("os").cpu_count() or 2))
    session_options.inter_op_num_threads = 1
    asr_session = ort.InferenceSession(
        str(model_path),
        sess_options=session_options,
        providers=["CPUExecutionProvider"],
    )
    cls_session = ort.InferenceSession(
        str(classifier_path),
        sess_options=session_options,
        providers=["CPUExecutionProvider"],
    )

    profiles: list[dict[str, Any]] = []
    analyzed = 0
    for speaker in speakers:
        excerpts = _extract_candidates(mono, sr, turns, speaker)
        inference_samples: list[dict[str, Any]] = []
        for excerpt in excerpts:
            try:
                analysis = _classify_excerpt(
                    excerpt["audio"], sr, config, asr_session, cls_session,
                    cls_meta, vocabulary, blank_id, tokenizer,
                )
            except Exception:
                continue
            inference_samples.append({**excerpt, "analysis": analysis})
        if not inference_samples:
            continue

        cls_gender, cls_gender_conf, cls_gender_agreement = _aggregate_classifier(inference_samples, "GENDER")
        cls_age, cls_age_conf, cls_age_agreement = _aggregate_classifier(inference_samples, "AGE")
        dialect_label, dialect_conf, dialect_agreement = _aggregate_classifier(inference_samples, "DIALECT")

        ctc_gender, ctc_gender_conf, ctc_gender_agreement, ctc_gender_coverage, ctc_gender_count = _aggregate_ctc(
            inference_samples, "GENDER"
        )
        ctc_age, ctc_age_conf, ctc_age_agreement, ctc_age_coverage, ctc_age_count = _aggregate_ctc(
            inference_samples, "AGE"
        )

        gender_label, gender_conf, gender_source = _fuse(
            cls_gender, cls_gender_conf, ctc_gender, ctc_gender_conf,
            classifier_min=0.64, ctc_min=0.55,
        )
        age_label, age_conf, age_source = _fuse(
            cls_age, cls_age_conf, ctc_age, ctc_age_conf,
            classifier_min=0.55, ctc_min=0.52,
        )

        gender = _map_gender(gender_label, gender_conf)
        age_group, age_candidates = _map_age(age_label, age_conf)
        sample_count = len(inference_samples)
        speech_seconds = sum(float(item["duration"]) for item in inference_samples)

        has_demographic = gender in {"male", "female"} or age_group != "unknown"
        strongest_valid = max(
            gender_conf if gender in {"male", "female"} else 0.0,
            age_conf if age_group != "unknown" else 0.0,
        )
        evidence_quality = (
            "strong" if has_demographic and sample_count >= 3 and strongest_valid >= 0.78
            else "medium" if has_demographic and sample_count >= 2 and strongest_valid >= 0.60
            else "weak" if has_demographic
            else "fallback_only"
        )

        example_transcripts = [
            str(item["analysis"].get("ctc_transcript") or "")[:160]
            for item in inference_samples
            if str(item["analysis"].get("ctc_transcript") or "").strip()
        ][:2]

        profiles.append({
            "speaker": speaker,
            "meta_gender": gender,
            "meta_gender_confidence": round(float(gender_conf), 3) if gender in {"male", "female"} else 0.0,
            "meta_gender_raw": gender_label,
            "meta_gender_source": gender_source,
            "classifier_gender_raw": cls_gender,
            "classifier_gender_confidence": round(float(cls_gender_conf), 3),
            "classifier_gender_agreement": round(float(cls_gender_agreement), 3),
            "ctc_gender_raw": ctc_gender,
            "ctc_gender_confidence": round(float(ctc_gender_conf), 3),
            "ctc_gender_agreement": round(float(ctc_gender_agreement), 3),
            "ctc_gender_coverage": round(float(ctc_gender_coverage), 3),
            "ctc_gender_samples": ctc_gender_count,

            "meta_age_group": age_group,
            "meta_age_confidence": round(float(age_conf), 3) if age_group != "unknown" else 0.0,
            "raw_age_bucket": age_label.removeprefix("AGE_") if age_label != "NONE" else "NONE",
            "age_group_candidates": age_candidates,
            "meta_age_source": age_source,
            "classifier_age_raw": cls_age,
            "classifier_age_confidence": round(float(cls_age_conf), 3),
            "classifier_age_agreement": round(float(cls_age_agreement), 3),
            "ctc_age_raw": ctc_age,
            "ctc_age_confidence": round(float(ctc_age_conf), 3),
            "ctc_age_agreement": round(float(ctc_age_agreement), 3),
            "ctc_age_coverage": round(float(ctc_age_coverage), 3),
            "ctc_age_samples": ctc_age_count,

            "meta_dialect": dialect_label.removeprefix("DIALECT_") if dialect_label != "NONE" else "NONE",
            "meta_dialect_confidence": round(float(dialect_conf), 3),
            "meta_dialect_agreement": round(float(dialect_agreement), 3),
            "demographic_model": MODEL_ID,
            "demographic_model_language": "zh",
            "demographic_revision": "ctc-fusion-v4",
            "samples_analyzed": sample_count,
            "speech_seconds_analyzed": round(speech_seconds, 3),
            "evidence_quality": evidence_quality,
            "ctc_transcript_examples": example_transcripts,
        })
        analyzed += 1

    _write_json(Path(args.output), {
        "status": "completed",
        "model": MODEL_ID,
        "revision": "ctc-fusion-v4",
        "speaker_count": len(speakers),
        "analyzed_speaker_count": analyzed,
        "speaker_profiles": profiles,
    })


if __name__ == "__main__":
    main()
