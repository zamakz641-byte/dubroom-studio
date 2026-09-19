from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import local_voice_service

POLICY_VERSION = "casting-intelligence-r4-final-20260809"
RESOLVER_VERSION = "voice-archetype-resolver-r4-final-1"

# These signatures describe the desired CASTING timbre, not per-line emotion.
# Exact profile metadata wins. The signatures are only a safe fallback for the
# existing OmniVoice library while new, better designed voices are added later.
ARCHETYPE_SIGNATURES: dict[str, dict[str, Any]] = {
    "M_PROTAG_SOFT": {
        "sex": "male", "ages": {"teen", "young_adult"},
        "roles": {"mc", "protagonist", "hero"},
        "positive": {"soft", "warm", "calm", "gentle", "youthful", "clear", "neutral"},
        "negative": {"elderly", "old", "rough", "dominant", "authoritative"},
    },
    "M_PROTAG_NEUTRAL": {
        "sex": "male", "ages": {"teen", "young_adult", "adult"},
        "roles": {"mc", "protagonist", "hero"},
        "positive": {"neutral", "calm", "versatile", "natural", "clear", "stable"},
        "negative": {"elderly", "old", "caricature"},
    },
    "M_PROTAG_POWERFUL": {
        "sex": "male", "ages": {"young_adult", "adult"},
        "roles": {"mc", "protagonist", "hero", "leader"},
        "positive": {"powerful", "confident", "firm", "serious", "dominant", "deep", "commanding"},
        "negative": {"elderly", "old", "nervous", "child"},
    },
    "M_ANTAG_YOUNG_ARROGANT": {
        "sex": "male", "ages": {"teen", "young_adult"},
        "roles": {"antagonist", "villain", "rival", "enemy"},
        "positive": {"arrogant", "mocking", "confident", "energetic", "contemptuous", "cold", "rival", "young"},
        "negative": {"elderly", "old", "wise", "fatherly", "gentle"},
    },
    "M_ANTAG_MATURE_DOMINANT": {
        "sex": "male", "ages": {"adult"},
        "roles": {"antagonist", "villain", "leader", "enemy"},
        "positive": {"mature", "dominant", "authoritative", "firm", "threatening", "serious", "leader", "deep"},
        "negative": {"teen", "child", "nervous", "bright"},
    },
    "M_ANTAG_OLD_MENACING": {
        "sex": "male", "ages": {"elderly"},
        "roles": {"antagonist", "villain", "elder", "master", "enemy"},
        "positive": {"old", "elderly", "deep", "menacing", "rough", "authoritative", "wise"},
        "negative": {"teen", "young", "bright"},
    },
    "F_LEAD_WARM": {
        "sex": "female", "ages": {"teen", "young_adult"},
        "roles": {"female_lead", "heroine", "lead_female"},
        "positive": {"warm", "tender", "soft", "calm", "neutral", "clear", "versatile"},
        "negative": {"elderly", "old", "dominant", "cold"},
    },
    "F_LEAD_EXPRESSIVE": {
        "sex": "female", "ages": {"teen", "young_adult"},
        "roles": {"female_lead", "heroine", "lead_female"},
        "positive": {"expressive", "energetic", "bright", "reactive", "lively", "young"},
        "negative": {"elderly", "old", "restrained"},
    },
    "F_LEAD_COLD": {
        "sex": "female", "ages": {"young_adult", "adult"},
        "roles": {"female_lead", "heroine", "rival", "antagonist"},
        "positive": {"cold", "controlled", "calm", "serious", "confident", "low"},
        "negative": {"child", "bratty", "nervous", "bright"},
    },
    "F_YOUNG_BRATTY": {
        "sex": "female", "ages": {"child", "teen"}, "compatible_ages": {"young_adult"},
        "roles": {"female_lead", "supporting", "student", "rival"},
        "positive": {"bratty", "insolent", "mocking", "reactive", "bright", "energetic", "young"},
        "negative": {"elderly", "mature", "motherly", "restrained"},
    },
    "F_MATURE_DOMINANT": {
        "sex": "female", "ages": {"adult"},
        "roles": {"female_lead", "antagonist", "leader", "mentor"},
        "positive": {"mature", "dominant", "authoritative", "confident", "firm", "elegant", "controlled"},
        "negative": {"child", "teen", "nervous"},
    },
    "M_SUPPORT_YOUNG": {
        "sex": "male", "ages": {"teen", "young_adult"},
        "roles": {"supporting", "secondary", "ally", "student", "rival"},
        "positive": {"young", "neutral", "calm", "bright", "energetic", "reactive", "versatile"},
        "negative": {"elderly", "old"},
    },
    "M_SUPPORT_MATURE": {
        "sex": "male", "ages": {"adult", "elderly"},
        "roles": {"supporting", "secondary", "mentor", "father", "elder", "merchant"},
        "positive": {"mature", "stable", "warm", "calm", "measured", "wise", "neutral"},
        "negative": {"child", "teen"},
    },
    "F_SUPPORT_YOUNG": {
        "sex": "female", "ages": {"teen", "young_adult"},
        "roles": {"supporting", "secondary", "ally", "student"},
        "positive": {"young", "neutral", "bright", "calm", "reactive", "versatile"},
        "negative": {"elderly", "old"},
    },
    "F_SUPPORT_MATURE": {
        "sex": "female", "ages": {"adult", "elderly"},
        "roles": {"supporting", "secondary", "mentor", "mother", "elder"},
        "positive": {"mature", "stable", "calm", "controlled", "wise", "neutral"},
        "negative": {"child", "teen"},
    },
}


