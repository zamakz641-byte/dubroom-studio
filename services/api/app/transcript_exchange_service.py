from __future__ import annotations

import hashlib
import json
import math
import re
import wave
from array import array
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .narrative_profiles import exchange_contract


MULTISPEAKER_SCHEMA_VERSION = 3
MULTISPEAKER_PROMPT_REVISION = "english-timing-strict-20260811-r5"
MULTISPEAKER_ENGLISH_TIMING_PROMPT_REVISION = MULTISPEAKER_PROMPT_REVISION
MULTISPEAKER_CASTING_PROMPT_REVISIONS = {
    "casting-intelligence-20260809-r4",
    "casting-intelligence-20260809-r4-final",
}
MULTISPEAKER_ACCEPTED_PROMPT_REVISIONS = {
    *MULTISPEAKER_CASTING_PROMPT_REVISIONS,
    "subtitle-fusion-20260811-r4",
    MULTISPEAKER_PROMPT_REVISION,
}
SINGLE_SPEAKER_PROMPT_REVISION = "single-speaker-20260809-r1"
SFX_SAFE_DBFS = -24.0

CHAT_SEGMENT_RE = re.compile(
    r'\[\[DUBROOM_SEGMENT\s+(?P<attrs>[^\]]*)\]\]'
    r'(?P<body>.*?)\[\[/DUBROOM_SEGMENT\]\]',
    re.DOTALL | re.IGNORECASE,
)
CHAT_ATTRIBUTE_RE = re.compile(r'(?P<name>[A-Za-z_]+)="(?P<value>[^"]*)"')
CHARACTER_ID_RE = re.compile(r"^(?:CHAR_\d{2,4}|NARRATOR|SYSTEM|UNKNOWN)$")
OMNIVOICE_TAGS = {
    "",
    "[laughter]",
    "[sigh]",
    "[confirmation-en]",
    "[question-en]",
    "[question-ah]",
    "[question-oh]",
    "[question-ei]",
    "[question-yi]",
    "[surprise-ah]",
    "[surprise-oh]",
    "[surprise-wa]",
    "[surprise-yo]",
    "[dissatisfaction-hnn]",
}
EMOTION_LABELS = {
    "neutral", "happy", "amused", "sad", "angry", "afraid", "surprised",
    "disgusted", "tender", "determined", "whispering", "exhausted",
}
SPEECH_TYPES = {"narration", "dialogue", "inner_monologue", "system", "reaction"}
VOICE_KEYS = {
    "narrator", "mc", "female_lead", "antagonist", "supporting",
    "system", "creature", "unknown",
}
SEX_LABELS = {"male", "female", "uncertain"}
AGE_GROUPS = {"child", "teen", "young_adult", "adult", "elderly", "unknown"}
IMPORTANCE_LEVELS = {"primary", "major", "supporting", "minor", "crowd"}
PRESENCE_LEVELS = {"low", "medium", "high"}
EMOTIONALITY_LEVELS = {"restrained", "balanced", "expressive"}
CASTING_REASONS = {
    "role", "dialogue_volume", "recurrence", "narrative_necessity",
    "narrator_fallback", "ambiguous",
}
CASTING_STATUSES = {"auto", "needs_review", "locked"}
VOICE_ARCHETYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
TIMESTAMP_RE = re.compile(
    r"^(?:(?P<hours>\d+):)?(?P<minutes>\d+):(?P<seconds>\d+(?:[.,]\d+)?)$"
)


def timestamp_seconds(value: str) -> float:
    match = TIMESTAMP_RE.match(str(value or "").strip())
    if not match:
        return 0.0
    return (
        int(match.group("hours") or 0) * 3600
        + int(match.group("minutes")) * 60
        + float(match.group("seconds").replace(",", "."))
    )


def segment_duration(segment: dict[str, Any]) -> float:
    return max(
        0.1,
        timestamp_seconds(str(segment.get("end") or ""))
        - timestamp_seconds(str(segment.get("start") or "")),
    )


def _looks_clearly_french(value: str) -> bool:
    """Conservatively reject French prose in English-only R5 output."""
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


