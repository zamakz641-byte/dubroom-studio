from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any


NARRATOR_STORY_KIND = "dubroom_narrator_story_manifest"
NARRATOR_STORY_SCHEMA_VERSION = 1
NARRATOR_STORY_MODE = "narrator_story"
NARRATOR_STORY_PROMPT_REVISION = "narrator-story-scene-lock-20260811-v1"
NARRATOR_STORY_TARGET_LANGUAGE = "en"
NARRATOR_DELIVERIES = {
    "neutral",
    "intimate",
    "tense",
    "urgent",
    "somber",
    "awed",
    "relieved",
}
DUCKING_PROFILES = {"none", "narration_standard", "narration_strong"}
SFX_POLICIES = {"protected", "clear", "duckable"}
EDITABLE_ROOT_FIELDS = {
    "status",
    "story_bible",
    "narration_blocks",
    "subtitle_cues",
    "validation",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _same_time(left: Any, right: Any, tolerance: float = 0.001) -> bool:
    return abs(_float(left) - _float(right)) <= tolerance


def spoken_word_count(text: str) -> int:
    return len(re.findall(r"\S+", str(text or "").strip()))


def _normalized_spoken_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _looks_clearly_french(value: str) -> bool:
    tokens = re.findall(r"[a-zàâçéèêëîïôûùüÿœæ'-]+", str(value or "").lower())
    if len(tokens) < 4:
        return False
    french = {
        "le", "la", "les", "des", "du", "une", "que", "qui", "dans",
        "avec", "pour", "mais", "donc", "sur", "aux", "est", "sont",
        "était", "cette", "ces", "son", "ses", "leur", "leurs", "nous",
        "vous", "ils", "elles", "pas", "plus", "comme", "alors", "tout",
    }
    english = {
        "the", "a", "an", "and", "or", "but", "in", "with", "for",
        "is", "are", "was", "were", "this", "that", "his", "her", "their",
        "he", "she", "they", "we", "you", "not", "as", "then", "all",
    }
    french_hits = sum(token in french for token in tokens)
    english_hits = sum(token in english for token in tokens)
    accented = bool(re.search(r"[àâçéèêëîïôûùüÿœæ]", str(value or "").lower()))
    return bool(
        (french_hits >= 3 and french_hits >= english_hits * 2)
        or (accented and french_hits >= 2 and french_hits > english_hits)
    )


def immutable_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in manifest.items()
        if key not in EDITABLE_ROOT_FIELDS and key != "contract_fingerprint"
    }


