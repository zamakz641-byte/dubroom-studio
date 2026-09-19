from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

DATASET_REPO = "AISHELL/AISHELL-3"
MODEL_ID = "iic/speech_eres2netv2_sv_zh-cn_16k-common"
HEAD_ID = "DubRoom/ERes2NetV2-AISHELL3-R2"
AGE_LABELS = {"A", "B", "C", "D"}
GENDERS = {"male", "female"}


def setup(packages: Path, cache_dir: Path) -> None:
    if packages.is_dir():
        sys.path.insert(0, str(packages))
    os.environ.setdefault("MODELSCOPE_CACHE", str(cache_dir / "modelscope"))
    os.environ.setdefault("HF_HOME", str(cache_dir / "huggingface"))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def normalize(vector: np.ndarray) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(value))
    return value / norm if norm > 1e-8 else value


def parse_spk_info(path: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        speaker, age, gender, accent = parts[:4]
        age = age.upper()
        gender = gender.lower()
        if age not in AGE_LABELS or gender not in GENDERS:
            continue
        result[speaker] = {
            "age": age,
            "gender": gender,
            "accent": accent.lower(),
        }
    return result


def actual_wavs_by_speaker(repo_files: list[str]) -> dict[str, list[str]]:
    """Use ONLY files that really exist in the HF repository.

    AISHELL-3's label_train-set.txt contains far more utterance IDs than the
    current HF mirror exposes as individual WAV files. Sampling labels first
    therefore causes thousands of guaranteed 404s.
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    for filename in repo_files:
        normalized = str(filename).replace("\\", "/")
        if not normalized.lower().endswith(".wav"):
            continue
        parts = normalized.split("/")
        if len(parts) < 4:
            continue
        if parts[0] not in {"train", "test"} or parts[1] != "wav":
            continue
        speaker = parts[2]
        if not speaker.startswith("SSB"):
            continue
        grouped[speaker].append(normalized)

    for speaker in grouped:
        grouped[speaker] = sorted(set(grouped[speaker]))
    return dict(grouped)


def spread_sample(values: list[str], count: int, seed: int, speaker: str) -> list[str]:
    if len(values) <= count:
        return list(values)
    rng = random.Random(f"{seed}:{speaker}")
    # Randomized but deterministic. It avoids systematically taking only
    # early utterances while remaining exactly reproducible.
    indexes = sorted(rng.sample(range(len(values)), count))
    return [values[index] for index in indexes]


def extract_embedding(model: Any, wav_path: Path) -> np.ndarray:
    result = model.generate(input=str(wav_path), disable_pbar=True)
    if not result:
        raise RuntimeError("ERes2NetV2 returned no embedding")
    value = result[0].get("spk_embedding")
    if value is None:
        raise RuntimeError("spk_embedding missing")
    try:
        import torch
        if isinstance(value, torch.Tensor):
            value = value.detach().cpu().numpy()
    except Exception:
        pass
    return normalize(np.asarray(value, dtype=np.float32))


def balanced_accuracy(y_true: list[str], y_pred: list[str]) -> float:
    labels = sorted(set(y_true))
    recalls: list[float] = []
    for label in labels:
        indices = [i for i, value in enumerate(y_true) if value == label]
        if not indices:
            continue
        correct = sum(1 for i in indices if y_pred[i] == label)
        recalls.append(correct / len(indices))
    return float(sum(recalls) / max(1, len(recalls)))


def class_metrics(y_true: list[str], y_pred: list[str]) -> dict[str, Any]:
    labels = sorted(set(y_true) | set(y_pred))
    output: dict[str, Any] = {}
    for label in labels:
        indices = [i for i, value in enumerate(y_true) if value == label]
        if not indices:
            continue
        correct = sum(1 for i in indices if y_pred[i] == label)
        output[label] = {
            "count": len(indices),
            "recall": round(correct / len(indices), 4),
        }
    return output


def choose_model(X_train, y_train, X_val, y_val, *, seed: int):
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import ExtraTreesClassifier

    candidates = [
        (
            "logreg",
            make_pipeline(
                StandardScaler(),
                LogisticRegression(
                    max_iter=5000,
                    C=1.5,
                    class_weight="balanced",
                    random_state=seed,
                ),
            ),
        ),
        (
            "extratrees",
            ExtraTreesClassifier(
                n_estimators=700,
                max_features="sqrt",
                min_samples_leaf=2,
                class_weight="balanced",
                random_state=seed,
                n_jobs=-1,
            ),
        ),
    ]

    best = None
    details = []
    for name, model in candidates:
        model.fit(X_train, y_train)
        pred = [str(item) for item in model.predict(X_val)]
        bal = balanced_accuracy(list(y_val), pred)
        acc = float(np.mean(np.asarray(pred) == np.asarray(y_val)))
        details.append({
            "name": name,
            "balanced_accuracy": round(bal, 4),
            "accuracy": round(acc, 4),
            "per_class": class_metrics(list(y_val), pred),
        })
        if best is None or bal > best[0]:
            best = (bal, name, model)
    assert best is not None
    return best[1], best[2], details


def safe_train_val_split(
    speakers: list[str],
    metadata: dict[str, dict[str, str]],
    *,
    seed: int,
) -> tuple[list[str], list[str]]:
    from sklearn.model_selection import train_test_split

    joint = [
        f"{metadata[speaker]['gender']}-{metadata[speaker]['age']}"
        for speaker in speakers
    ]
    try:
        return train_test_split(
            speakers,
            test_size=0.22,
            random_state=seed,
            stratify=joint,
        )
    except ValueError:
        # Some age/gender combinations are genuinely tiny in AISHELL-3.
        return train_test_split(
            speakers,
            test_size=0.22,
            random_state=seed,
            stratify=[metadata[s]["gender"] for s in speakers],
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packages", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--samples-per-speaker", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    packages = Path(args.packages).resolve()
    cache_dir = Path(args.cache_dir).resolve()
    output = Path(args.output).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    setup(packages, cache_dir)

    from huggingface_hub import HfApi, hf_hub_download
    from funasr import AutoModel
    import joblib
    from sklearn.base import clone

    print("[R2] AISHELL-3 trainer: selection basee sur les WAV REELLEMENT presents.")
    print("[DATA] Chargement spk-info.txt...")
    spk_info = Path(hf_hub_download(
        repo_id=DATASET_REPO,
        repo_type="dataset",
        filename="spk-info.txt",
        cache_dir=str(cache_dir / "huggingface"),
    ))
    metadata = parse_spk_info(spk_info)

    print("[DATA] Inventaire du depot Hugging Face (un seul listing, pas de 404 par clip)...")
    api = HfApi()
    repo_files = api.list_repo_files(
        repo_id=DATASET_REPO,
        repo_type="dataset",
    )
    wavs_by_speaker = actual_wavs_by_speaker(repo_files)

    usable_speakers = sorted(
        speaker
        for speaker in set(metadata).intersection(wavs_by_speaker)
        if wavs_by_speaker.get(speaker)
    )
    actual_wav_count = sum(len(wavs_by_speaker[s]) for s in usable_speakers)

    print(f"[DATA] Speakers metadata: {len(metadata)}")
    print(f"[DATA] Speakers avec WAV reels: {len(usable_speakers)}")
    print(f"[DATA] WAV reels disponibles (train+test): {actual_wav_count}")

    if len(usable_speakers) < 80:
        raise RuntimeError(
            f"Trop peu de speakers avec WAV reels sur le miroir: {len(usable_speakers)}"
        )

    count = max(4, min(20, int(args.samples_per_speaker)))
    selected: list[tuple[str, str]] = []
    for speaker in usable_speakers:
        for filename in spread_sample(
            wavs_by_speaker[speaker],
            count,
            args.seed,
            speaker,
        ):
            selected.append((speaker, filename))

    print(f"[DATA] Clips cibles reels: {len(selected)}")
    print("[DATA] Les 157 embeddings deja caches peuvent etre reutilises automatiquement.")

    try:
        import torch
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        device = "cpu"

    print(f"[MODEL] Chargement ERes2NetV2 sur {device}...")
    model = AutoModel(
        model=MODEL_ID,
        device=device,
        disable_update=True,
        hub="ms",
    )

    X: list[np.ndarray] = []
    genders: list[str] = []
    ages: list[str] = []
    groups: list[str] = []
    failures: list[dict[str, str]] = []

    for index, (speaker, filename) in enumerate(selected, 1):
        try:
            wav_path = Path(hf_hub_download(
                repo_id=DATASET_REPO,
                repo_type="dataset",
                filename=filename,
                cache_dir=str(cache_dir / "huggingface"),
            ))
            embedding = extract_embedding(model, wav_path)
        except Exception as exc:
            failures.append({
                "file": filename,
                "error": str(exc)[-300:],
            })
            if len(failures) <= 12:
                print(f"[WARN] {filename}: {str(exc)[-180:]}")
            continue

        X.append(embedding)
        genders.append(metadata[speaker]["gender"])
        ages.append(metadata[speaker]["age"])
        groups.append(speaker)

        if index % 100 == 0 or index == len(selected):
            print(
                f"[EMBED] {index}/{len(selected)} | "
                f"OK={len(X)} | failed={len(failures)}"
            )

    unique_groups = sorted(set(groups))
    print(f"[EMBED] Final: {len(X)} embeddings / {len(unique_groups)} speakers.")

    if len(X) < 500 or len(unique_groups) < 70:
        raise RuntimeError(
            f"Dataset embeddings insuffisant: {len(X)} embeddings, "
            f"{len(unique_groups)} speakers"
        )

    matrix = np.stack(X, axis=0)
    groups_arr = np.asarray(groups)
    train_spk, val_spk = safe_train_val_split(
        unique_groups,
        metadata,
        seed=args.seed,
    )
    train_set = set(train_spk)
    val_set = set(val_spk)
    train_idx = np.array([speaker in train_set for speaker in groups], dtype=bool)
    val_idx = np.array([speaker in val_set for speaker in groups], dtype=bool)

    X_train = matrix[train_idx]
    X_val = matrix[val_idx]
    gender_arr = np.asarray(genders)
    age_arr = np.asarray(ages)
    gender_train = gender_arr[train_idx]
    gender_val = gender_arr[val_idx]
    age_train = age_arr[train_idx]
    age_val = age_arr[val_idx]

    print(
        f"[SPLIT] train speakers={len(train_set)} | "
        f"validation speakers={len(val_set)}"
    )
    print("[TRAIN] Gender: LogisticRegression vs ExtraTrees...")
    gender_name, gender_best, gender_candidates = choose_model(
        X_train, gender_train, X_val, gender_val, seed=args.seed
    )
    print("[TRAIN] Age: LogisticRegression vs ExtraTrees...")
    age_name, age_best, age_candidates = choose_model(
        X_train, age_train, X_val, age_val, seed=args.seed
    )

    gender_pred = [str(x) for x in gender_best.predict(X_val)]
    age_pred = [str(x) for x in age_best.predict(X_val)]
    gender_bal = balanced_accuracy(list(gender_val), gender_pred)
    age_bal = balanced_accuracy(list(age_val), age_pred)
    gender_acc = float(np.mean(np.asarray(gender_pred) == gender_val))
    age_acc = float(np.mean(np.asarray(age_pred) == age_val))

    # Auto-safety: an objectively poor validation head is not allowed to
    # silently become production truth.
    gender_enabled = gender_bal >= 0.72 and gender_acc >= 0.78
    age_enabled = age_bal >= 0.42 and age_acc >= 0.50

    gender_final = None
    age_final = None
    if gender_enabled:
        gender_final = clone(gender_best)
        gender_final.fit(matrix, gender_arr)
    if age_enabled:
        age_final = clone(age_best)
        age_final.fit(matrix, age_arr)

    metrics = {
        "revision": "aishell3-r2-real-files",
        "validation_split": "speaker_disjoint_22_percent",
        "repo_file_count": len(repo_files),
        "actual_wav_count": actual_wav_count,
        "usable_speaker_count": len(usable_speakers),
        "embedding_speaker_count": len(unique_groups),
        "embedding_count": len(X),
        "download_or_embedding_failures": len(failures),
        "samples_per_speaker_target": count,
        "gender_model_type": gender_name,
        "gender_accuracy": round(gender_acc, 4),
        "gender_balanced_accuracy": round(gender_bal, 4),
        "gender_enabled": gender_enabled,
        "gender_candidates": gender_candidates,
        "age_model_type": age_name,
        "age_accuracy": round(age_acc, 4),
        "age_balanced_accuracy": round(age_bal, 4),
        "age_enabled": age_enabled,
        "age_candidates": age_candidates,
    }

    payload = {
        "id": HEAD_ID,
        "revision": "aishell3-r2-real-files",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": DATASET_REPO,
        "dataset_license": "apache-2.0",
        "embedding_model": MODEL_ID,
        "embedding_dim": int(matrix.shape[1]),
        "gender_model": gender_final,
        "age_model": age_final,
        "metrics": metrics,
        "age_labels": {
            "A": "<14",
            "B": "14-25",
            "C": "26-40",
            "D": ">41",
        },
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(payload, output)

    report = output.with_suffix(".json")
    report.write_text(
        json.dumps({
            key: value
            for key, value in payload.items()
            if key not in {"gender_model", "age_model"}
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    failure_report = output.with_name(output.stem + "-failures.json")
    failure_report.write_text(
        json.dumps(failures[:200], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("")
    print("============================================================")
    print("  RESULTATS VALIDATION - SPEAKERS JAMAIS VUS")
    print("============================================================")
    print(
        f"Gender accuracy={gender_acc:.3f} | "
        f"balanced={gender_bal:.3f} | enabled={gender_enabled}"
    )
    print(
        f"Age    accuracy={age_acc:.3f} | "
        f"balanced={age_bal:.3f} | enabled={age_enabled}"
    )
    print(f"[OK] Head sauvegarde: {output}")
    print(f"[OK] Rapport: {report}")
    if not gender_enabled:
        print("[SAFE] Gender head trop faible: desactive automatiquement.")
    if not age_enabled:
        print("[SAFE] Age head trop faible: desactive automatiquement.")


if __name__ == "__main__":
    main()
