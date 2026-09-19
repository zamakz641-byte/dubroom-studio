from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app import transcript_exchange_service as exchange  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def segment(segment_id: str, start: str, end: str, text: str) -> dict[str, object]:
    return {
        "id": segment_id,
        "start": start,
        "end": end,
        "speaker": "SPEAKER_00",
        "sourceText": text,
        "translatedText": "",
        "adaptedText": "",
    }


def payload(state: dict[str, object], project_name: str) -> dict[str, object]:
    return exchange.build_exchange_payload(
        project_id="subtitle-contract-test",
        project_name=project_name,
        state=state,
        project_dir=None,
    )


def complete_manifest(manifest: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(manifest)
    result["status"] = "translated"
    result["character_registry"] = [
        {
            "character_id": "CHAR_001",
            "character_name": "Ye Fan",
            "character_role": "protagonist",
            "voice_key": "mc",
            "sex": "male",
            "age_group": "young_adult",
            "confidence": 0.94,
        }
    ]
    for index, row in enumerate(result["segments"], start=1):
        ideal_words = int((row.get("recommended_words") or {}).get("ideal") or 4)
        timing_words = [
            "This", "spoken", "English", "line", "fits", "the", "timing",
            "window", "naturally", "and", "clearly", "today",
        ]
        row["translation"] = " ".join(timing_words[:ideal_words]) + "."
        row["voice_units"] = [
            {
                "unit_id": f"{row['id']}-u01",
                "order": 1,
                "speech_type": "dialogue",
                "character_id": "CHAR_001",
                "character_name": "Ye Fan",
                "character_role": "protagonist",
                "voice_key": "mc",
                "source_excerpt": row["text"],
                "translation": row["translation"],
                "emotion": "neutral",
                "emotion_intensity": 20,
                "vocal_events": [],
                "confidence": 0.94,
            }
        ]
    return result


def main() -> None:
    base_state: dict[str, object] = {
        "segments": [
            segment("zh-test-001", "00:00:12.000", "00:00:15.500", "叶凡你居然还活着"),
            segment("zh-test-002", "00:00:16.000", "00:00:18.000", "这不可能"),
        ],
        "source_language": "zh",
        "target_language": "en",
        "revision": 1,
        "dubbing_mode": "multi",
    }

    legacy_payload = payload(base_state, "Legacy V3")
    legacy_manifest = exchange.build_translation_manifest(
        project_dir=ROOT,
        payload=legacy_payload,
    )
    check(legacy_manifest["schema_version"] == 3, "Multi-speaker must remain schema V3")
    check(
        all("subtitle_evidence" not in row for row in legacy_manifest["segments"]),
        "Legacy V3 unexpectedly gained empty subtitle evidence",
    )
    legacy_fingerprint_payload = [
        {
            "id": str(item.get("id") or ""),
            "start": str(item.get("start") or ""),
            "end": str(item.get("end") or ""),
            "speaker": str(item.get("acousticSpeaker") or item.get("speaker") or ""),
            "source": str(item.get("sourceText") or "").strip(),
        }
        for item in base_state["segments"]
    ]
    legacy_expected_fingerprint = hashlib.sha256(
        json.dumps(
            legacy_fingerprint_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    check(
        legacy_manifest["transcript_fingerprint"] == legacy_expected_fingerprint,
        "Legacy V3 fingerprint changed despite having no subtitle evidence",
    )

    evidence = [
        {
            "text": "叶凡，你居然还活着！",
            "start": 11.8,
            "end": 15.6,
            "source": "soft_subtitle",
            "overlap_ratio": 0.92,
            "match_confidence": 0.96,
        }
    ]
    fused_state = copy.deepcopy(base_state)
    fused_state["subtitle_evidence_revision"] = "soft-subtitle-test-r1"
    fused_state["segments"][0]["subtitleEvidence"] = evidence
    fused_payload = payload(fused_state, "Subtitle Fusion R4")
    fused_manifest = exchange.build_translation_manifest(
        project_dir=ROOT,
        payload=fused_payload,
    )
    check(
        fused_manifest["segments"][0]["subtitle_evidence"] == evidence,
        "Multi-speaker subtitle evidence was not exported unchanged",
    )
    check(
        "subtitle_evidence" not in fused_manifest["segments"][1],
        "Optional evidence must stay absent on segments without a match",
    )
    check(
        fused_manifest["subtitle_evidence_revision"] == "soft-subtitle-test-r1",
        "Subtitle evidence revision was not exported",
    )
    check(
        fused_manifest["transcript_fingerprint"]
        != legacy_manifest["transcript_fingerprint"],
        "Subtitle evidence did not affect the transcript fingerprint",
    )

    single_state = copy.deepcopy(fused_state)
    single_state["dubbing_mode"] = "single"
    single_payload = payload(single_state, "Single-speaker V2")
    single_manifest = exchange.build_translation_manifest(
        project_dir=ROOT,
        payload=single_payload,
    )
    check(single_manifest["schema_version"] == 2, "Single-speaker must remain schema V2")
    check(
        all("subtitle_evidence" not in row for row in single_manifest["segments"]),
        "Single-speaker V2 received the multi-speaker subtitle contract",
    )
    check(
        single_manifest["transcript_fingerprint"]
        == exchange.transcript_fingerprint(
            single_state["segments"],
            include_subtitle_evidence=False,
        ),
        "Single-speaker fingerprint was changed by multi-speaker evidence",
    )

    completed = complete_manifest(fused_manifest)
    parsed = exchange._parse_json_payload(Path("completed-v3.json"), completed)
    accepted = exchange.preview_import(
        state=fused_state,
        parsed=parsed,
        require_complete_multispeaker=True,
    )
    check(accepted["can_apply"], "Unchanged subtitle evidence was rejected")

    french_output = copy.deepcopy(completed)
    french_output["segments"][0]["voice_units"][0]["translation"] = (
        "Il comprend alors que la vérité était devant lui depuis le début."
    )
    french_preview = exchange.preview_import(
        state=fused_state,
        parsed=exchange._parse_json_payload(Path("french-v3.json"), french_output),
        require_complete_multispeaker=True,
    )
    check(
        french_preview["non_english_translation_ids"] == ["zh-test-001"]
        and not french_preview["can_apply"],
        "R5 did not block clearly French prose",
    )

    short_output = copy.deepcopy(completed)
    short_output["segments"][0]["voice_units"][0]["translation"] = "Go now."
    short_preview = exchange.preview_import(
        state=fused_state,
        parsed=exchange._parse_json_payload(Path("short-v3.json"), short_output),
        require_complete_multispeaker=True,
    )
    check(
        short_preview["strict_timing_mismatch_ids"] == ["zh-test-001"]
        and not short_preview["can_apply"],
        "R5 did not block a translation below the minimum word budget",
    )

    modified = copy.deepcopy(completed)
    modified["segments"][0]["subtitle_evidence"][0]["text"] = "改写的字幕"
    modified_parsed = exchange._parse_json_payload(Path("modified-v3.json"), modified)
    rejected = exchange.preview_import(
        state=fused_state,
        parsed=modified_parsed,
        require_complete_multispeaker=True,
    )
    check(
        rejected["subtitle_evidence_mismatch_ids"] == ["zh-test-001"]
        and not rejected["can_apply"],
        "Modified subtitle evidence was not blocked",
    )

    missing = copy.deepcopy(completed)
    missing["segments"][0].pop("subtitle_evidence")
    missing_parsed = exchange._parse_json_payload(Path("missing-v3.json"), missing)
    missing_preview = exchange.preview_import(
        state=fused_state,
        parsed=missing_parsed,
        require_complete_multispeaker=True,
    )
    check(
        missing_preview["subtitle_evidence_mismatch_ids"] == ["zh-test-001"]
        and not missing_preview["can_apply"],
        "Removed subtitle evidence was not blocked",
    )

    print(
        json.dumps(
            {
                "legacy_v3_without_subtitles": "accepted",
                "multispeaker_v3_with_subtitles": "accepted",
                "single_speaker_v2_separate": True,
                "subtitle_r4_compact_registry": "accepted",
                "modified_evidence": "blocked",
                "removed_evidence": "blocked",
                "prompt_revision": exchange.MULTISPEAKER_PROMPT_REVISION,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
