from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app import local_voice_service, voice_cleanup_service, voice_reference_service  # noqa: E402


def main() -> None:
    pending: list[tuple[dict, dict, str]] = []
    for profile in local_voice_service.profiles():
        for sample in profile.get("samples") or []:
            clean_path = Path(str(sample.get("clean_path") or ""))
            if clean_path.is_file():
                continue
            source = Path(str(sample.get("path") or ""))
            if not source.is_file():
                continue
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            pending.append((profile, sample, digest))

    transcriptions: dict[str, dict] = {}
    migrated = 0
    with tempfile.TemporaryDirectory(prefix="dubroom-voice-migration-") as folder:
        temporary = Path(folder)
        for position, (profile, sample, digest) in enumerate(pending, start=1):
            if digest not in transcriptions:
                print(json.dumps({
                    "event": "transcribing_unique_reference",
                    "index": len(transcriptions) + 1,
                    "source": sample["path"],
                }, ensure_ascii=False), flush=True)
                transcriptions[digest] = voice_reference_service.transcribe_reference(
                    sample["path"], language=None
                )
            transcription = transcriptions[digest]
            output = temporary / f"{sample['id']}.clean.wav"
            cleaned = voice_cleanup_service.prepare_reference(
                sample["path"],
                output,
                reference_text=str(sample.get("reference_text") or transcription.get("text") or ""),
                transcription=transcription,
                mode="balanced",
            )
            local_voice_service.attach_cleaned_sample(
                str(profile["id"]),
                str(sample["id"]),
                cleaned,
                transcription=transcription,
            )
            migrated += 1
            print(json.dumps({
                "event": "sample_migrated",
                "index": position,
                "total": len(pending),
                "profile": profile.get("name"),
                "duration": (cleaned.get("metrics") or {}).get("duration_seconds"),
            }, ensure_ascii=False), flush=True)

    print(json.dumps({
        "ok": True,
        "migrated": migrated,
        "unique_transcriptions": len(transcriptions),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