def _tokens(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        raw = " ".join(str(item or "") for item in value)
    else:
        raw = str(value or "")
    return {token for token in re.split(r"[^a-z0-9_]+", raw.casefold()) if token}


def _speaker_tokens(speaker: Any) -> set[str]:
    return _tokens([
        getattr(speaker, "name", ""), getattr(speaker, "role", ""),
        getattr(speaker, "character_role", ""), getattr(speaker, "voice_archetype", ""),
    ])


def _profile_tokens(profile: dict[str, Any]) -> set[str]:
    return _tokens([
        profile.get("id"), profile.get("name"), profile.get("description"),
        profile.get("personality"), profile.get("primary_role"), profile.get("roles"),
        profile.get("traits"), profile.get("casting_tags"), profile.get("voice_archetype"),
        profile.get("age"), profile.get("age_group"), profile.get("pitch"),
    ])


def _profile_gender(profile: dict[str, Any]) -> str:
    declared = str(profile.get("gender") or "").strip().lower()
    if declared in {"male", "female"}:
        return declared
    pid = str(profile.get("id") or "")
    if re.search(r"(?:^|-)M\d+$", pid, re.IGNORECASE):
        return "male"
    if re.search(r"(?:^|-)F\d+$", pid, re.IGNORECASE):
        return "female"
    return "unspecified"


def _normalise_age(value: Any) -> str:
    age = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "teenager": "teen", "young": "young_adult", "youngadult": "young_adult",
        "middle_aged": "adult", "middleaged": "adult", "mature": "adult",
        "senior": "elderly", "elder": "elderly", "old": "elderly",
    }
    return aliases.get(age, age or "unknown")


def _age_compatible(wanted: str, actual: str) -> tuple[bool, int]:
    wanted = _normalise_age(wanted)
    actual = _normalise_age(actual)
    if wanted in {"", "unknown", "uncertain"} or actual in {"", "unknown", "unspecified"}:
        return True, 0
    if wanted == actual:
        return True, 90
    adjacent = {
        ("teen", "young_adult"), ("young_adult", "teen"),
        ("young_adult", "adult"), ("adult", "young_adult"),
        ("adult", "elderly"), ("elderly", "adult"),
    }
    if (wanted, actual) in adjacent:
        return True, 15
    # Do not make a child sound elderly or an elderly person sound like a teen.
    if {wanted, actual} in ({"child", "elderly"}, {"teen", "elderly"}, {"child", "adult"}):
        return False, -1000
    return True, -35


def _role_aliases(render_key: str) -> set[str]:
    key = str(render_key or "").strip().lower()
    aliases = {
        "narrator": {"narrator", "narration", "storyteller", "recap"},
        "mc": {"mc", "protagonist", "hero", "lead_male", "main_character"},
        "female_lead": {"female_lead", "heroine", "lead_female", "femalelead"},
        "antagonist": {"antagonist", "villain", "rival", "enemy"},
        "supporting": {"supporting", "secondary", "mentor", "ally", "parent", "npc"},
        "system": {"system", "announcement", "interface"},
        "creature": {"creature", "monster", "beast"},
    }
    return aliases.get(key, {key} if key else set())


