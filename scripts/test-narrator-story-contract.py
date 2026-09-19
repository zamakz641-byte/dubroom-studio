from __future__ import annotations

import copy
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app import narrator_story_service as story  # noqa: E402


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def prepared_manifest() -> dict[str, object]:
    return story.build_narrator_story_manifest(
        project_id="narrator-story-test",
        project_name="Narrator Story Contract Test",
        duration_seconds=20.0,
        source_fingerprint="source-sha256-test",
        source_tracks=[
            {"kind": "asr_zh", "language": "zh", "origin": "funasr"},
            {"kind": "subtitle_zh", "language": "zh-Hans", "origin": "uploader_provided"},
            {"kind": "subtitle_en", "language": "en", "origin": "uploader_provided"},
        ],
        evidence=[
            {"evidence_id": "EVD_0001", "kind": "asr_zh", "start": 0.2, "end": 2.5, "text": "叶凡醒来"},
            {"evidence_id": "EVD_0002", "kind": "subtitle_zh", "start": 0.1, "end": 2.6, "text": "叶凡醒来了。"},
            {"evidence_id": "EVD_0003", "kind": "subtitle_en", "start": 0.1, "end": 2.6, "text": "Ye Fan woke up."},
        ],
        scenes=[
            {"scene_id": "SCN_0001", "start": 0.0, "end": 8.0},
            {"scene_id": "SCN_0002", "start": 8.0, "end": 20.0},
        ],
        narration_slots=[
            {
                "slot_id": "SLOT_0001", "scene_id": "SCN_0001",
                "start": 0.0, "end": 4.0, "duration_seconds": 4.0,
                "safe_start": 0.15, "safe_end": 3.75, "usable_duration_seconds": 3.6,
                "ideal_words": 8, "max_words": 10, "sfx_policy": "clear",
                "recommended_ducking_profile": "none",
                "allowed_evidence_ids": ["EVD_0001", "EVD_0002", "EVD_0003"],
            },
            {
                "slot_id": "SLOT_0002", "scene_id": "SCN_0002",
                "start": 8.0, "end": 11.0, "duration_seconds": 3.0,
                "safe_start": 8.15, "safe_end": 10.75, "usable_duration_seconds": 2.6,
                "ideal_words": 0, "max_words": 0, "sfx_policy": "protected",
                "recommended_ducking_profile": "none",
                "allowed_evidence_ids": [],
            },
        ],
        sfx_intervals=[
            {"sfx_id": "SFX_0001", "start": 8.0, "end": 11.0, "protected": True, "reason": "impact"}
        ],
    )


def completed_manifest(source: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(source)
    result["status"] = "scripted"
    result["story_bible"] = {"characters": [{"name": "Ye Fan", "role": "protagonist"}]}
    text = "Ye Fan woke to find his world completely changed."
    result["narration_blocks"] = [
        {
            "block_id": "NAR_0001", "scene_id": "SCN_0001", "slot_id": "SLOT_0001",
            "planned_start": 0.15, "hard_end": 3.75, "text": text,
            "word_count": story.spoken_word_count(text), "delivery": "awed",
            "delivery_intensity": 45, "evidence_ids": ["EVD_0001", "EVD_0002", "EVD_0003"],
            "ducking_profile": "none",
        }
    ]
    result["subtitle_cues"] = [
        {
            "cue_id": "SUB_0001", "block_id": "NAR_0001", "start": 0.15, "end": 3.75,
            "lines": ["Ye Fan woke to find his", "world completely changed."],
        }
    ]
    result["validation"] = {"passed": True, "errors": []}
    return result


def main() -> None:
    source = prepared_manifest()
    valid = completed_manifest(source)
    valid_result = story.validate_completed_manifest(source, valid)
    check(valid_result["passed"], f"Valid manifest failed: {valid_result['errors']}")

    overflow = copy.deepcopy(valid)
    overflow["narration_blocks"][0]["hard_end"] = 8.5
    check(
        "scene_lock_mismatch:NAR_0001" in story.validate_completed_manifest(source, overflow)["errors"],
        "Scene overflow was not blocked",
    )

    too_long = copy.deepcopy(valid)
    too_long_text = "This narration contains far too many unnecessary words and cannot possibly fit inside the approved scene slot."
    too_long["narration_blocks"][0]["text"] = too_long_text
    too_long["narration_blocks"][0]["word_count"] = story.spoken_word_count(too_long_text)
    too_long["subtitle_cues"][0]["lines"] = [too_long_text]
    check(
        "word_budget_exceeded:NAR_0001" in story.validate_completed_manifest(source, too_long)["errors"],
        "Word overflow was not blocked",
    )

    protected = copy.deepcopy(valid)
    protected["narration_blocks"][0].update(
        {"scene_id": "SCN_0002", "slot_id": "SLOT_0002", "planned_start": 8.15, "hard_end": 10.75}
    )
    protected_result = story.validate_completed_manifest(source, protected)
    check(
        "protected_slot_used:NAR_0001" in protected_result["errors"]
        and "protected_sfx_overlap:NAR_0001" in protected_result["errors"],
        "Protected SFX was not blocked",
    )

    french = copy.deepcopy(valid)
    french_text = "Il comprend alors que la vérité était cachée depuis le début."
    french["narration_blocks"][0]["text"] = french_text
    french["narration_blocks"][0]["word_count"] = story.spoken_word_count(french_text)
    french["subtitle_cues"][0]["lines"] = [french_text]
    check(
        "non_english_text:NAR_0001" in story.validate_completed_manifest(source, french)["errors"],
        "French narration was not blocked",
    )

    print(json.dumps({"status": "passed", "contract": story.NARRATOR_STORY_PROMPT_REVISION, "checks": 5}, indent=2))


if __name__ == "__main__":
    main()