def exchange_timestamp(seconds: float) -> str:
    milliseconds = max(0, round(float(seconds or 0) * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    whole_seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{milliseconds:03d}"


def _pcm_dbfs(raw: bytes, sample_width: int) -> float | None:
    """Return a lightweight RMS estimate for PCM WAV data."""
    if not raw or sample_width not in {1, 2, 3, 4}:
        return None
    values: list[int] | array
    if sample_width == 1:
        values = [value - 128 for value in raw]
    elif sample_width in {2, 4}:
        typecode = "h" if sample_width == 2 else "i"
        pcm = array(typecode)
        pcm.frombytes(raw[: len(raw) - (len(raw) % sample_width)])
        values = pcm
    else:
        values = [
            int.from_bytes(raw[offset : offset + 3], "little", signed=True)
            for offset in range(0, len(raw) - 2, 3)
        ]
    if not values:
        return None
    stride = max(1, len(values) // 250_000)
    sampled = values[::stride]
    mean_square = sum(float(value) * float(value) for value in sampled) / len(sampled)
    if mean_square <= 0:
        return -96.0
    full_scale = float(2 ** (sample_width * 8 - 1))
    return round(20.0 * math.log10(math.sqrt(mean_square) / full_scale), 1)


def _annotate_bridge_audio_activity(
    project_dir: Path | None,
    rows: list[dict[str, Any]],
) -> None:
    """Mark narration gaps that are quiet enough not to mask useful SFX."""
    if project_dir is None:
        return
    separation = project_dir / "audio" / "separation"
    track = separation / "sfx.wav"
    if not track.is_file():
        track = separation / "bed.wav"
    if not track.is_file():
        return
    try:
        with wave.open(str(track), "rb") as source:
            frame_rate = source.getframerate()
            sample_width = source.getsampwidth()
            total_frames = source.getnframes()
            for row in rows:
                slot = row.get("bridge_slot") or {}
                if not bool(slot.get("available")):
                    continue
                start = timestamp_seconds(str(slot.get("start") or ""))
                end = timestamp_seconds(str(slot.get("end") or ""))
                start_frame = min(total_frames, max(0, round(start * frame_rate)))
                frame_count = min(
                    max(0, total_frames - start_frame),
                    max(1, round(max(0.0, end - start) * frame_rate)),
                )
                source.setpos(start_frame)
                dbfs = _pcm_dbfs(source.readframes(frame_count), sample_width)
                if dbfs is None:
                    continue
                slot["bed_activity_dbfs"] = dbfs
                slot["sfx_safe"] = dbfs <= SFX_SAFE_DBFS
                slot["bed_activity"] = (
                    "quiet" if dbfs <= -30.0 else "moderate" if dbfs <= SFX_SAFE_DBFS else "strong"
                )
    except (OSError, EOFError, wave.Error):
        return


TTS_LEAD_IN_SECONDS = 0.12
TTS_TAIL_OUT_SECONDS = 0.18


def recommended_word_range(duration_seconds: float) -> dict[str, int]:
    """Return a practical spoken-word target for one dubbing segment.

    The TTS stage preserves a short 120 ms lead-in and 180 ms tail. These targets
    remain deliberately broad so the script can use complete sentences without
    forcing the voice to race or encouraging another large silent gap.
    """
    duration = max(0.1, float(duration_seconds or 0.0))
    minimum = max(1, round(duration * 1.90))
    ideal = max(minimum, round(duration * 2.50))
    maximum = max(ideal + 1, round(duration * 3.05))
    return {"minimum": minimum, "ideal": ideal, "maximum": maximum}


def subtitle_evidence(segment: dict[str, Any]) -> list[dict[str, Any]]:
    raw = segment.get("subtitle_evidence")
    if raw is None:
        raw = segment.get("subtitleEvidence")
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        source = str(item.get("source") or "").strip()
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
            overlap_ratio = float(item.get("overlap_ratio"))
            match_confidence = float(item.get("match_confidence"))
        except (TypeError, ValueError):
            continue
        if not text or not source or end < start:
            continue
        candidate = {
            "text": text,
            "start": start,
            "end": end,
            "source": source,
            "overlap_ratio": overlap_ratio,
            "match_confidence": match_confidence,
        }
        if str(item.get("revision") or "").strip():
            candidate["revision"] = str(item["revision"]).strip()
        result.append(candidate)
    return result


def source_hash(
    segment: dict[str, Any],
    include_subtitle_evidence: bool = True,
) -> str:
    parts = [
        str(segment.get("id") or ""),
        str(segment.get("start") or ""),
        str(segment.get("end") or ""),
        str(segment.get("acousticSpeaker") or segment.get("speaker") or ""),
        str(segment.get("sourceText") or "").strip(),
    ]
    evidence = subtitle_evidence(segment) if include_subtitle_evidence else []
    if evidence:
        parts.append(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    payload = "\0".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def transcript_fingerprint(
    segments: list[dict[str, Any]],
    subtitle_evidence_revision: str | None = None,
    include_subtitle_evidence: bool = True,
) -> str:
    payload = []
    has_subtitle_evidence = False
    for segment in segments:
        row = {
            "id": str(segment.get("id") or ""),
            "start": str(segment.get("start") or ""),
            "end": str(segment.get("end") or ""),
            "speaker": str(segment.get("acousticSpeaker") or segment.get("speaker") or ""),
            "source": str(segment.get("sourceText") or "").strip(),
        }
        evidence = subtitle_evidence(segment) if include_subtitle_evidence else []
        if evidence:
            row["subtitle_evidence"] = evidence
            has_subtitle_evidence = True
        payload.append(row)
    revision = str(subtitle_evidence_revision or "").strip()
    fingerprint_payload: Any = payload
    if revision or has_subtitle_evidence:
        fingerprint_payload = {
            "subtitle_evidence_revision": revision or None,
            "segments": payload,
        }
    return hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def build_context_groups(
    segments: list[dict[str, Any]],
    *,
    preferred_seconds: float = 6.8,
    maximum_seconds: float = 10.5,
    maximum_gap_seconds: float = 0.55,
) -> list[dict[str, Any]]:
    """CONTINUOUS_NARRATION_V2_20260803: use the same windows as grouped TTS."""
    visible = [
        segment
        for segment in segments
        if str(segment.get("sourceText") or "").strip()
    ]
    if not visible:
        return []
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for segment in visible:
        if not current:
            current = [segment]
            continue
        current_start = timestamp_seconds(str(current[0].get("start") or ""))
        current_end = timestamp_seconds(str(current[-1].get("end") or ""))
        next_start = timestamp_seconds(str(segment.get("start") or ""))
        next_end = timestamp_seconds(str(segment.get("end") or ""))
        current_duration = max(0.1, current_end - current_start)
        projected_duration = max(0.1, next_end - current_start)
        closes_sentence = bool(
            re.search(
                r"""[.!?…]["'”’)]*$""",
                str(current[-1].get("sourceText") or "").strip(),
            )
        )
        can_join = (
            str(segment.get("speaker") or "")
            == str(current[-1].get("speaker") or "")
            and max(0.0, next_start - current_end) <= maximum_gap_seconds
            and projected_duration <= maximum_seconds
            and not (current_duration >= preferred_seconds and closes_sentence)
        )
        if can_join:
            current.append(segment)
        else:
            groups.append(current)
            current = [segment]
    if current:
        groups.append(current)

    result: list[dict[str, Any]] = []
    for index, members in enumerate(groups, start=1):
        start = timestamp_seconds(str(members[0].get("start") or ""))
        end = timestamp_seconds(str(members[-1].get("end") or ""))
        duration = max(0.1, end - start)
        result.append(
            {
                "id": f"context-{index:04d}",
                "member_ids": [str(member.get("id") or "") for member in members],
                "speaker": str(members[0].get("speaker") or ""),
                "start": str(members[0].get("start") or ""),
                "end": str(members[-1].get("end") or ""),
                "duration_seconds": round(duration, 3),
                "recommended_words": recommended_word_range(duration),
                "source_context": " ".join(
                    str(member.get("sourceText") or "").strip()
                    for member in members
                    if str(member.get("sourceText") or "").strip()
                ),
            }
        )
    return result


def build_exchange_payload(
    *,
    project_id: str,
    project_name: str,
    state: dict[str, Any],
    project_dir: Path | None = None,
) -> dict[str, Any]:
    dubbing_mode = str(state.get("dubbing_mode") or "single").strip().lower()
    if dubbing_mode not in {"single", "multi"}:
        dubbing_mode = "single"
    evidence_revision = str(state.get("subtitle_evidence_revision") or "").strip()
    segments = [
        segment
        for segment in (state.get("segments") or [])
        if isinstance(segment, dict)
    ]
    groups = build_context_groups(segments)
    group_by_member: dict[str, dict[str, Any]] = {}
    for group in groups:
        for segment_id in group["member_ids"]:
            group_by_member[segment_id] = group
    acoustic = _load_acoustic_evidence(
        project_dir,
        segments,
        source_language=str(state.get("source_language") or "auto"),
    )
    rows = []
    for segment in segments:
        segment_id = str(segment.get("id") or "")
        duration = segment_duration(segment)
        group = group_by_member.get(segment_id)
        row = {
                "id": segment_id,
                "source_hash": source_hash(
                    segment,
                    include_subtitle_evidence=dubbing_mode == "multi",
                ),
                "start": str(segment.get("start") or ""),
                "end": str(segment.get("end") or ""),
                "duration_seconds": round(duration, 3),
                "recommended_words": recommended_word_range(duration),
                "temporary_cluster": acoustic["cluster_by_segment"].get(
                    segment_id,
                    str(segment.get("acousticSpeaker") or segment.get("speaker") or ""),
                ),
                "speaker": str(segment.get("speaker") or ""),
                "source_text": str(segment.get("sourceText") or "").strip(),
                "draft_translation": str(
                    segment.get("translatedText")
                    or segment.get("adaptedText")
                    or ""
                ).strip(),
                "target_text": "",
                "character_id": "",
                "character_name": "",
                "character_role": "",
                "character_confidence": None,
                "emotion": "neutral",
                "emotion_intensity": 0,
                "omnivoice_tag": "",
                "context_id": str((group or {}).get("id") or ""),
            }
        evidence = subtitle_evidence(segment)
        if dubbing_mode == "multi" and evidence:
            row["subtitle_evidence"] = evidence
        rows.append(row)
    previous_end = 0.0
    for row in rows:
        start_seconds = timestamp_seconds(str(row.get("start") or ""))
        gap_seconds = max(0.0, start_seconds - previous_end)
        usable_bridge_seconds = max(0.0, gap_seconds - 0.30)
        bridge_available = usable_bridge_seconds >= 1.5
        row["preceding_gap_seconds"] = round(gap_seconds, 3)
        row["bridge_slot"] = {
            "available": bridge_available,
            "start": exchange_timestamp(previous_end + 0.15),
            "end": exchange_timestamp(max(previous_end + 0.15, start_seconds - 0.15)),
            "max_duration_seconds": round(usable_bridge_seconds, 3),
            "max_words": max(0, round(usable_bridge_seconds * 2.4)),
        }
        previous_end = max(
            previous_end,
            timestamp_seconds(str(row.get("end") or "")),
        )
    _annotate_bridge_audio_activity(project_dir, rows)
    narrative_profile = str(
        state.get("narrative_profile") or "natural_recap"
    ).strip()
    narrative_instructions = str(
        state.get("narrative_instructions") or ""
    ).strip()
    speaker_sections = _build_speaker_sections(rows) if dubbing_mode == "multi" else []
    section_by_segment = {
        segment_id: section["section_id"]
        for section in speaker_sections
        for segment_id in section.pop("_segment_ids")
    }
    for row in rows:
        row["section_id"] = section_by_segment.get(row["id"], "")
    result = {
        "schema_version": MULTISPEAKER_SCHEMA_VERSION if dubbing_mode == "multi" else 2,
        "kind": "dubroom_transcript_exchange",
        "project_id": project_id,
        "project_name": project_name,
        "revision": int(state.get("revision") or 0),
        "source_language": state.get("source_language") or "auto",
        "target_language": state.get("target_language") or "fr",
        "dubbing_mode": dubbing_mode,
        "narrative_profile": narrative_profile,
        "narrative_instructions": narrative_instructions,
        "narrative_contract": exchange_contract(
            narrative_profile,
            narrative_instructions,
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "transcript_fingerprint": transcript_fingerprint(
            segments,
            evidence_revision if dubbing_mode == "multi" else None,
            include_subtitle_evidence=dubbing_mode == "multi",
        ),
        "translation_goal": {
            "priority": [
                "Preserve every fact, name, number, negation, relationship, cause and action.",
                "Keep NARRATOR as one external third-person storyteller; give the MC voice only to actual dialogue or explicit inner monologue.",
                "Split mixed source segments into ordered voice units whenever narration, dialogue, inner thought, system speech or another character coexist.",
                "Convert first-person recap narration into names and third-person pronouns; retain first person only inside an identified character voice unit.",
                "Use complete subject-verb sentences and natural transitions instead of headline fragments or clipped slogans.",
                "Keep every segment close to its own duration at natural speed while reserving 0.12 seconds before speech and 0.18 seconds after it.",
                "Use context only for understanding; never move facts or wording into another segment.",
                "Use temporary_cluster only as acoustic evidence. It is not a final identity and several clusters may belong to the same character.",
                "Resolve one stable character_id per voice unit from the whole story, dialogue context, names and conversational continuity.",
                "Separate identity from rendering: keep recurring CHAR IDs even when a minor character is rendered by NARRATOR.",
                "Classify each recurring character as primary, major, supporting, minor or crowd before deciding whether it deserves a dedicated voice.",
                "Use dedicated voices for primary/major characters; minor/crowd default to NARRATOR; supporting characters need recurrence, dialogue volume or narrative necessity.",
                "Choose a stable voice_archetype from age, sex, personality and presence; emotion changes acting, never character identity or archetype.",
                "Use narrator bridges only inside approved bridge slots and only from facts already supported by nearby context.",
                "Use the available merged duration; never collapse a complete 4-7 second passage into a tiny summary.",
                "Rephrase fully when needed; never summarize or delete information merely to make the line shorter.",
            ],
            "timing_rule": (
                "Match each segment's duration_seconds and recommended_words at natural speech speed. "
                "DubRoom preserves 0.12 seconds of lead-in and 0.18 seconds of tail silence around the generated voice. "
                "Return one or more ordered voice_units for every segment ID. Context groups are read-only context; "
                "do not merge source segments or transfer information between them."
            ),
        },
        "context_groups": groups,
        "speaker_hints": acoustic["speaker_hints"],
        "character_registry": [],
        "speaker_sections": speaker_sections,
        "segments": rows,
    }
    if dubbing_mode == "multi" and evidence_revision:
        result["subtitle_evidence_revision"] = evidence_revision
    return result


def _build_speaker_sections(
    rows: list[dict[str, Any]],
    section_size: int = 60,
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for offset in range(0, len(rows), section_size):
        members = rows[offset : offset + section_size]
        if not members:
            continue
        sections.append(
            {
                "section_id": f"section-{len(sections) + 1:03d}",
                "start": members[0]["start"],
                "end": members[-1]["end"],
                "first_segment_id": members[0]["id"],
                "last_segment_id": members[-1]["id"],
                "detected_speakers": [],
                "_segment_ids": [row["id"] for row in members],
            }
        )
    return sections


def _load_acoustic_evidence(
    project_dir: Path | None,
    segments: list[dict[str, Any]],
    source_language: str = "auto",
) -> dict[str, Any]:
    """Load compact Sherpa evidence without treating clusters as identities."""
    empty = {"cluster_by_segment": {}, "speaker_hints": {}}
    # ERES2NETV2_CHINESE_HINT_R1
    source_language = str(source_language or "auto").strip().lower()
    is_mandarin = source_language in {"zh", "zh-cn", "zh-tw", "cmn", "chinese", "mandarin"}
    if project_dir is None:
        return empty
    manifest_path = project_dir / "analysis" / "diarization" / "diarization-manifest.json"
    if not manifest_path.is_file():
        return empty
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return empty
    turns = [item for item in manifest.get("turns") or [] if isinstance(item, dict)]
    profiles = {
        str(item.get("speaker") or ""): item
        for item in manifest.get("speaker_profiles") or []
        if isinstance(item, dict) and str(item.get("speaker") or "")
    }
    cluster_by_segment: dict[str, str] = {}
    for segment in segments:
        segment_id = str(segment.get("id") or "")
        start = timestamp_seconds(str(segment.get("start") or ""))
        end = max(start + 0.01, timestamp_seconds(str(segment.get("end") or "")))
        overlap_by_cluster: dict[str, float] = {}
        for turn in turns:
            cluster = str(turn.get("speaker") or "")
            turn_start = float(turn.get("start") or 0.0)
            turn_end = float(turn.get("end") or turn_start)
            overlap = max(0.0, min(end, turn_end) - max(start, turn_start))
            if overlap:
                overlap_by_cluster[cluster] = overlap_by_cluster.get(cluster, 0.0) + overlap
        if overlap_by_cluster:
            cluster_by_segment[segment_id] = max(overlap_by_cluster, key=overlap_by_cluster.get)
        else:
            cluster_by_segment[segment_id] = str(
                segment.get("acousticSpeaker") or segment.get("speaker") or ""
            )
    used_clusters = {value for value in cluster_by_segment.values() if value}
    hints: dict[str, dict[str, Any]] = {}
    for cluster in sorted(used_clusters):
        profile = profiles.get(cluster, {})
        if (
            is_mandarin
            and str(profile.get("demographic_model") or "") == "DubRoom/ERes2NetV2-AISHELL3-R1"
        ):
            profile = dict(profile)
            meta_gender = str(profile.get("meta_gender") or "uncertain").lower()
            meta_gender_conf = float(profile.get("meta_gender_confidence") or 0.0)
            meta_samples = int(profile.get("demographic_samples_analyzed") or 0)
            base_gender = str(profile.get("sex") or profile.get("gender") or "uncertain").lower()
            base_gender_conf = float(profile.get("sex_confidence") or 0.0)
            if meta_gender in {"male", "female"} and meta_samples >= 3:
                if base_gender == meta_gender:
                    profile["sex"] = meta_gender; profile["sex_confidence"] = max(base_gender_conf, meta_gender_conf)
                elif meta_gender_conf >= 0.90:
                    profile["sex"] = meta_gender; profile["sex_confidence"] = meta_gender_conf
                elif meta_gender_conf >= 0.78 and base_gender_conf < 0.60:
                    profile["sex"] = meta_gender; profile["sex_confidence"] = meta_gender_conf
                elif meta_gender_conf >= 0.78 and base_gender in {"male", "female"}:
                    profile["sex"] = "uncertain"; profile["sex_confidence"] = min(0.65, max(meta_gender_conf, base_gender_conf))
            meta_age = str(profile.get("meta_age_group") or "unknown").lower()
            meta_age_conf = float(profile.get("meta_age_confidence") or 0.0)
            if meta_age in {"child", "teen", "young_adult", "adult", "elderly"} and meta_age_conf >= 0.58 and meta_samples >= 3:
                profile["age_group"] = meta_age; profile["age_confidence"] = meta_age_conf
        sex = str(profile.get("sex") or profile.get("gender") or "uncertain").lower()
        if sex not in {"male", "female"}:
            sex = "uncertain"
        pitch_samples = int(profile.get("pitch_samples") or 0)
        median_pitch = profile.get("median_pitch_hz")
        sex_confidence = profile.get("sex_confidence")
        if sex_confidence is None:
            sample_factor = min(1.0, pitch_samples / 80.0)
            distance = 0.0
            if isinstance(median_pitch, (int, float)):
                distance = min(1.0, abs(float(median_pitch) - 162.5) / 55.0)
            sex_confidence = round(min(0.85, sample_factor * (0.45 + 0.5 * distance)), 2)
        sex_confidence = min(0.85, float(sex_confidence or 0.0))
        age_group = str(profile.get("age_group") or "")
        age_confidence = profile.get("age_confidence")
        if not age_group:
            if isinstance(median_pitch, (int, float)) and median_pitch >= 300 and pitch_samples >= 12:
                age_group, age_confidence = "child", 0.34
            elif isinstance(median_pitch, (int, float)) and median_pitch >= 245 and pitch_samples >= 20:
                age_group, age_confidence = "teen", 0.22
            else:
                age_group, age_confidence = "unknown", 0.0
        hints[cluster] = {
            "sex": sex,
            "sex_confidence": sex_confidence,
            "age_group": age_group,
            "age_confidence": float(age_confidence or 0.0),
        }
    return {"cluster_by_segment": cluster_by_segment, "speaker_hints": hints}


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return cleaned[:48] or "dubroom-project"


def _chat_header(payload: dict[str, Any], part: int, total: int) -> str:
    contract = payload.get("narrative_contract") or exchange_contract(
        str(payload.get("narrative_profile") or "natural_recap"),
        str(payload.get("narrative_instructions") or ""),
    )
    rules = "\n".join(
        f"- {rule}" for rule in (contract.get("rules") or [])
    )
    return f"""# DubRoom Studio · Translation Chat Pack {part}/{total}

Project: {payload["project_name"]}
Source language: {payload["source_language"]}
Target language: {payload["target_language"]}
Transcript fingerprint: {payload["transcript_fingerprint"]}
Narrative profile: {contract["profile"]}
Point of view: {contract["point_of_view"]}
Narrator role: {contract["narrator_role"]}
Tone: {contract["tone"]}

## Mandatory instructions

Rewrite every SOURCE into natural spoken {payload["target_language"]} using the selected narrative style.
Style direction: {contract["style_instruction"]}
Additional project direction: {contract.get("project_direction") or "None"}
Keep all identifiers and marker lines exactly unchanged.
Fill CHARACTER_ID, CHARACTER_NAME, CHARACTER_ROLE, CHARACTER_CONFIDENCE and TARGET.
Also fill EMOTION, EMOTION_INTENSITY and OMNIVOICE_TAG for every phrase from its scene context.
Read the complete CONTEXT and the whole story before translating its segments.
Return exactly one TARGET for every DUBROOM_SEGMENT, in the same order and with the same ID.
Each TARGET must contain only the information from its own SOURCE; never merge rows or move information between rows.
TEMPORARY_CLUSTER is immutable acoustic evidence, not a character identity. Several clusters may map to the same stable character.
Resolve characters from the complete story, names, who answers whom and scene continuity. Use cautious sex/age hints only as supporting evidence.
Use stable IDs such as CHAR_001, NARRATOR, SYSTEM or UNKNOWN. Never guess an exact numeric age.
Use an OmniVoice tag only for an audible event justified by the source or scene. Never add laughter, sighs or reactions merely to make a line more expressive.
For the current section, fill its detected_speakers registry first, then reuse those stable IDs in every segment. Carry known IDs into later sections.
Narration is external and third-person: convert recap I/we into character names or third-person pronouns.
Keep first-person wording only for dialogue that is unmistakably spoken by a character; never invent quotation marks for narration or inner explanation.
Write complete subject-verb sentences with smooth causal transitions. Avoid headlines, nominal fragments, clipped slogans and chains of tiny sentences.
Match every segment's duration and WORDS range at natural speed. DubRoom preserves 0.12 s before speech and 0.18 s after it; stay near the IDEAL count so no additional dead air is created.
Aim near the IDEAL count and make the line occupy roughly 88-100% of its playable speech window without rushing.
Never remove names, numbers, negations, relationships, causes, consequences or actions.
Prefer idiomatic phrasing when the target language is longer, but never summarize the story into a shorter idea.
Do not add explanations, Markdown fences or commentary to the returned file.

## Narrative and fidelity rules

{rules}

"""


def render_chat_parts(
    payload: dict[str, Any],
    *,
    chunk_size: int = 60,
) -> list[tuple[str, str]]:
    chunk_size = max(10, min(120, int(chunk_size)))
    rows = list(payload["segments"])
    groups = {
        str(group["id"]): group for group in payload.get("context_groups") or []
    }
    total = max(1, (len(rows) + chunk_size - 1) // chunk_size)
    stem = _safe_stem(str(payload["project_id"]))
    files: list[tuple[str, str]] = []
    for part_index, offset in enumerate(range(0, len(rows), chunk_size), start=1):
        selected = rows[offset : offset + chunk_size]
        selected_clusters = {
            str(row.get("temporary_cluster") or "") for row in selected
            if str(row.get("temporary_cluster") or "")
        }
        hints = {
            cluster: (payload.get("speaker_hints") or {}).get(cluster, {})
            for cluster in sorted(selected_clusters)
        }
        lines = [
            _chat_header(payload, part_index, total),
            "## Acoustic hints for this part\n\n"
            + json.dumps(hints, ensure_ascii=False, separators=(",", ":"))
            + "\n",
        ]
        active_context = ""
        for row in selected:
            context_id = str(row.get("context_id") or "")
            if context_id != active_context:
                if active_context:
                    lines.append("[[/DUBROOM_CONTEXT]]\n")
                active_context = context_id
                group = groups.get(context_id, {})
                words = group.get("recommended_words") or {}
                lines.append(
                    f'[[DUBROOM_CONTEXT id="{context_id}" '
                    f'duration="{float(group.get("duration_seconds") or 0):.3f}" '
                    f'words="{int(words.get("minimum") or 0)}-'
                    f'{int(words.get("maximum") or 0)}"]]\n'
                f'CONTEXT: {group.get("source_context") or row["source_text"]}\n'
                )
            segment_words = row.get("recommended_words") or recommended_word_range(
                float(row.get("duration_seconds") or 0.0)
            )
            lines.append(
                f'[[DUBROOM_SEGMENT id="{row["id"]}" '
                f'hash="{row["source_hash"]}" '
                f'temporary_cluster="{row["temporary_cluster"]}" '
                f'duration="{float(row["duration_seconds"]):.3f}" '
                f'words="{int(segment_words.get("minimum") or 1)}-'
                f'{int(segment_words.get("maximum") or 2)}"]]\n'
                f'SOURCE: {row["source_text"]}\n'
                f'TIMING: Aim for {int(segment_words.get("ideal") or 1)} spoken words '
                f'({int(segment_words.get("minimum") or 1)}-'
                f'{int(segment_words.get("maximum") or 2)} acceptable).\n'
                "CHARACTER_ID:\n"
                "CHARACTER_NAME:\n"
                "CHARACTER_ROLE:\n"
                "CHARACTER_CONFIDENCE:\n"
                "EMOTION: neutral\n"
                "EMOTION_INTENSITY: 0\n"
                "OMNIVOICE_TAG:\n"
                "TARGET:\n"
                "[[/DUBROOM_SEGMENT]]\n"
            )
        if active_context:
            lines.append("[[/DUBROOM_CONTEXT]]\n")
        name = f"{stem}-chat-{part_index:02d}-of-{total:02d}.md"
        files.append((name, "\n".join(lines)))
    return files


def render_srt(payload: dict[str, Any]) -> str:
    cues = []
    for index, row in enumerate(payload["segments"], start=1):
        cues.append(
            f"{index}\n"
            f'{_subtitle_timestamp(row["start"], srt=True)} --> '
            f'{_subtitle_timestamp(row["end"], srt=True)}\n'
            f'[{row["id"]}] {row["source_text"]}\n'
        )
    return "\n".join(cues)


def render_vtt(payload: dict[str, Any]) -> str:
    cues = ["WEBVTT\n"]
    for row in payload["segments"]:
        cues.append(
            f'{row["id"]}\n'
            f'{_subtitle_timestamp(row["start"], srt=False)} --> '
            f'{_subtitle_timestamp(row["end"], srt=False)}\n'
            f'[{row["id"]}] {row["source_text"]}\n'
        )
    return "\n".join(cues)


def build_translation_manifest(
    *,
    project_dir: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Return a compact JSON script for external translation."""
    is_multispeaker = str(payload.get("dubbing_mode") or "single") == "multi"
    asr_path = project_dir / "analysis" / "asr_manifest.json"
    asr_payload: dict[str, Any] = {}
    if asr_path.is_file():
        try:
            loaded = json.loads(asr_path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, dict):
                asr_payload = loaded
        except (OSError, json.JSONDecodeError):
            asr_payload = {}
    segments = []
    for row in payload["segments"]:
        segment = {
            "id": row["id"],
            "source_hash": row["source_hash"],
            "start": row["start"],
            "end": row["end"],
            "duration_seconds": row["duration_seconds"],
            "recommended_words": row.get("recommended_words")
            or recommended_word_range(float(row["duration_seconds"])),
            "context_id": row.get("context_id") or "",
            "text": row["source_text"],
            "emotion": "neutral",
            "emotion_intensity": 0,
            "omnivoice_tag": "",
            "translation": "",
        }
        if is_multispeaker:
            segment.update(
                {
                    "preceding_gap_seconds": float(row.get("preceding_gap_seconds") or 0),
                    "bridge_slot": row.get("bridge_slot") or {
                        "available": False,
                        "start": row["start"],
                        "end": row["start"],
                        "max_duration_seconds": 0,
                        "max_words": 0,
                        "sfx_safe": False,
                    },
                    "section_id": row.get("section_id") or "",
                    "temporary_cluster": row["temporary_cluster"],
                    "character_id": "",
                    "character_name": "",
                    "character_role": "",
                    "character_confidence": None,
                    "voice_units": [],
                    "narrator_bridge": {
                        "enabled": False,
                        "translation": "",
                        "emotion": "neutral",
                        "emotion_intensity": 0,
                        "vocal_events": [],
                    },
                }
            )
            if row.get("subtitle_evidence"):
                segment["subtitle_evidence"] = row["subtitle_evidence"]
        segments.append(segment)
    contract = payload.get("narrative_contract") or exchange_contract(
        str(payload.get("narrative_profile") or "natural_recap"),
        str(payload.get("narrative_instructions") or ""),
    )
    result = {
        "schema_version": MULTISPEAKER_SCHEMA_VERSION if is_multispeaker else 2,
        "kind": "dubroom_translation_manifest",
        "prompt_revision": (
            MULTISPEAKER_PROMPT_REVISION
            if is_multispeaker
            else SINGLE_SPEAKER_PROMPT_REVISION
        ),
        "project_id": payload["project_id"],
        "project_name": payload["project_name"],
        "source_language": payload["source_language"],
        "target_language": payload["target_language"],
        "dubbing_mode": "multi" if is_multispeaker else "single",
        "narrative_profile": contract["profile"],
        "narrative_contract": contract,
        "revision": payload["revision"],
        "created_at": payload["created_at"],
        "status": "ready_for_translation",
        "duration": float(asr_payload.get("duration") or 0),
        "transcript_fingerprint": payload["transcript_fingerprint"],
        "speaker_hints": payload.get("speaker_hints") or {} if is_multispeaker else {},
        "character_registry": payload.get("character_registry") or [] if is_multispeaker else [],
        "speaker_sections": payload.get("speaker_sections") or [] if is_multispeaker else [],
        "instructions": (
            "MULTI-SPEAKER R5 ENGLISH FINAL: write English only, resolve stable character identities across the whole story first, then cast only important recurring "
            "characters to dedicated voices. Minor/crowd characters keep their CHAR identity but render with "
            "NARRATOR. MC is only proven dialogue or unmistakable private thought. Fill every voice_units array "
            "with stable render_voice_key/voice_archetype metadata. Keep each segment's total English word count "
            "inside recommended_words and close to ideal. Preserve immutable evidence and create the "
            "completed JSON as a downloadable file."
            if is_multispeaker
            else "SINGLE-SPEAKER V2: adapt every translation naturally for one stable narrator voice. Preserve "
            "all IDs, hashes, source text and timecodes. Return a complete downloadable JSON file."
        ),
        "segments": segments,
    }
    if is_multispeaker and str(payload.get("subtitle_evidence_revision") or "").strip():
        result["subtitle_evidence_revision"] = str(
            payload["subtitle_evidence_revision"]
        ).strip()
    return result


def render_gpt_instructions(payload: dict[str, Any]) -> str:
    contract = payload.get("narrative_contract") or exchange_contract(
        str(payload.get("narrative_profile") or "natural_recap"),
        str(payload.get("narrative_instructions") or ""),
    )
    rules = "\n".join(
        f"- {rule}" for rule in (contract.get("rules") or [])
    )
    forbidden = "\n".join(
        f"- {item}" for item in (contract.get("forbidden") or [])
    )
    return f"""# DubRoom GPT · Instructions de réécriture

Tu es le scénariste final de doublage de DubRoom Studio. Tu lis toute l'histoire
avant d'écrire et tu produis une adaptation orale naturelle, fidèle et jouable.

## Profil sélectionné

- Profil : {contract["profile"]}
- Point de vue : {contract["point_of_view"]}
- Rôle du narrateur : {contract["narrator_role"]}
- Ton : {contract["tone"]}
- Direction de style : {contract["style_instruction"]}
- Direction du projet : {contract.get("project_direction") or "Aucune"}

## Règles obligatoires

{rules}

## Interdictions

{forbidden}

## Contrat de sortie

- Lis le fichier complet avant de commencer.
- Conserve strictement les identifiants, durées, timecodes, `temporary_cluster` et textes source.
- `temporary_cluster` est un indice acoustique, pas l'identité finale. Plusieurs clusters peuvent appartenir au même personnage.
- Déduis l'identité stable grâce à toute l'histoire, aux noms, à qui répond à qui et à la continuité des scènes.
- Pour chaque `speaker_section`, remplis d'abord `detected_speakers`, puis applique ces mêmes identifiants aux segments de la section et réutilise-les dans les sections suivantes.
- Les indices de sexe et d'âge sont prudents et secondaires. Ne devine jamais un âge numérique précis.
- Remplis `character_id`, `character_name`, `character_role`, `character_confidence` et `translation`/`TARGET`.
- En Multi-Speaker R4, sépare l'identité du rendu : un `CHAR_###` mineur garde son identité mais peut avoir `render_voice_key: narrator`.
- Le registre R4 décide `importance`, compte les dialogues significatifs/scènes, puis fixe `dedicated_voice`, `voice_archetype`, `render_voice_key`, `casting_confidence` et les verrous.
- Utilise `CHAR_001`, `CHAR_002`, `NARRATOR`, `SYSTEM` ou `UNKNOWN` comme identifiants stables.
- N'ajoute aucune explication, note, introduction ni bloc Markdown.
- Chaque texte doit tenir dans sa durée à un débit naturel, sans accélération artificielle.
- DubRoom conserve 0,12 seconde avant la voix et 0,18 seconde après elle; le texte doit rester proche du nombre de mots idéal pour ne pas ajouter un silence plus long.
- Pour le profil externe, le narrateur raconte toute l'histoire de l'extérieur à la troisième personne.
- Transforme le « je/nous » du récit source en nom du personnage ou en pronom de troisième personne.
- Garde la première personne uniquement dans une réplique réellement prononcée et clairement identifiable.
- N'invente pas de guillemets pour une pensée, une description ou une narration récapitulative.
- Écris des phrases complètes avec sujet et verbe; évite les fragments nominaux, slogans et formulations télégraphiques.
- Relie naturellement action, réaction, cause et conséquence afin que les segments forment un récit continu.
- Vise 88 à 100 % de la fenêtre de parole utile et reste proche du nombre de mots idéal.
"""


def _subtitle_timestamp(value: str, *, srt: bool) -> str:
    seconds = timestamp_seconds(value)
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    separator = "," if srt else "."
    return (
        f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}"
        f"{separator}{milliseconds:03d}"
    )


def write_export(
    *,
    project_dir: Path,
    payload: dict[str, Any],
    export_format: str,
    chunk_size: int = 60,
) -> dict[str, Any]:
    value = str(export_format or "manifest").strip().lower()
    if value not in {"manifest", "chat", "json", "srt", "vtt"}:
        raise ValueError("Unsupported transcript export format")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = project_dir / "analysis" / "exchange" / f"export-{stamp}-{value}"
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(str(payload["project_id"]))
    files: list[Path] = []
    if value == "manifest":
        manifest = output_dir / f"{stem}-translation-manifest.json"
        manifest.write_text(
            json.dumps(
                build_translation_manifest(
                    project_dir=project_dir,
                    payload=payload,
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        files.append(manifest)
    else:
        manifest = output_dir / f"{stem}-exchange.json"
        manifest.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        files.append(manifest)
    if value == "chat":
        for name, content in render_chat_parts(payload, chunk_size=chunk_size):
            path = output_dir / name
            path.write_text(content, encoding="utf-8")
            files.append(path)
    elif value == "srt":
        path = output_dir / f"{stem}-transcript.srt"
        path.write_text(render_srt(payload), encoding="utf-8-sig")
        files.append(path)
    elif value == "vtt":
        path = output_dir / f"{stem}-transcript.vtt"
        path.write_text(render_vtt(payload), encoding="utf-8")
        files.append(path)
    if value in {"manifest", "chat", "json"}:
        guide = output_dir / "DUBROOM-GPT-INSTRUCTIONS.md"
        source_language = str(payload.get("source_language") or "").lower()
        custom_root = Path(__file__).resolve().parents[3] / "docs" / "custom-gpt-dubroom"
        custom_guide = custom_root / "INSTRUCTIONS_CHINESE_MULTISPEAKER_V5_ENGLISH_TIMING_8000.txt"
        use_chinese_multispeaker = bool(
            source_language in {"zh", "zh-cn", "zh-tw", "cmn"}
            and str(payload.get("dubbing_mode") or "single") == "multi"
        )
        guide.write_text(
            custom_guide.read_text(encoding="utf-8")
            if use_chinese_multispeaker and custom_guide.is_file()
            else render_gpt_instructions(payload),
            encoding="utf-8",
        )
        files.append(guide)
        if use_chinese_multispeaker and custom_guide.is_file():
            instructions_txt = output_dir / custom_guide.name
            instructions_txt.write_text(
                custom_guide.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            files.append(instructions_txt)
        knowledge_source = custom_root / "KNOWLEDGE_MULTISPEAKER_JSON_R5_ENGLISH_TIMING.txt"
        if use_chinese_multispeaker and knowledge_source.is_file():
            knowledge = output_dir / knowledge_source.name
            knowledge.write_text(knowledge_source.read_text(encoding="utf-8"), encoding="utf-8")
            files.append(knowledge)
            setup = output_dir / "DUBROOM-CUSTOM-GPT-SETUP.txt"
            setup_source = custom_root / "DUBROOM-CUSTOM-GPT-R5-SETUP.txt"
            setup.write_text(
                setup_source.read_text(encoding="utf-8")
                if setup_source.is_file()
                else "DUBROOM CUSTOM GPT R5 - SETUP\n",
                encoding="utf-8",
            )
            files.append(setup)
    return {
        "format": value,
        "output_dir": str(output_dir.resolve()),
        "segment_count": len(payload["segments"]),
        "context_count": len(payload["context_groups"]),
        "transcript_fingerprint": payload["transcript_fingerprint"],
        "files": [
            {
                "name": path.name,
                "path": str(path.resolve()),
                "size_bytes": path.stat().st_size,
            }
            for path in files
        ],
    }


def parse_import_file(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError("Translation file does not exist")
    suffix = resolved.suffix.lower()
    if suffix in {".json", ".md", ".txt"}:
        content = resolved.read_text(encoding="utf-8-sig")
        payload = _extract_json_payload(content)
        if payload is not None:
            return _parse_json_payload(resolved, payload)
        if suffix == ".json":
            raise ValueError("The selected file is not a valid DubRoom JSON object")
    if suffix in {".md", ".txt"}:
        return _parse_chat_import(resolved)
    if suffix in {".srt", ".vtt"}:
        return _parse_subtitle_import(resolved)
    raise ValueError("Use a DubRoom JSON, Chat Pack, SRT or VTT file")


def _extract_json_payload(content: str) -> dict[str, Any] | None:
    """Accept real JSON, fenced JSON, or a downloaded raw JSON text file."""
    stripped = str(content or "").strip().lstrip("\ufeff")
    candidates = [stripped]
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", stripped, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    first = stripped.find("{")
    last = stripped.rfind("}")
    if first >= 0 and last > first:
        candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("segments"), list):
            return payload
    return None


def _parse_json_import(path: Path) -> dict[str, Any]:
    payload = _extract_json_payload(path.read_text(encoding="utf-8-sig"))
    if payload is None:
        raise ValueError("Invalid DubRoom exchange JSON")
    return _parse_json_payload(path, payload)


def _parse_json_payload(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("segments") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("Invalid DubRoom exchange JSON")
    entries = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        voice_units = []
        for index, unit in enumerate(row.get("voice_units") or [], start=1):
            if not isinstance(unit, dict):
                continue
            events = []
            for event in unit.get("vocal_events") or []:
                if isinstance(event, str):
                    events.append({"event": event.strip().lower(), "position": "before"})
                elif isinstance(event, dict):
                    events.append(
                        {
                            "event": str(event.get("event") or "").strip().lower(),
                            "position": str(event.get("position") or "before").strip().lower(),
                        }
                    )
            voice_units.append(
                {
                    "unit_id": str(unit.get("unit_id") or f'{row.get("id")}-u{index:02d}').strip(),
                    "order": unit.get("order", index),
                    "speech_type": str(unit.get("speech_type") or "").strip().lower(),
                    "character_id": str(unit.get("character_id") or "").strip().upper(),
                    "character_name": str(unit.get("character_name") or "").strip(),
                    "character_role": str(unit.get("character_role") or "").strip(),
                    "voice_key": str(unit.get("voice_key") or "").strip().lower(),
                    "render_voice_key": str(
                        unit.get("render_voice_key") or unit.get("voice_key") or ""
                    ).strip().lower(),
                    "voice_archetype": str(unit.get("voice_archetype") or "").strip().upper(),
                    "source_excerpt": str(unit.get("source_excerpt") or "").strip(),
                    "target_text": str(
                        unit.get("translation")
                        or unit.get("target_text")
                        or unit.get("translated_text")
                        or ""
                    ).strip(),
                    "emotion": str(unit.get("emotion") or "neutral").strip().lower(),
                    "emotion_intensity": unit.get("emotion_intensity", 0),
                    "vocal_events": events,
                    "character_confidence": unit.get(
                        "confidence", unit.get("character_confidence")
                    ),
                }
            )
        target = str(
            row.get("target_text")
            or row.get("translated_text")
            or row.get("translatedText")
            or row.get("translation")
            or ""
        ).strip()
        if voice_units:
            target = " ".join(
                str(unit.get("target_text") or "").strip()
                for unit in sorted(voice_units, key=lambda item: int(item.get("order") or 0))
                if str(unit.get("target_text") or "").strip()
            ).strip()
        if not target:
            continue
        entries.append(
            {
                "id": str(row.get("id") or "").strip(),
                "target_text": target,
                "source_hash": str(row.get("source_hash") or "").strip(),
                "subtitle_evidence": subtitle_evidence(row),
                "temporary_cluster": str(row.get("temporary_cluster") or row.get("speaker") or "").strip(),
                "character_id": str(row.get("character_id") or "").strip().upper(),
                "character_name": str(row.get("character_name") or "").strip(),
                "character_role": str(row.get("character_role") or "").strip(),
                "character_confidence": row.get("character_confidence"),
                "emotion": str(row.get("emotion") or "neutral").strip().lower(),
                "emotion_intensity": row.get("emotion_intensity", 0),
                "omnivoice_tag": str(row.get("omnivoice_tag") or "").strip().lower(),
                "voice_units": voice_units,
                "bridge_slot": row.get("bridge_slot") if isinstance(row.get("bridge_slot"), dict) else {},
                "narrator_bridge": row.get("narrator_bridge") if isinstance(row.get("narrator_bridge"), dict) else {},
            }
        )
    return {
        "format": "json",
        "project_id": payload.get("project_id"),
        "revision": payload.get("revision"),
        "transcript_fingerprint": payload.get("transcript_fingerprint"),
        "subtitle_evidence_revision": str(
            payload.get("subtitle_evidence_revision") or ""
        ).strip(),
        "entries": entries,
        "speaker_sections": (
            payload.get("speaker_sections")
            if isinstance(payload.get("speaker_sections"), list)
            else []
        ),
        "character_registry": (
            payload.get("character_registry")
            if isinstance(payload.get("character_registry"), list)
            else []
        ),
        "schema_version": int(payload.get("schema_version") or 2),
        "prompt_revision": str(payload.get("prompt_revision") or "").strip(),
        "target_language": str(payload.get("target_language") or "").strip().lower(),
        "kind": str(payload.get("kind") or "").strip(),
        "status": str(payload.get("status") or "").strip().lower(),
        "path": str(path),
    }


def _parse_chat_import(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8-sig")
    entries = []
    for match in CHAT_SEGMENT_RE.finditer(content):
        attributes = {
            item.group("name").lower(): item.group("value")
            for item in CHAT_ATTRIBUTE_RE.finditer(match.group("attrs"))
        }
        body = match.group("body")
        fields: dict[str, str] = {}
        for field in (
            "CHARACTER_ID",
            "CHARACTER_NAME",
            "CHARACTER_ROLE",
            "CHARACTER_CONFIDENCE",
            "EMOTION",
            "EMOTION_INTENSITY",
            "OMNIVOICE_TAG",
        ):
            field_match = re.search(
                rf"^{field}:\s*(.*?)\s*$",
                body,
                re.MULTILINE | re.IGNORECASE,
            )
            fields[field] = field_match.group(1).strip() if field_match else ""
        target_match = re.search(
            r"^TARGET:\s*(?P<target>.*)\Z",
            body,
            re.MULTILINE | re.DOTALL | re.IGNORECASE,
        )
        target = target_match.group("target").strip() if target_match else ""
        if not target:
            continue
        entries.append(
            {
                "id": str(attributes.get("id") or "").strip(),
                "target_text": target,
                "source_hash": str(attributes.get("hash") or "").strip(),
                "temporary_cluster": str(attributes.get("temporary_cluster") or "").strip(),
                "character_id": fields["CHARACTER_ID"].upper(),
                "character_name": fields["CHARACTER_NAME"],
                "character_role": fields["CHARACTER_ROLE"],
                "character_confidence": fields["CHARACTER_CONFIDENCE"],
                "emotion": fields["EMOTION"].lower() or "neutral",
                "emotion_intensity": fields["EMOTION_INTENSITY"] or 0,
                "omnivoice_tag": fields["OMNIVOICE_TAG"].lower(),
            }
        )
    fingerprint_match = re.search(
        r"^Transcript fingerprint:\s*(\S+)",
        content,
        re.MULTILINE | re.IGNORECASE,
    )
    return {
        "format": "chat",
        "project_id": None,
        "revision": None,
        "transcript_fingerprint": (
            fingerprint_match.group(1) if fingerprint_match else None
        ),
        "entries": entries,
        "speaker_sections": [],
        "path": str(path),
    }


def _parse_subtitle_import(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    blocks = re.split(r"\n{2,}", content.strip())
    entries = []
    for block in blocks:
        if block.strip().upper() == "WEBVTT":
            continue
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        id_match = re.search(r"\[([A-Za-z0-9_-]+)\]", "\n".join(lines))
        if not id_match:
            continue
        text_lines = [
            re.sub(r"^\[[A-Za-z0-9_-]+\]\s*", "", line)
            for line in lines
            if "-->" not in line
            and not re.fullmatch(r"\d+", line)
            and line != id_match.group(1)
        ]
        target = " ".join(line for line in text_lines if line).strip()
        if target:
            entries.append(
                {
                    "id": id_match.group(1),
                    "target_text": target,
                    "source_hash": "",
                }
            )
    return {
        "format": path.suffix.lower().lstrip("."),
        "project_id": None,
        "revision": None,
        "transcript_fingerprint": None,
        "entries": entries,
        "speaker_sections": [],
        "path": str(path),
    }


def preview_import(
    *,
    state: dict[str, Any],
    parsed: dict[str, Any],
    require_complete_multispeaker: bool = False,
) -> dict[str, Any]:
    segments = [
        segment
        for segment in (state.get("segments") or [])
        if isinstance(segment, dict)
    ]
    by_id = {str(segment.get("id") or ""): segment for segment in segments}
    entries_by_id: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    unknown: list[str] = []
    hash_mismatches: list[str] = []
    subtitle_evidence_mismatches: list[str] = []
    empty: list[str] = []
    timing_warnings: list[dict[str, Any]] = []
    invalid_character_ids: list[str] = []
    character_conflicts: list[str] = []
    character_metadata: dict[str, tuple[str, str]] = {}
    invalid_emotion_ids: list[str] = []
    invalid_voice_unit_ids: list[str] = []
    invalid_bridge_ids: list[str] = []
    invalid_registry_ids: list[str] = []
    invalid_casting_ids: list[str] = []
    casting_review_ids: list[str] = []
    invalid_speaker_section_ids: list[str] = []
    strict_timing_mismatch_ids: list[str] = []
    non_english_translation_ids: list[str] = []
    seen_voice_unit_ids: set[str] = set()
    schema_version = int(parsed.get("schema_version") or 2)
    expected_evidence_revision = str(
        state.get("subtitle_evidence_revision") or ""
    ).strip()
    imported_evidence_revision = str(
        parsed.get("subtitle_evidence_revision") or ""
    ).strip()
    subtitle_evidence_revision_mismatch = bool(
        schema_version >= MULTISPEAKER_SCHEMA_VERSION
        and imported_evidence_revision != expected_evidence_revision
    )
    prompt_revision = str(parsed.get("prompt_revision") or "").strip()
    strict_english_timing = bool(
        schema_version >= MULTISPEAKER_SCHEMA_VERSION
        and prompt_revision == MULTISPEAKER_ENGLISH_TIMING_PROMPT_REVISION
    )
    imported_target_language = str(parsed.get("target_language") or "").strip().lower()
    invalid_target_language = bool(
        strict_english_timing and imported_target_language != "en"
    )
    casting_r4 = bool(
        schema_version >= MULTISPEAKER_SCHEMA_VERSION
        and prompt_revision in MULTISPEAKER_CASTING_PROMPT_REVISIONS
    )
    prompt_revision_mismatch = bool(
        schema_version >= MULTISPEAKER_SCHEMA_VERSION
        and prompt_revision
        and prompt_revision not in MULTISPEAKER_ACCEPTED_PROMPT_REVISIONS
    )
    registry_ids: set[str] = set()
    registry_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(parsed.get("character_registry") or [], start=1):
        if not isinstance(item, dict):
            invalid_registry_ids.append(f"registry-{index}")
            continue
        character_id = str(item.get("character_id") or "").strip().upper()
        voice_key = str(item.get("voice_key") or "").strip().lower()
        sex = str(item.get("sex") or "uncertain").strip().lower()
        age_group = str(item.get("age_group") or "unknown").strip().lower()
        try:
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = -1.0
        if not (
            CHARACTER_ID_RE.fullmatch(character_id)
            and character_id not in registry_ids
            and voice_key in VOICE_KEYS
            and sex in SEX_LABELS
            and age_group in AGE_GROUPS
            and 0.0 <= confidence <= 1.0
        ):
            invalid_registry_ids.append(character_id or f"registry-{index}")
            continue

        normalized = dict(item)
        normalized.update(
            {
                "character_id": character_id,
                "voice_key": voice_key,
                "sex": sex,
                "age_group": age_group,
                "confidence": confidence,
            }
        )

        if casting_r4 and character_id not in {"NARRATOR", "SYSTEM", "UNKNOWN"}:
            importance = str(item.get("importance") or "").strip().lower()
            render_voice_key = str(item.get("render_voice_key") or "").strip().lower()
            voice_archetype = str(item.get("voice_archetype") or "").strip().upper()
            casting_reason = str(item.get("casting_reason") or "").strip().lower()
            casting_status = str(item.get("casting_status") or "").strip().lower()
            presence = str(item.get("presence") or "").strip().lower()
            emotionality = str(item.get("emotionality") or "").strip().lower()
            temperament = item.get("temperament")
            dedicated_voice = item.get("dedicated_voice")
            identity_locked = item.get("identity_locked")
            voice_locked = item.get("voice_locked")
            try:
                dialogue_count = int(item.get("dialogue_count"))
                meaningful_dialogue_count = int(item.get("meaningful_dialogue_count"))
                scene_count = int(item.get("scene_count"))
                casting_confidence = float(item.get("casting_confidence"))
            except (TypeError, ValueError):
                dialogue_count = meaningful_dialogue_count = scene_count = -1
                casting_confidence = -1.0

            base_casting_valid = bool(
                importance in IMPORTANCE_LEVELS
                and render_voice_key in VOICE_KEYS
                and casting_reason in CASTING_REASONS
                and casting_status in CASTING_STATUSES
                and presence in PRESENCE_LEVELS
                and emotionality in EMOTIONALITY_LEVELS
                and isinstance(temperament, list)
                and all(isinstance(value, str) and value.strip() for value in temperament)
                and len(temperament) <= 6
                and isinstance(dedicated_voice, bool)
                and isinstance(identity_locked, bool)
                and isinstance(voice_locked, bool)
                and dialogue_count >= 0
                and meaningful_dialogue_count >= 0
                and meaningful_dialogue_count <= dialogue_count
                and scene_count >= 0
                and 0.0 <= casting_confidence <= 1.0
                and (not voice_archetype or VOICE_ARCHETYPE_RE.fullmatch(voice_archetype))
            )
            policy_valid = base_casting_valid
            if importance in {"primary", "major"} and not dedicated_voice:
                policy_valid = False
            if importance in {"minor", "crowd"} and dedicated_voice:
                policy_valid = False
            if not dedicated_voice and render_voice_key != "narrator":
                policy_valid = False
            if not dedicated_voice and voice_archetype:
                policy_valid = False
            if dedicated_voice and casting_status != "needs_review":
                policy_valid = bool(
                    policy_valid
                    and render_voice_key == voice_key
                    and render_voice_key not in {"narrator", "unknown"}
                    and voice_archetype
                )
            if casting_status == "needs_review":
                casting_review_ids.append(character_id)
                if voice_locked:
                    policy_valid = False
            if (
                importance == "supporting"
                and dedicated_voice
                and casting_reason != "narrative_necessity"
                and not (
                    meaningful_dialogue_count >= 8
                    or (meaningful_dialogue_count >= 5 and scene_count >= 2)
                )
            ):
                policy_valid = False
            if importance in {"minor", "crowd"} and casting_reason != "narrator_fallback":
                policy_valid = False
            # CASTING_R4_FINAL_POLICY
            if casting_status == "auto":
                policy_valid = False
            if casting_status == "needs_review":
                if (
                    voice_archetype
                    or voice_locked
                    or casting_reason != "ambiguous"
                    or render_voice_key != voice_key
                ):
                    policy_valid = False
            elif casting_status == "locked" and not voice_locked:
                policy_valid = False
            if voice_locked and casting_status != "locked":
                policy_valid = False
            if not dedicated_voice and (casting_status != "locked" or not voice_locked):
                policy_valid = False
            if dedicated_voice and casting_status == "locked" and not voice_archetype:
                policy_valid = False
            if not policy_valid:
                invalid_casting_ids.append(character_id)

            normalized.update(
                {
                    "importance": importance,
                    "dialogue_count": dialogue_count,
                    "meaningful_dialogue_count": meaningful_dialogue_count,
                    "scene_count": scene_count,
                    "temperament": temperament if isinstance(temperament, list) else [],
                    "presence": presence,
                    "emotionality": emotionality,
                    "dedicated_voice": bool(dedicated_voice),
                    "voice_archetype": voice_archetype,
                    "render_voice_key": render_voice_key,
                    "casting_reason": casting_reason,
                    "casting_status": casting_status,
                    "casting_confidence": casting_confidence,
                    "identity_locked": bool(identity_locked),
                    "voice_locked": bool(voice_locked),
                }
            )

        registry_ids.add(character_id)
        registry_by_id[character_id] = normalized
    for index, section in enumerate(parsed.get("speaker_sections") or [], start=1):
        section_id = str((section or {}).get("section_id") or f"section-{index}")
        if not isinstance(section, dict):
            invalid_speaker_section_ids.append(section_id)
            continue
        for detected in section.get("detected_speakers") or []:
            # R2 accepted a compact list of character IDs. Keep those files
            # importable; the registry still carries their casting metadata.
            if isinstance(detected, str) and CHARACTER_ID_RE.fullmatch(
                detected.strip().upper()
            ):
                continue
            if not isinstance(detected, dict):
                invalid_speaker_section_ids.append(section_id)
                break
            detected_id = str(detected.get("character_id") or "").strip().upper()
            sex = str(detected.get("sex") or "uncertain").strip().lower()
            age_group = str(detected.get("age_group") or "unknown").strip().lower()
            try:
                confidence = float(detected.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = -1.0
            if not (
                CHARACTER_ID_RE.fullmatch(detected_id)
                and sex in SEX_LABELS
                and age_group in AGE_GROUPS
                and 0.0 <= confidence <= 1.0
            ):
                invalid_speaker_section_ids.append(section_id)
                break
    for entry in parsed.get("entries") or []:
        segment_id = str(entry.get("id") or "").strip()
        target = str(entry.get("target_text") or "").strip()
        if not segment_id:
            continue
        if segment_id in entries_by_id:
            duplicates.append(segment_id)
            continue
        if segment_id not in by_id:
            unknown.append(segment_id)
            continue
        if not target:
            empty.append(segment_id)
            continue
        expected_hash = str(entry.get("source_hash") or "").strip()
        if expected_hash and expected_hash != source_hash(
            by_id[segment_id],
            include_subtitle_evidence=schema_version >= MULTISPEAKER_SCHEMA_VERSION,
        ):
            hash_mismatches.append(segment_id)
            continue
        if (
            schema_version >= MULTISPEAKER_SCHEMA_VERSION
            and subtitle_evidence(entry) != subtitle_evidence(by_id[segment_id])
        ):
            subtitle_evidence_mismatches.append(segment_id)
            continue
        raw_units = entry.get("voice_units") or []
        if raw_units:
            normalised_units: list[dict[str, Any]] = []
            unit_failed = False
            expected_orders = list(range(1, len(raw_units) + 1))
            actual_orders: list[int] = []
            for index, unit in enumerate(raw_units, start=1):
                unit_id = str(unit.get("unit_id") or "").strip()
                character_id = str(unit.get("character_id") or "").strip().upper()
                character_name = str(unit.get("character_name") or "").strip()
                character_role = str(unit.get("character_role") or "").strip()
                speech_type = str(unit.get("speech_type") or "").strip().lower()
                voice_key = str(unit.get("voice_key") or "").strip().lower()
                render_voice_key = str(
                    unit.get("render_voice_key") or voice_key
                ).strip().lower()
                voice_archetype = str(unit.get("voice_archetype") or "").strip().upper()
                unit_target = str(unit.get("target_text") or "").strip()
                emotion = str(unit.get("emotion") or "neutral").strip().lower()
                confidence_value = unit.get("character_confidence")
                try:
                    order = int(unit.get("order") or index)
                    actual_orders.append(order)
                    character_confidence = (
                        None if confidence_value in {None, ""}
                        else max(0.0, min(1.0, float(confidence_value)))
                    )
                    emotion_intensity = max(
                        0, min(100, int(float(unit.get("emotion_intensity") or 0)))
                    )
                except (TypeError, ValueError):
                    invalid_voice_unit_ids.append(unit_id or segment_id)
                    unit_failed = True
                    continue
                events = unit.get("vocal_events") or []
                events_valid = all(
                    isinstance(event, dict)
                    and str(event.get("event") or "").strip().lower() in OMNIVOICE_TAGS - {""}
                    and str(event.get("position") or "").strip().lower() in {"before", "after"}
                    for event in events
                )
                identity_valid = bool(
                    unit_id
                    and unit_id not in seen_voice_unit_ids
                    and re.fullmatch(rf"{re.escape(segment_id)}-u\d{{2}}", unit_id)
                    and unit_target
                    and CHARACTER_ID_RE.fullmatch(character_id)
                    and speech_type in SPEECH_TYPES
                    and voice_key in VOICE_KEYS
                    and emotion in EMOTION_LABELS
                    and events_valid
                    and (speech_type != "narration" or (character_id == "NARRATOR" and voice_key == "narrator"))
                    and (character_id != "NARRATOR" or (speech_type == "narration" and voice_key == "narrator"))
                    and (character_id != "SYSTEM" or (speech_type == "system" and voice_key == "system"))
                    and (speech_type != "system" or (character_id == "SYSTEM" and voice_key == "system"))
                    and (speech_type != "inner_monologue" or voice_key == "mc")
                    and (voice_key != "narrator" or character_id == "NARRATOR")
                    and (voice_key != "system" or character_id == "SYSTEM")
                    and (voice_key != "mc" or speech_type in {"dialogue", "inner_monologue", "reaction"})
                )
                if not identity_valid:
                    invalid_voice_unit_ids.append(unit_id or segment_id)
                    unit_failed = True
                    continue
                if casting_r4:
                    casting_valid = True
                    if character_id == "NARRATOR":
                        casting_valid = render_voice_key == "narrator"
                    elif character_id == "SYSTEM":
                        casting_valid = render_voice_key == "system"
                    elif character_id == "UNKNOWN":
                        casting_valid = render_voice_key == "unknown" and not voice_archetype
                    else:
                        registry_item = registry_by_id.get(character_id)
                        casting_valid = bool(
                            registry_item
                            and voice_key == str(registry_item.get("voice_key") or "")
                            and render_voice_key == str(registry_item.get("render_voice_key") or "")
                            and voice_archetype == str(registry_item.get("voice_archetype") or "")
                        )
                    if not casting_valid:
                        invalid_casting_ids.append(unit_id or segment_id)
                        unit_failed = True
                        continue
                metadata = (character_name.casefold(), character_role.casefold())
                previous_metadata = character_metadata.get(character_id)
                if previous_metadata and any(
                    left and right and left != right
                    for left, right in zip(previous_metadata, metadata, strict=True)
                ):
                    character_conflicts.append(character_id)
                    unit_failed = True
                    continue
                character_metadata.setdefault(character_id, metadata)
                seen_voice_unit_ids.add(unit_id)
                normalised_units.append(
                    {
                        **unit,
                        "unit_id": unit_id,
                        "order": order,
                        "target_text": unit_target,
                        "character_id": character_id,
                        "character_name": character_name,
                        "character_role": character_role,
                        "voice_key": voice_key,
                        "render_voice_key": render_voice_key,
                        "voice_archetype": voice_archetype,
                        "speech_type": speech_type,
                        "character_confidence": character_confidence,
                        "emotion": emotion,
                        "emotion_intensity": emotion_intensity,
                        "vocal_events": events,
                    }
                )
            if actual_orders != expected_orders:
                invalid_voice_unit_ids.append(segment_id)
                unit_failed = True
            if unit_failed or not normalised_units:
                continue
            normalised_units.sort(key=lambda unit: int(unit["order"]))
            bridge_slot = entry.get("bridge_slot") or {}
            narrator_bridge = entry.get("narrator_bridge") or {}
            if bool(narrator_bridge.get("enabled")):
                bridge_text = str(narrator_bridge.get("translation") or "").strip()
                bridge_emotion = str(narrator_bridge.get("emotion") or "neutral").strip().lower()
                bridge_events = narrator_bridge.get("vocal_events") or []
                try:
                    bridge_intensity = max(
                        0,
                        min(100, int(float(narrator_bridge.get("emotion_intensity") or 0))),
                    )
                except (TypeError, ValueError):
                    bridge_intensity = -1
                bridge_word_count = len(
                    re.findall(r"\b[\w'-]+\b", bridge_text, re.UNICODE)
                )
                bridge_events_valid = all(
                    isinstance(event, dict)
                    and str(event.get("event") or "").strip().lower() in OMNIVOICE_TAGS - {""}
                    and str(event.get("position") or "").strip().lower() in {"before", "after"}
                    for event in bridge_events
                )
                if not (
                    bool(bridge_slot.get("available"))
                    and (
                        bool(bridge_slot.get("sfx_safe"))
                        or prompt_revision not in MULTISPEAKER_ACCEPTED_PROMPT_REVISIONS
                    )
                    and bridge_text
                    and bridge_emotion in EMOTION_LABELS
                    and bridge_intensity >= 0
                    and bridge_events_valid
                    and bridge_word_count <= int(bridge_slot.get("max_words") or 0)
                ):
                    invalid_bridge_ids.append(segment_id)
                    continue
                narrator_bridge = {
                    **narrator_bridge,
                    "translation": bridge_text,
                    "emotion": bridge_emotion,
                    "emotion_intensity": bridge_intensity,
                    "vocal_events": bridge_events,
                }
            entries_by_id[segment_id] = {
                "id": segment_id,
                "target_text": target,
                "temporary_cluster": str(entry.get("temporary_cluster") or "").strip(),
                "voice_units": normalised_units,
                "bridge_slot": bridge_slot,
                "narrator_bridge": narrator_bridge,
            }
        else:
            character_id = str(entry.get("character_id") or "").strip().upper()
            character_name = str(entry.get("character_name") or "").strip()
            character_role = str(entry.get("character_role") or "").strip()
            confidence_value = entry.get("character_confidence")
            character_confidence: float | None = None
            if confidence_value not in {None, ""}:
                try:
                    character_confidence = max(0.0, min(1.0, float(confidence_value)))
                except (TypeError, ValueError):
                    invalid_character_ids.append(segment_id)
                    continue
            if character_id and not CHARACTER_ID_RE.fullmatch(character_id):
                invalid_character_ids.append(segment_id)
                continue
            if character_id:
                metadata = (character_name.casefold(), character_role.casefold())
                previous_metadata = character_metadata.get(character_id)
                if previous_metadata and any(
                    left and right and left != right
                    for left, right in zip(previous_metadata, metadata, strict=True)
                ):
                    character_conflicts.append(character_id)
                    continue
                character_metadata.setdefault(character_id, metadata)
            emotion = str(entry.get("emotion") or "neutral").strip().lower()
            omnivoice_tag = str(entry.get("omnivoice_tag") or "").strip().lower()
            try:
                emotion_intensity = max(0, min(100, int(float(entry.get("emotion_intensity") or 0))))
            except (TypeError, ValueError):
                invalid_emotion_ids.append(segment_id)
                continue
            if emotion not in EMOTION_LABELS or omnivoice_tag not in OMNIVOICE_TAGS:
                invalid_emotion_ids.append(segment_id)
                continue
            entries_by_id[segment_id] = {
                "id": segment_id,
                "target_text": target,
                "temporary_cluster": str(entry.get("temporary_cluster") or "").strip(),
                "character_id": character_id,
                "character_name": character_name,
                "character_role": character_role,
                "character_confidence": character_confidence,
                "emotion": emotion,
                "emotion_intensity": emotion_intensity,
                "omnivoice_tag": omnivoice_tag,
            }
        duration = segment_duration(by_id[segment_id])
        word_count = len(re.findall(r"\b[\wÀ-ÿ'-]+\b", target, re.UNICODE))
        source_word_count = len(
            re.findall(
                r"\b[\wÀ-ÿ'-]+\b",
                str(by_id[segment_id].get("sourceText") or ""),
                re.UNICODE,
            )
        )
        words_per_second = word_count / duration
        expected = recommended_word_range(duration)
        likely_too_long = word_count > max(expected["maximum"] + 2, round(expected["maximum"] * 1.18))
        likely_too_short = (
            duration >= 1.8
            and source_word_count >= 3
            and word_count < max(1, round(expected["minimum"] * 0.82))
        )
        if likely_too_long or likely_too_short:
            timing_warnings.append(
                {
                    "id": segment_id,
                    "duration_seconds": round(duration, 3),
                    "word_count": word_count,
                    "recommended_words": expected,
                    "words_per_second": round(words_per_second, 2),
                    "kind": (
                        "likely_too_long"
                        if likely_too_long
                        else "likely_too_short"
                    ),
                }
            )
        if strict_english_timing:
            voice_units = entry.get("voice_units") or []
            short_reaction_exception = bool(
                duration < 1.2
                and voice_units
                and all(
                    str(unit.get("speech_type") or "").strip().lower() == "reaction"
                    for unit in voice_units
                )
            )
            if (
                word_count > int(expected["maximum"])
                or (word_count < int(expected["minimum"]) and not short_reaction_exception)
            ):
                strict_timing_mismatch_ids.append(segment_id)
            if _looks_clearly_french(target):
                non_english_translation_ids.append(segment_id)

    fingerprint = transcript_fingerprint(
        segments,
        expected_evidence_revision
        if schema_version >= MULTISPEAKER_SCHEMA_VERSION
        else None,
        include_subtitle_evidence=schema_version >= MULTISPEAKER_SCHEMA_VERSION,
    )
    imported_fingerprint = str(parsed.get("transcript_fingerprint") or "")
    fingerprint_mismatch = bool(
        imported_fingerprint and imported_fingerprint != fingerprint
    )
    changed = sum(
        str(by_id[segment_id].get("translatedText") or "").strip()
        != str(entry["target_text"]).strip()
        for segment_id, entry in entries_by_id.items()
    )
    used_character_ids = {
        str(unit.get("character_id") or "").strip().upper()
        for entry in entries_by_id.values()
        for unit in entry.get("voice_units") or []
        if str(unit.get("character_id") or "").strip()
    }
    missing_registry_ids = sorted(
        character_id
        for character_id in used_character_ids - {"NARRATOR", "SYSTEM", "UNKNOWN"}
        if character_id not in registry_ids
    )
    incomplete_multispeaker = bool(
        require_complete_multispeaker
        and schema_version >= MULTISPEAKER_SCHEMA_VERSION
        and len(entries_by_id) != len(segments)
    )
    blocking = bool(
        duplicates
        or hash_mismatches
        or subtitle_evidence_mismatches
        or subtitle_evidence_revision_mismatch
        or fingerprint_mismatch
        or invalid_character_ids
        or character_conflicts
        or invalid_emotion_ids
        or invalid_voice_unit_ids
        or invalid_bridge_ids
        or invalid_registry_ids
        or invalid_casting_ids
        or invalid_speaker_section_ids
        or prompt_revision_mismatch
        or invalid_target_language
        or strict_timing_mismatch_ids
        or non_english_translation_ids
        or missing_registry_ids
        or incomplete_multispeaker
    )
    samples = []
    for segment_id, entry in list(entries_by_id.items())[:6]:
        segment = by_id[segment_id]
        samples.append(
            {
                "id": segment_id,
                "start": segment.get("start"),
                "end": segment.get("end"),
                "source_text": segment.get("sourceText"),
                "previous_text": segment.get("translatedText"),
                "target_text": entry["target_text"],
                "character_id": entry.get("character_id") or None,
                "character_name": entry.get("character_name") or None,
            }
        )
    return {
        "format": parsed.get("format"),
        "path": parsed.get("path"),
        "revision": int(state.get("revision") or 0),
        "transcript_fingerprint": fingerprint,
        "imported_fingerprint": imported_fingerprint or None,
        "segment_count": len(segments),
        "parsed_count": len(parsed.get("entries") or []),
        "matched_count": len(entries_by_id),
        "changed_count": changed,
        "untouched_count": len(segments) - len(entries_by_id),
        "duplicate_ids": sorted(set(duplicates)),
        "unknown_ids": sorted(set(unknown)),
        "empty_ids": sorted(set(empty)),
        "source_mismatch_ids": sorted(set(hash_mismatches)),
        "subtitle_evidence_mismatch_ids": sorted(
            set(subtitle_evidence_mismatches)
        ),
        "subtitle_evidence_revision": expected_evidence_revision or None,
        "imported_subtitle_evidence_revision": imported_evidence_revision or None,
        "subtitle_evidence_revision_mismatch": subtitle_evidence_revision_mismatch,
        "invalid_character_ids": sorted(set(invalid_character_ids)),
        "character_conflicts": sorted(set(character_conflicts)),
        "invalid_emotion_ids": sorted(set(invalid_emotion_ids)),
        "invalid_voice_unit_ids": sorted(set(invalid_voice_unit_ids)),
        "invalid_bridge_ids": sorted(set(invalid_bridge_ids)),
        "invalid_registry_ids": sorted(set(invalid_registry_ids)),
        "invalid_casting_ids": sorted(set(invalid_casting_ids)),
        "casting_review_ids": sorted(set(casting_review_ids)),
        "invalid_speaker_section_ids": sorted(set(invalid_speaker_section_ids)),
        "invalid_target_language": invalid_target_language,
        "imported_target_language": imported_target_language or None,
        "strict_timing_mismatch_ids": sorted(set(strict_timing_mismatch_ids)),
        "non_english_translation_ids": sorted(set(non_english_translation_ids)),
        "missing_registry_ids": missing_registry_ids,
        "incomplete_multispeaker": incomplete_multispeaker,
        "prompt_revision": prompt_revision or None,
        "expected_prompt_revision": (
            MULTISPEAKER_PROMPT_REVISION
            if schema_version >= MULTISPEAKER_SCHEMA_VERSION
            else SINGLE_SPEAKER_PROMPT_REVISION
        ),
        "prompt_revision_mismatch": prompt_revision_mismatch,
        "casting_r4": casting_r4,
        "dedicated_voice_count": sum(
            1
            for character_id, item in registry_by_id.items()
            if character_id not in {"NARRATOR", "SYSTEM", "UNKNOWN"}
            and bool(item.get("dedicated_voice"))
        ),
        "narrator_rendered_character_count": sum(
            1
            for character_id, item in registry_by_id.items()
            if character_id not in {"NARRATOR", "SYSTEM", "UNKNOWN"}
            and str(item.get("render_voice_key") or "") == "narrator"
        ),
        "resolved_character_count": len(
            {
                character_id
                for entry in entries_by_id.values()
                for character_id in (
                    [str(unit.get("character_id") or "") for unit in entry.get("voice_units") or []]
                    if entry.get("voice_units")
                    else [str(entry.get("character_id") or "")]
                )
                if character_id
            }
        ),
        "fingerprint_mismatch": fingerprint_mismatch,
        "timing_warning_count": len(timing_warnings),
        "timing_warnings": timing_warnings[:30],
        "can_apply": bool(entries_by_id) and not blocking,
        "entries": list(entries_by_id.values()),
        "speaker_sections": parsed.get("speaker_sections") or [],
        "character_registry": parsed.get("character_registry") or [],
        "schema_version": schema_version,
        "samples": samples,
    }


def write_import_audit(
    *,
    project_dir: Path,
    source_path: Path,
    preview: dict[str, Any],
) -> Path:
    audit_dir = project_dir / "analysis" / "exchange" / "imports"
    audit_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = audit_dir / f"import-{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "source_path": str(source_path.resolve()),
                "imported_at": datetime.now(timezone.utc).isoformat(),
                "summary": {
                    key: value
                    for key, value in preview.items()
                    if key not in {"entries", "samples", "timing_warnings"}
                },
                "entries": preview.get("entries") or [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