def _best_existing_speaker(state: Any, render_key: str, character_name: str = "") -> Any | None:
    aliases = _role_aliases(render_key)
    wanted_name = character_name.strip().casefold()
    ranked: list[tuple[int, str, Any]] = []
    for speaker in list(getattr(state, "speakers", []) or []):
        tokens = _speaker_tokens(speaker)
        score = 0
        name = str(getattr(speaker, "name", "") or "")
        if wanted_name and name.casefold() == wanted_name:
            score += 600
        if aliases & tokens:
            score += 260
        role = str(getattr(speaker, "role", "") or "").casefold()
        if any(alias in role for alias in aliases):
            score += 120
        if getattr(speaker, "voice_profile_id", None):
            score += 80
        if bool(getattr(speaker, "voice_locked", False)):
            score += 120
        if score:
            ranked.append((score, name, speaker))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], item[1].casefold()))
    return ranked[0][2]


def _archetype_signature_score(archetype: str, profile: dict[str, Any]) -> tuple[int, list[str]]:
    signature = ARCHETYPE_SIGNATURES.get(str(archetype or "").strip().upper())
    if not signature:
        return 0, []
    tokens = _profile_tokens(profile)
    score = 0
    reasons: list[str] = []
    roles = set(signature.get("roles") or set())
    positives = set(signature.get("positive") or set())
    negatives = set(signature.get("negative") or set())
    role_hits = roles & tokens
    positive_hits = positives & tokens
    negative_hits = negatives & tokens
    actual_age = _normalise_age(profile.get("age_group") or profile.get("age"))
    preferred_ages = {str(value) for value in (signature.get("ages") or set())}
    compatible_ages = {str(value) for value in (signature.get("compatible_ages") or set())}
    if actual_age and actual_age in preferred_ages:
        # Archetype age is stronger than a generic role hit. This matters for
        # cases such as F_YOUNG_BRATTY, where a reactive teen is safer than an
        # expressive adult female lead even if both are otherwise plausible.
        score += 220 if archetype == "F_YOUNG_BRATTY" else 150
        reasons.append("signature_age")
    elif actual_age and actual_age in compatible_ages:
        score += 35
        reasons.append("signature_age_compatible")
    elif preferred_ages and actual_age not in {"", "unknown", "unspecified"}:
        score -= 55
        reasons.append("signature_age_penalty")
    if role_hits:
        score += min(160, 55 * len(role_hits))
        reasons.append("signature_role:" + ",".join(sorted(role_hits)))
    if positive_hits:
        score += min(220, 45 * len(positive_hits))
        reasons.append("signature_traits:" + ",".join(sorted(positive_hits)))
    if negative_hits:
        score -= min(260, 80 * len(negative_hits))
        reasons.append("signature_penalty:" + ",".join(sorted(negative_hits)))
    return score, reasons