def build_narrator_story_manifest(
    *,
    project_id: str,
    project_name: str,
    duration_seconds: float,
    source_fingerprint: str,
    source_tracks: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
    narration_slots: list[dict[str, Any]],
    sfx_intervals: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the isolated, scene-locked narrator-story exchange manifest."""
    manifest: dict[str, Any] = {
        "kind": NARRATOR_STORY_KIND,
        "schema_version": NARRATOR_STORY_SCHEMA_VERSION,
        "dubbing_mode": NARRATOR_STORY_MODE,
        "target_language": NARRATOR_STORY_TARGET_LANGUAGE,
        "prompt_revision": NARRATOR_STORY_PROMPT_REVISION,
        "project_id": str(project_id),
        "project_name": str(project_name),
        "media": {
            "duration_seconds": round(float(duration_seconds), 3),
            "speed": 1.0,
            "source_fingerprint": str(source_fingerprint),
        },
        "source_tracks": copy.deepcopy(source_tracks),
        "evidence": copy.deepcopy(evidence),
        "scenes": copy.deepcopy(scenes),
        "narration_slots": copy.deepcopy(narration_slots),
        "sfx_intervals": copy.deepcopy(sfx_intervals),
        "status": "prepared",
        "story_bible": {},
        "narration_blocks": [],
        "subtitle_cues": [],
        "validation": {},
    }
    manifest["contract_fingerprint"] = _fingerprint(immutable_payload(manifest))
    input_errors = validate_prepared_manifest(manifest)
    if input_errors:
        raise ValueError("Invalid narrator-story manifest: " + "; ".join(input_errors))
    return manifest


def validate_prepared_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = {
        "kind": NARRATOR_STORY_KIND,
        "schema_version": NARRATOR_STORY_SCHEMA_VERSION,
        "dubbing_mode": NARRATOR_STORY_MODE,
        "target_language": NARRATOR_STORY_TARGET_LANGUAGE,
        "prompt_revision": NARRATOR_STORY_PROMPT_REVISION,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            errors.append(f"invalid_{key}")

    duration = _float((manifest.get("media") or {}).get("duration_seconds"))
    if duration <= 0:
        errors.append("invalid_media_duration")
    if _float((manifest.get("media") or {}).get("speed")) != 1.0:
        errors.append("source_speed_must_be_1_0")

    evidence_ids: set[str] = set()
    for item in manifest.get("evidence") or []:
        evidence_id = str((item or {}).get("evidence_id") or "")
        if not evidence_id or evidence_id in evidence_ids:
            errors.append("invalid_or_duplicate_evidence_id")
        evidence_ids.add(evidence_id)

    scenes: dict[str, dict[str, Any]] = {}
    for item in manifest.get("scenes") or []:
        scene_id = str((item or {}).get("scene_id") or "")
        start = _float((item or {}).get("start"))
        end = _float((item or {}).get("end"))
        if not scene_id or scene_id in scenes or start < 0 or end <= start or end > duration + 0.001:
            errors.append(f"invalid_scene:{scene_id or '?'}")
            continue
        scenes[scene_id] = item

    slot_ids: set[str] = set()
    for item in manifest.get("narration_slots") or []:
        slot_id = str((item or {}).get("slot_id") or "")
        scene_id = str((item or {}).get("scene_id") or "")
        scene = scenes.get(scene_id)
        start = _float((item or {}).get("start"))
        end = _float((item or {}).get("end"))
        safe_start = _float((item or {}).get("safe_start"))
        safe_end = _float((item or {}).get("safe_end"))
        policy = str((item or {}).get("sfx_policy") or "")
        allowed = set((item or {}).get("allowed_evidence_ids") or [])
        valid = bool(
            slot_id
            and slot_id not in slot_ids
            and scene
            and _float(scene.get("start")) <= start <= safe_start < safe_end <= end <= _float(scene.get("end"))
            and policy in SFX_POLICIES
            and int((item or {}).get("max_words") or 0) >= 0
            and int((item or {}).get("ideal_words") or 0) >= 0
            and allowed.issubset(evidence_ids)
        )
        if not valid:
            errors.append(f"invalid_slot:{slot_id or '?'}")
        slot_ids.add(slot_id)

    expected_fingerprint = _fingerprint(immutable_payload(manifest))
    if manifest.get("contract_fingerprint") != expected_fingerprint:
        errors.append("contract_fingerprint_mismatch")
    return errors


def validate_completed_manifest(
    source: dict[str, Any],
    completed: dict[str, Any],
) -> dict[str, Any]:
    errors = validate_prepared_manifest(source)
    if immutable_payload(source) != immutable_payload(completed):
        errors.append("immutable_evidence_changed")
    if completed.get("contract_fingerprint") != source.get("contract_fingerprint"):
        errors.append("contract_fingerprint_changed")
    if completed.get("status") != "scripted":
        errors.append("status_not_scripted")

    evidence_ids = {
        str(item.get("evidence_id") or "")
        for item in source.get("evidence") or []
        if isinstance(item, dict)
    }
    slots = {
        str(item.get("slot_id") or ""): item
        for item in source.get("narration_slots") or []
        if isinstance(item, dict)
    }
    scenes = {
        str(item.get("scene_id") or ""): item
        for item in source.get("scenes") or []
        if isinstance(item, dict)
    }
    protected_intervals = [
        item
        for item in source.get("sfx_intervals") or []
        if isinstance(item, dict) and bool(item.get("protected"))
    ]

    blocks_by_id: dict[str, dict[str, Any]] = {}
    previous_end = -1.0
    for index, block in enumerate(completed.get("narration_blocks") or [], start=1):
        if not isinstance(block, dict):
            errors.append(f"invalid_block:{index}")
            continue
        block_id = str(block.get("block_id") or "")
        expected_id = f"NAR_{index:04d}"
        slot_id = str(block.get("slot_id") or "")
        scene_id = str(block.get("scene_id") or "")
        slot = slots.get(slot_id)
        scene = scenes.get(scene_id)
        start = _float(block.get("planned_start"))
        end = _float(block.get("hard_end"))
        text = _normalized_spoken_text(block.get("text") or "")
        claimed_words = int(block.get("word_count") or 0)
        actual_words = spoken_word_count(text)
        delivery = str(block.get("delivery") or "")
        ducking = str(block.get("ducking_profile") or "")
        supporting = set(block.get("evidence_ids") or [])

        if block_id != expected_id or block_id in blocks_by_id:
            errors.append(f"invalid_block_id:{block_id or index}")
        if not slot or not scene or str(slot.get("scene_id") or "") != scene_id:
            errors.append(f"invalid_block_slot_or_scene:{block_id or index}")
        else:
            if not _same_time(start, slot.get("safe_start")) or not _same_time(end, slot.get("safe_end")):
                errors.append(f"scene_lock_mismatch:{block_id}")
            if start < _float(scene.get("start")) or end > _float(scene.get("end")):
                errors.append(f"scene_boundary_overflow:{block_id}")
            if str(slot.get("sfx_policy") or "") == "protected":
                errors.append(f"protected_slot_used:{block_id}")
            if actual_words > int(slot.get("max_words") or 0):
                errors.append(f"word_budget_exceeded:{block_id}")
            if not supporting or not supporting.issubset(evidence_ids):
                errors.append(f"invalid_evidence_reference:{block_id}")
            if not supporting.issubset(set(slot.get("allowed_evidence_ids") or [])):
                errors.append(f"evidence_not_allowed_in_slot:{block_id}")

        if not text or actual_words != claimed_words:
            errors.append(f"word_count_mismatch:{block_id or index}")
        if _looks_clearly_french(text):
            errors.append(f"non_english_text:{block_id or index}")
        if delivery not in NARRATOR_DELIVERIES:
            errors.append(f"invalid_delivery:{block_id or index}")
        intensity = int(block.get("delivery_intensity") or 0)
        if not 0 <= intensity <= 100:
            errors.append(f"invalid_delivery_intensity:{block_id or index}")
        if ducking not in DUCKING_PROFILES:
            errors.append(f"invalid_ducking_profile:{block_id or index}")
        if start < previous_end - 0.001:
            errors.append(f"overlapping_block:{block_id or index}")
        for interval in protected_intervals:
            if start < _float(interval.get("end")) and end > _float(interval.get("start")):
                errors.append(f"protected_sfx_overlap:{block_id or index}")
                break
        previous_end = max(previous_end, end)
        blocks_by_id[block_id] = block

    cues_by_block: dict[str, list[dict[str, Any]]] = {}
    for index, cue in enumerate(completed.get("subtitle_cues") or [], start=1):
        if not isinstance(cue, dict):
            errors.append(f"invalid_subtitle_cue:{index}")
            continue
        if str(cue.get("cue_id") or "") != f"SUB_{index:04d}":
            errors.append(f"invalid_subtitle_cue_id:{index}")
        block_id = str(cue.get("block_id") or "")
        block = blocks_by_id.get(block_id)
        lines = cue.get("lines") or []
        if not block or not isinstance(lines, list) or not 1 <= len(lines) <= 2:
            errors.append(f"invalid_subtitle_cue:{index}")
            continue
        if _float(cue.get("start")) < _float(block.get("planned_start")) - 0.001:
            errors.append(f"subtitle_before_block:{index}")
        if _float(cue.get("end")) > _float(block.get("hard_end")) + 0.001:
            errors.append(f"subtitle_after_block:{index}")
        cues_by_block.setdefault(block_id, []).append(cue)

    for block_id, block in blocks_by_id.items():
        cue_text = " ".join(
            " ".join(str(line) for line in cue.get("lines") or [])
            for cue in cues_by_block.get(block_id, [])
        )
        if _normalized_spoken_text(cue_text) != _normalized_spoken_text(block.get("text") or ""):
            errors.append(f"subtitle_text_mismatch:{block_id}")

    unique_errors = sorted(set(errors))
    return {
        "passed": not unique_errors,
        "errors": unique_errors,
        "narration_block_count": len(blocks_by_id),
        "subtitle_cue_count": sum(len(items) for items in cues_by_block.values()),
        "source_duration_seconds": _float((source.get("media") or {}).get("duration_seconds")),
        "source_speed": _float((source.get("media") or {}).get("speed")),
    }