def _best_profile(
    *,
    render_key: str,
    voice_archetype: str,
    sex: str,
    age_group: str,
    language: str,
    temperament: list[str] | None,
    presence: str,
    emotionality: str,
    character_role: str,
    excluded_ids: set[str],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    aliases = _role_aliases(render_key)
    archetype = str(voice_archetype or "").strip().upper()
    wanted_sex = str(sex or "").strip().lower()
    wanted_age = _normalise_age(age_group)
    wanted_language = str(language or "").strip().lower().split("-", 1)[0]
    wanted_traits = _tokens([temperament or [], presence, emotionality, character_role])
    ranked: list[tuple[int, str, dict[str, Any], list[str]]] = []

    for profile in local_voice_service.profiles():
        pid = str(profile.get("id") or "")
        if not pid or pid in excluded_ids or not bool(profile.get("enabled", True)):
            continue
        scope = str(profile.get("usage_scope") or "both").strip().lower()
        if scope not in {"both", "multi", "multi-speaker", "multispeaker"}:
            continue

        psex = _profile_gender(profile)
        # Gender is a hard constraint when both sides are known. No more male->female
        # casting simply because a role score happened to be larger.
        if wanted_sex in {"male", "female"} and psex in {"male", "female"} and psex != wanted_sex:
            continue

        actual_age = _normalise_age(profile.get("age_group") or profile.get("age"))
        age_ok, age_score = _age_compatible(wanted_age, actual_age)
        if not age_ok:
            continue

        tokens = _profile_tokens(profile)
        score = age_score
        reasons: list[str] = []
        if age_score > 0:
            reasons.append("age")

        p_arch = str(profile.get("voice_archetype") or "").strip().upper()
        if archetype:
            if p_arch == archetype:
                score += 1200
                reasons.append("exact_archetype")
            else:
                signature_score, signature_reasons = _archetype_signature_score(archetype, profile)
                score += signature_score
                reasons.extend(signature_reasons)

        primary = str(profile.get("primary_role") or "").strip().lower()
        if primary == render_key:
            score += 260
            reasons.append("primary_role")
        role_hits = aliases & tokens
        if role_hits:
            score += min(220, 80 * len(role_hits))
            reasons.append("role:" + ",".join(sorted(role_hits)))

        if wanted_sex in {"male", "female"} and psex == wanted_sex:
            score += 150
            reasons.append("sex")

        trait_hits = wanted_traits & tokens
        if trait_hits:
            score += min(180, 45 * len(trait_hits))
            reasons.append("traits:" + ",".join(sorted(trait_hits)))

        plang = str(profile.get("language") or "multi").strip().lower().split("-", 1)[0]
        if wanted_language:
            if plang in {wanted_language, "multi", "multilingual", ""}:
                score += 70
                reasons.append("language")
            else:
                score -= 140

        engine = str(profile.get("default_engine") or profile.get("preset_engine") or "").lower()
        if engine == "tts-omnivoice-hq" or "omnivoice" in engine:
            score += 35
        if bool(profile.get("locked", False)):
            score += 20

        # If an explicit archetype was requested, a generic role match alone is not
        # enough. Require either exact metadata or a useful signature match.
        minimum = 420 if archetype else 260
        if score >= minimum:
            ranked.append((score, pid, profile, reasons))

    if not ranked:
        return None, {
            "resolver": RESOLVER_VERSION,
            "requested_archetype": archetype or None,
            "status": "unresolved",
            "score": None,
            "reasons": ["no_safe_compatible_profile"],
        }
    ranked.sort(key=lambda item: (-item[0], item[1]))
    score, pid, profile, reasons = ranked[0]
    return profile, {
        "resolver": RESOLVER_VERSION,
        "requested_archetype": archetype or None,
        "resolved_profile_id": pid,
        "resolved_profile_archetype": str(profile.get("voice_archetype") or "").strip().upper() or None,
        "status": "exact" if str(profile.get("voice_archetype") or "").strip().upper() == archetype and archetype else "inferred",
        "score": score,
        "reasons": reasons,
    }


def _clone_speaker(
    template: Any,
    *,
    name: str,
    role: str,
    color: str,
    profile: dict[str, Any] | None,
    metadata: dict[str, Any],
) -> Any:
    update: dict[str, Any] = {
        "name": name,
        "role": role,
        "color": color,
        "duration": "--",
        "level": int(getattr(template, "level", 72) or 72),
        "voice_profile_id": str((profile or {}).get("id") or "") or None,
        "voice_engine": str((profile or {}).get("default_engine") or (profile or {}).get("preset_engine") or "") or None,
        "voice_model": str((profile or {}).get("preset_voice_id") or "") or None,
        "voice_instruct": getattr(template, "voice_instruct", None),
        "effects_chain": list(getattr(template, "effects_chain", []) or []),
    }
    for key in (
        "character_id", "character_name", "character_role", "sex", "age_group", "importance",
        "dedicated_voice", "voice_archetype", "render_voice_key", "casting_confidence",
        "casting_status", "identity_locked", "voice_locked",
    ):
        if hasattr(template, key):
            update[key] = metadata.get(key)
    if hasattr(template, "model_copy"):
        return template.model_copy(update=update)
    for key, value in update.items():
        try:
            setattr(template, key, value)
        except Exception:
            pass
    return template


def _color(character_id: str) -> str:
    palette = ("#39c6bd", "#7c9cff", "#d990f7", "#f0a85b", "#62c98d", "#e77c8f", "#8cb7e8", "#c5a56a")
    return palette[sum(ord(ch) for ch in str(character_id or "NARRATOR")) % len(palette)]


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\wÀ-ÿ'’-]+\b", str(text or ""), flags=re.UNICODE))


def _mark_voice_manifest_stale(project_dir: Path, changed_ids: list[str]) -> None:
    if not changed_ids:
        return
    path = project_dir / "audio" / "voice_manifest.json"
    if not path.is_file():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    payload.update({
        "stale": True,
        "stale_reason": "Casting Intelligence R4 changed the speaker/voice assignment",
        "invalidated_at": datetime.now(timezone.utc).isoformat(),
        "changed_segment_ids": sorted(set(changed_ids)),
    })
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def apply_casting(*, project_dir: Path, state: Any, preview: dict[str, Any]) -> dict[str, Any] | None:
    registry = [dict(item) for item in (preview.get("character_registry") or []) if isinstance(item, dict)]
    entries = [dict(item) for item in (preview.get("entries") or []) if isinstance(item, dict)]
    has_r4 = bool(preview.get("casting_r4")) or any(
        isinstance(unit, dict) and str(unit.get("render_voice_key") or "").strip()
        for entry in entries for unit in (entry.get("voice_units") or [])
    )
    if not registry or not entries or not has_r4:
        return None

    speakers = list(getattr(state, "speakers", []) or [])
    if not speakers:
        return None
    template = speakers[0]
    registry_by_id = {
        str(item.get("character_id") or "").strip().upper(): item
        for item in registry if str(item.get("character_id") or "").strip()
    }
    entry_by_id = {str(item.get("id") or ""): item for item in entries}
    target_language = str(getattr(state, "target_language", "") or "en")
    used_profile_ids: set[str] = set()
    cast_speakers: dict[str, Any] = {}
    unresolved: list[str] = []
    mixed: list[dict[str, Any]] = []
    changed: list[str] = []
    segment_cast: dict[str, dict[str, Any]] = {}
    character_cast: dict[str, dict[str, Any]] = {}

    def ensure(render_key: str, character_id: str, unit: dict[str, Any]) -> Any | None:
        render = str(render_key or "").strip().lower()
        source_cid = str(character_id or "").strip().upper()
        cid = source_cid
        item = registry_by_id.get(cid) or {}
        if render == "narrator":
            cid = "NARRATOR"
            item = {
                "character_id": "NARRATOR", "character_name": "Narrator",
                "character_role": "external_narrator", "importance": "primary",
                "sex": "uncertain", "age_group": "adult", "dedicated_voice": True,
                "casting_confidence": 1.0, "casting_status": "locked",
                "identity_locked": True, "voice_locked": True,
                "temperament": ["stable"], "presence": "high", "emotionality": "balanced",
            }
        elif render == "system":
            cid = "SYSTEM"
            item = registry_by_id.get(cid) or {
                "character_id": "SYSTEM", "character_name": "System", "character_role": "system",
                "importance": "supporting", "sex": "uncertain", "age_group": "unknown",
                "dedicated_voice": True, "casting_confidence": 1.0, "casting_status": "locked",
                "identity_locked": True, "voice_locked": True,
            }
        if not item:
            return None
        cache_key = f"{cid}:{render}"
        if cache_key in cast_speakers:
            return cast_speakers[cache_key]

        name = (
            "Narrator" if cid == "NARRATOR" else
            "System" if cid == "SYSTEM" else
            str(item.get("character_name") or unit.get("character_name") or cid).strip() or cid
        )
        existing = _best_existing_speaker(state, render, name)
        profile = None
        match: dict[str, Any] = {
            "resolver": RESOLVER_VERSION, "status": "unresolved", "score": None,
            "requested_archetype": str(item.get("voice_archetype") or unit.get("voice_archetype") or "").strip().upper() or None,
            "reasons": [],
        }
        if existing and getattr(existing, "voice_profile_id", None):
            profile = local_voice_service.get(str(existing.voice_profile_id))
            if profile is not None:
                match.update({
                    "status": "preserved_existing",
                    "resolved_profile_id": str(profile.get("id") or ""),
                    "resolved_profile_archetype": str(profile.get("voice_archetype") or "").strip().upper() or None,
                    "score": 9999,
                    "reasons": ["existing_speaker_assignment_preserved"],
                })

        if profile is None and str(item.get("casting_status") or "").lower() != "needs_review":
            profile, match = _best_profile(
                render_key=render,
                voice_archetype=str(item.get("voice_archetype") or unit.get("voice_archetype") or ""),
                sex=str(item.get("sex") or ""),
                age_group=str(item.get("age_group") or ""),
                language=target_language,
                temperament=[str(v) for v in (item.get("temperament") or []) if str(v).strip()],
                presence=str(item.get("presence") or ""),
                emotionality=str(item.get("emotionality") or ""),
                character_role=str(item.get("character_role") or unit.get("character_role") or ""),
                excluded_ids=(set() if render in {"narrator", "mc", "system", "creature"} else used_profile_ids),
            )

        if profile is None and existing is None:
            character_cast.setdefault(source_cid, {}).update({
                "source_character_id": source_cid,
                "render_voice_key": render,
                "voice_archetype": str(item.get("voice_archetype") or unit.get("voice_archetype") or "") or None,
                "profile_match": match,
                "status": "unresolved",
            })
            return None
        if profile and render not in {"narrator", "mc", "system", "creature"}:
            used_profile_ids.add(str(profile.get("id") or ""))

        metadata = {
            "character_id": cid,
            "character_name": name,
            "character_role": str(item.get("character_role") or unit.get("character_role") or render),
            "sex": str(item.get("sex") or "uncertain"),
            "age_group": str(item.get("age_group") or "unknown"),
            "importance": str(item.get("importance") or "supporting"),
            "dedicated_voice": bool(item.get("dedicated_voice", render not in {"narrator", "unknown"})),
            "voice_archetype": str(item.get("voice_archetype") or unit.get("voice_archetype") or "") or None,
            "render_voice_key": render,
            "casting_confidence": float(item.get("casting_confidence") or item.get("confidence") or 0),
            "casting_status": str(item.get("casting_status") or "locked"),
            "identity_locked": bool(item.get("identity_locked", False)),
            "voice_locked": bool(item.get("voice_locked", False)),
        }
        base = existing or template
        speaker = _clone_speaker(
            base,
            name=name,
            role=f"R4 · {metadata['importance']} · {metadata['character_role']}",
            color=(str(getattr(existing, "color", "")) if existing else "") or _color(cid),
            profile=profile,
            metadata=metadata,
        )
        cast_speakers[cache_key] = speaker
        character_cast[source_cid] = {
            "source_character_id": source_cid,
            "render_character_id": cid,
            "speaker": name,
            "render_voice_key": render,
            "voice_archetype": metadata["voice_archetype"],
            "profile_id": getattr(speaker, "voice_profile_id", None),
            "profile_match": match,
            "status": "resolved" if getattr(speaker, "voice_profile_id", None) else "speaker_without_profile",
        }
        return speaker

    for segment in list(getattr(state, "segments", []) or []):
        entry = entry_by_id.get(str(getattr(segment, "id", "")))
        units = [dict(unit) for unit in ((entry or {}).get("voice_units") or []) if isinstance(unit, dict)]
        if not units:
            continue
        candidates: list[tuple[int, int, dict[str, Any]]] = []
        renders: set[str] = set()
        for unit in units:
            render = str(unit.get("render_voice_key") or unit.get("voice_key") or "").strip().lower()
            if not render:
                continue
            renders.add(render)
            cid = str(unit.get("character_id") or "").strip().upper()
            item = registry_by_id.get(cid) or {}
            importance = str(item.get("importance") or "").lower()
            priority = (
                5 if importance == "primary" and render != "narrator" else
                4 if importance == "major" and render != "narrator" else
                3 if importance == "supporting" and render != "narrator" else
                2 if render != "narrator" else 1
            )
            text = str(unit.get("target_text") or unit.get("translation") or "")
            candidates.append((priority, _word_count(text), unit))
        if not candidates:
            unresolved.append(str(getattr(segment, "id", "")))
            continue
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        chosen = candidates[0][2]
        render = str(chosen.get("render_voice_key") or chosen.get("voice_key") or "").strip().lower()
        source_cid = str(chosen.get("character_id") or "").strip().upper()
        speaker = ensure(render, source_cid, chosen)
        if speaker is None:
            # Never invent a random voice. Preserve the current manual/acoustic speaker
            # and report the unresolved casting for review.
            unresolved.append(str(getattr(segment, "id", "")))
            continue
        old_name = str(getattr(segment, "speaker", "") or "")
        new_name = str(getattr(speaker, "name", "") or "")
        if old_name != new_name:
            changed.append(str(getattr(segment, "id", "")))
        segment.speaker = new_name
        if hasattr(segment, "color"):
            segment.color = str(getattr(speaker, "color", "") or getattr(segment, "color", ""))
        cmeta = character_cast.get(source_cid) or {}
        segment_cast[str(getattr(segment, "id", ""))] = {
            "speaker": new_name,
            "source_character_id": source_cid,
            "render_character_id": "NARRATOR" if render == "narrator" else source_cid,
            "render_voice_key": render,
            "voice_archetype": str(chosen.get("voice_archetype") or registry_by_id.get(source_cid, {}).get("voice_archetype") or "") or None,
            "unit_count": len(units),
            "profile_id": getattr(speaker, "voice_profile_id", None),
            "profile_match": cmeta.get("profile_match"),
        }
        if len(renders) > 1:
            mixed.append({
                "segment_id": str(getattr(segment, "id", "")),
                "render_voice_keys": sorted(renders),
                "selected_render_voice_key": render,
                "policy": "primary-major-supporting-then-longest-until-per-unit-timing",
            })

    referenced = {str(getattr(segment, "speaker", "") or "") for segment in getattr(state, "segments", []) or []}
    final_speakers: list[Any] = []
    seen_names: set[str] = set()
    for speaker in cast_speakers.values():
        name = str(getattr(speaker, "name", "") or "")
        if name and name in referenced and name not in seen_names:
            final_speakers.append(speaker)
            seen_names.add(name)
    # Keep unresolved/manual speakers still referenced by untouched segments.
    for speaker in speakers:
        name = str(getattr(speaker, "name", "") or "")
        if name and name in referenced and name not in seen_names:
            final_speakers.append(speaker)
            seen_names.add(name)
    state.speakers = final_speakers

    duration_by_name: dict[str, float] = {}

    def ts(value: str) -> float:
        parts = str(value or "0").replace(",", ".").split(":")
        try:
            nums = [float(x) for x in parts]
        except ValueError:
            return 0.0
        if len(nums) == 3:
            return nums[0] * 3600 + nums[1] * 60 + nums[2]
        if len(nums) == 2:
            return nums[0] * 60 + nums[1]
        return nums[0] if nums else 0.0

    for segment in getattr(state, "segments", []) or []:
        name = str(getattr(segment, "speaker", "") or "")
        duration_by_name[name] = duration_by_name.get(name, 0.0) + max(
            0.0, ts(getattr(segment, "end", "")) - ts(getattr(segment, "start", ""))
        )
    for speaker in state.speakers:
        try:
            speaker.duration = f"{duration_by_name.get(str(getattr(speaker, 'name', '') or ''), 0.0):.1f}s"
        except Exception:
            pass

    artifact = {
        "version": 3,
        "policy": POLICY_VERSION,
        "resolver": RESOLVER_VERSION,
        "prompt_revision": preview.get("prompt_revision"),
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "character_registry": registry,
        "speaker_sections": preview.get("speaker_sections") or [],
        "character_cast": character_cast,
        "segment_cast": segment_cast,
        "mixed_render_segments": mixed,
        "unresolved_segments": sorted(set(unresolved)),
        "changed_segment_ids": sorted(set(changed)),
        "speaker_count": len(state.speakers),
        "narrator_rendered_segment_count": sum(
            1 for item in segment_cast.values() if item.get("render_voice_key") == "narrator"
        ),
    }
    path = project_dir / "analysis" / "casting_r4.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")
    _mark_voice_manifest_stale(project_dir, changed)
    return artifact
