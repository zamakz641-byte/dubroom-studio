#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import re
import shutil
from pathlib import Path

PATCH_ID = "dubroom-continuous-narration-groups-v1"

GROUP_CODE = r"""
def _voice_group_speaker(segment: SegmentRecord) -> str:
    return str(getattr(segment, "speaker", "") or "").strip()


def _voice_group_context(segment: SegmentRecord) -> str:
    return str(
        getattr(segment, "context_id", "")
        or getattr(segment, "contextId", "")
        or ""
    ).strip()


def _voice_group_text(members: list[SegmentRecord]) -> str:
    text = " ".join(
        _segment_tts_text(member).strip()
        for member in members
        if _segment_tts_text(member).strip()
    )
    text = re.sub(r"\s+([,.;:!?…])", r"\1", text)
    text = re.sub(r"([«“])\s+", r"\1", text)
    text = re.sub(r"\s+([»”])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _voice_group_has_natural_release(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned or re.search(r"[,;:—–-]\s*$", cleaned):
        return False
    return bool(re.search(r"[.!?…][»”\"']?\s*$", cleaned))


def _build_voice_groups(
    segments: list[SegmentRecord],
    *,
    preferred_seconds: float = 6.8,
    maximum_seconds: float = 10.0,
    maximum_gap_seconds: float = 0.75,
    trailing_room_seconds: float = 0.35,
) -> list[dict[str, Any]]:
    # PATCH: dubroom-continuous-narration-groups-v1
    # Adjacent ASR rows share one narrator take; sync anchors remain intact.
    strict = str(os.getenv("DUBROOM_STRICT_SEGMENT_TTS", "")).lower().strip()
    if strict in {"1", "true", "yes", "on"}:
        groups = []
        for segment in segments:
            text = _segment_tts_text(segment).strip()
            if not text:
                continue
            start = _timestamp_seconds(segment.start)
            end = max(start + 0.1, _timestamp_seconds(segment.end))
            groups.append({
                "id": segment.id,
                "lead": segment,
                "members": [segment],
                "member_ids": [segment.id],
                "text": text,
                "timeline_start": start,
                "timeline_end": end,
                "sync_anchors": [{
                    "segment_id": segment.id,
                    "relative_start": 0.0,
                    "relative_end": round(end - start, 3),
                    "absolute_start": round(start, 3),
                    "absolute_end": round(end, 3),
                }],
            })
        return groups

    def setting(name: str, default: float, low: float, high: float) -> float:
        try:
            value = float(os.getenv(name, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    preferred_seconds = setting(
        "DUBROOM_VOICE_GROUP_PREFERRED_SECONDS", preferred_seconds, 3.5, 9.0
    )
    maximum_seconds = setting(
        "DUBROOM_VOICE_GROUP_MAXIMUM_SECONDS",
        maximum_seconds,
        preferred_seconds,
        14.0,
    )
    maximum_gap_seconds = setting(
        "DUBROOM_VOICE_GROUP_MAXIMUM_GAP_SECONDS",
        maximum_gap_seconds,
        0.05,
        1.5,
    )
    trailing_room_seconds = setting(
        "DUBROOM_VOICE_GROUP_TRAILING_ROOM_SECONDS",
        trailing_room_seconds,
        0.0,
        0.8,
    )

    eligible = [s for s in segments if _segment_tts_text(s).strip()]
    raw_groups: list[list[SegmentRecord]] = []
    current: list[SegmentRecord] = []

    for segment in eligible:
        if not current:
            current = [segment]
            continue

        first, previous = current[0], current[-1]
        group_start = _timestamp_seconds(first.start)
        previous_end = _timestamp_seconds(previous.end)
        next_start = _timestamp_seconds(segment.start)
        next_end = max(next_start + 0.1, _timestamp_seconds(segment.end))
        current_duration = max(0.1, previous_end - group_start)
        candidate_duration = max(0.1, next_end - group_start)
        gap = max(0.0, next_start - previous_end)

        old_speaker = _voice_group_speaker(previous)
        new_speaker = _voice_group_speaker(segment)
        speaker_changed = bool(
            old_speaker and new_speaker and old_speaker != new_speaker
        )
        old_context = _voice_group_context(previous)
        new_context = _voice_group_context(segment)
        context_changed = bool(
            old_context and new_context and old_context != new_context
            and current_duration >= 3.2
        )
        natural_release = (
            current_duration >= preferred_seconds
            and _voice_group_has_natural_release(_voice_group_text(current))
        )

        if (
            speaker_changed
            or context_changed
            or gap > maximum_gap_seconds
            or candidate_duration > maximum_seconds
            or natural_release
        ):
            raw_groups.append(current)
            current = [segment]
        else:
            current.append(segment)

    if current:
        raw_groups.append(current)

    groups: list[dict[str, Any]] = []
    for index, members in enumerate(raw_groups):
        start = _timestamp_seconds(members[0].start)
        end = max(start + 0.1, _timestamp_seconds(members[-1].end))
        if index + 1 < len(raw_groups):
            next_start = _timestamp_seconds(raw_groups[index + 1][0].start)
            end += min(trailing_room_seconds, max(0.0, next_start - end - 0.04))

        anchors = []
        for member in members:
            member_start = _timestamp_seconds(member.start)
            member_end = max(member_start + 0.1, _timestamp_seconds(member.end))
            anchors.append({
                "segment_id": member.id,
                "relative_start": round(max(0.0, member_start - start), 3),
                "relative_end": round(max(0.1, member_end - start), 3),
                "absolute_start": round(member_start, 3),
                "absolute_end": round(member_end, 3),
            })

        groups.append({
            "id": members[0].id,
            "lead": members[0],
            "members": members,
            "member_ids": [member.id for member in members],
            "text": _voice_group_text(members),
            "timeline_start": start,
            "timeline_end": max(start + 0.1, end),
            "sync_anchors": anchors,
        })
    return groups
""".strip() + "\n\n"

NATURAL_RECAP = r"""    "natural_recap": {
        "point_of_view": "external_third_person",
        "narrator_role": "A dominant external storyteller who recounts the complete plot.",
        "tone": "Fluid, vivid, conversational and lightly witty when the scene allows it.",
        "prompt": (
            "Rewrite the entire script as one continuous narrator-dominant third-person recap. "
            "The narrator owns the story and guides the listener through actions, causes, reactions "
            "and consequences. Convert first-person recap narration into names or third-person pronouns, "
            "then avoid repeating names when he, him, his, she or her is unambiguous. Convert most spoken "
            "dialogue into indirect narration: explain that a character warns, asks, admits, mocks, refuses "
            "or promises something instead of reproducing a long exchange word for word. Keep direct dialogue "
            "only when it is brief, iconic, emotionally decisive or necessary for a punchline; never build "
            "several consecutive segments as back-and-forth quoted dialogue. Reconstruct sentences across "
            "adjacent transcript boundaries and do not force a full stop at the end of every segment. Use "
            "connectors and varied sentence rhythm so each segment sounds like part of the same living story. "
            "Light humor may come from the narrator's phrasing and timing, but never invent events, motives "
            "or facts. Preserve every verified name, number, negation, relationship and causal link."
        ),
    },
"""

WORKER_RECAP = r"""    "natural_recap": (
        "Write a continuous narrator-dominant third-person recap in natural spoken language. "
        "Convert most character dialogue into indirect narration and keep direct quotes only when "
        "they are brief, iconic, emotionally decisive or essential to a punchline. Never create a "
        "rapid back-and-forth exchange across tiny transcript rows. Reconstruct sentences across "
        "neighboring boundaries, use pronouns when unambiguous, connect causes and consequences, "
        "and add only light narrator humor supported by the existing scene."
    ),
"""


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def find(root: Path, filename: str, markers: tuple[str, ...]) -> Path:
    preferred = [
        root / "services" / "api" / "app" / filename,
        root / "backend" / "app" / filename,
        root / "backend" / filename,
        root / "app" / filename,
    ]
    candidates = [p for p in preferred if p.is_file()] or list(root.rglob(filename))
    valid = []
    for path in candidates:
        try:
            text = read(path)
        except OSError:
            continue
        if all(marker in text for marker in markers):
            valid.append(path)
    if not valid:
        raise FileNotFoundError(f"{filename} not found below {root}")
    return sorted(valid, key=lambda p: (len(p.parts), str(p)))[0]


def patch_main(text: str) -> tuple[str, list[str]]:
    if PATCH_ID in text:
        return text, ["main.py already patched"]
    pattern = re.compile(
        r"(?ms)^def _build_voice_groups\(.*?(?=^def _voice_groups_fingerprint\()"
    )
    text, count = pattern.subn(lambda _match: GROUP_CODE, text, count=1)
    if count != 1:
        raise RuntimeError("Could not safely replace _build_voice_groups")

    for old in (
        "voice-script-v4-strict-segments",
        "voice-script-v5-segment-timing",
        "voice-script-v6-natural-edge-pause",
    ):
        text = text.replace(old, "voice-script-v7-continuous-narration-groups")
    for old in (
        "voice-render-source-v3-strict-segments",
        "voice-render-source-v4-soft-gap-borrow",
        "voice-render-source-v5-natural-edge-pause",
        "voice-render-source-v6-balanced-av-sync",
    ):
        text = text.replace(old, "voice-render-source-v7-continuous-narration-groups")

    text = text.replace(
        "# member_ids always contains exactly this segment in strict mode.",
        "# member_ids may span several ASR rows; only the lead owns the WAV.",
    )
    text = re.sub(
        r'(?m)^(\s+)"member_ids": member_ids,\n',
        r'\1"member_ids": member_ids,\n'
        r'\1"sync_anchors": list(voice_group.get("sync_anchors") or []),\n',
        text,
    )
    text = re.sub(
        r'(?m)^(\s+)"member_ids": context\["member_ids"\],\n',
        r'\1"member_ids": context["member_ids"],\n'
        r'\1"sync_anchors": context.get("sync_anchors") or [],\n',
        text,
    )
    return text, ["continuous TTS groups enabled", "internal sync anchors preserved"]


def patch_profiles(text: str) -> tuple[str, list[str]]:
    notes = []
    if "A dominant external storyteller who recounts the complete plot." not in text:
        pattern = re.compile(
            r'(?ms)^    "natural_recap": \{\n.*?(?=^    "external_narrator": \{)'
        )
        text, count = pattern.subn(lambda _match: NATURAL_RECAP, text, count=1)
        if count != 1:
            raise RuntimeError("natural_recap profile block not found")
        notes.append("natural_recap changed to narrator-dominant")

    old_rules = [
        '"Direct dialogue may retain first-person pronouns only when the source clearly represents spoken dialogue, and it must remain attributed to its speaker.",',
        '"Direct dialogue may retain first-person pronouns, but it must remain attributed to its speaker.",',
    ]
    new_rules = (
        '"Convert most character dialogue into indirect narrated speech. Keep a direct quote only when '
        'it is brief, iconic, emotionally decisive or essential to a punchline.",\n'
        '        "The narrator must remain the dominant voice; never create rapid back-and-forth dialogue '
        'across consecutive short segments.",\n'
        '        "A sentence may continue across adjacent segment boundaries; do not force every segment '
        'to end as a standalone sentence.",'
    )
    for old in old_rules:
        if old in text:
            text = text.replace(old, new_rules, 1)
            notes.append("dialogue contract changed to indirect narration")
            break

    marker = '"turning external narration into invented direct dialogue",'
    if marker in text and '"a script dominated by back-and-forth quoted dialogue",' not in text:
        text = text.replace(
            marker,
            marker
            + '\n            "a script dominated by back-and-forth quoted dialogue",'
            + '\n            "forcing a full sentence ending at every transcript boundary",',
            1,
        )
    return text, notes


def patch_worker(text: str) -> tuple[str, list[str]]:
    notes = []
    if "rapid back-and-forth exchange across tiny transcript rows" not in text:
        pattern = re.compile(
            r'(?ms)^    "natural_recap": \(\n.*?(?=^    "external_narrator": \()'
        )
        text, count = pattern.subn(lambda _match: WORKER_RECAP, text, count=1)
        if count != 1:
            raise RuntimeError("translation_worker natural_recap block not found")
        notes.append("local translation prompt strengthened")

    text = text.replace(
        "Translate exactly one explicitly tagged current line. Context is never part of the output.",
        "Adapt exactly one timeline slice while making it sound like a continuation of the surrounding story. "
        "Context guides syntax, attribution and pronouns but must never be copied into the output.",
    )

    old = (
        '"Translate only the text inside <current_source>. The other tagged blocks are reference only: "\n'
        '                "never translate, continue or echo them. Preserve every fact, action, name, title, number, tense "\n'
        '                "and relationship. Use idiomatic spoken language, correct grammar and natural genre agreement."'
    )
    new = (
        '"Adapt only the timeline slice inside <current_source>, but use neighboring blocks to understand "\n'
        '                "whether its sentence begins earlier or continues later. Never copy neighboring facts into "\n'
        '                "this slice. In narrator-dominant profiles, convert most dialogue into indirect narration "\n'
        '                "and keep only short iconic quotes. Preserve every fact, name, number, negation and relationship. "\n'
        '                "Do not force a full stop when the thought clearly continues in the next segment."'
    )
    if old in text:
        text = text.replace(old, new, 1)
        notes.append("neighboring ASR rows now guide sentence continuity")

    old_voice = (
        'f"You are a senior {target} dubbing script adapter. Rewrite each complete "\n'
        '                        "utterance for natural neural speech at 1.0x speed. Preserve every event, "'
    )
    new_voice = (
        'f"You are a senior {target} dubbing script adapter. Rewrite each grouped utterance "\n'
        '                        "for natural neural speech at 1.0x speed. Use one dominant external narrator. "\n'
        '                        "Convert most dialogue into indirect narration and keep a quote only for a "\n'
        '                        "brief iconic reaction, emotional turning point or punchline. Never restart "\n'
        '                        "at internal transcript boundaries. Preserve every event, "'
    )
    if old_voice in text:
        text = text.replace(old_voice, new_voice, 1)
        notes.append("voice-script adaptation changed to narrator-dominant")
    return text, notes


def backup(root: Path, files: list[Path]) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = root / ".dubroom_patch_backup" / stamp
    for path in files:
        relative = path.relative_to(root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    (destination / "backup.json").write_text(
        json.dumps({"files": [str(p.relative_to(root)) for p in files]}, indent=2),
        encoding="utf-8",
    )
    return destination


def restore(root: Path, name: str) -> None:
    base = root / ".dubroom_patch_backup"
    choices = sorted([p for p in base.iterdir() if p.is_dir()], reverse=True)
    chosen = choices[0] if name == "latest" else base / name
    data = json.loads((chosen / "backup.json").read_text(encoding="utf-8"))
    for relative in data["files"]:
        shutil.copy2(chosen / relative, root / relative)
        print("RESTORED", root / relative)


def clear_cache(root: Path) -> int:
    removed = 0
    for audio in root.rglob("audio"):
        if not audio.is_dir():
            continue
        for name in ("voice_manifest.json", "sync_plan.json", "voiceover.wav"):
            path = audio / name
            if path.is_file():
                path.unlink()
                removed += 1
        for folder in (audio, audio / "raw"):
            if folder.is_dir():
                for wav in folder.glob("*.wav"):
                    wav.unlink()
                    removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--clear-voice-cache", action="store_true")
    parser.add_argument("--restore", metavar="BACKUP")
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()

    if args.restore:
        restore(root, args.restore)
        return 0

    main_path = find(root, "main.py", ("def _build_voice_groups(", "voice_generation"))
    profiles_path = find(
        root, "narrative_profiles.py", ("NARRATIVE_PROFILES", "def exchange_contract(")
    )
    worker_path = find(
        root,
        "translation_worker.py",
        ("NARRATIVE_PROFILES", "run_llama_voice_script_adapt"),
    )

    originals = {
        main_path: read(main_path),
        profiles_path: read(profiles_path),
        worker_path: read(worker_path),
    }
    patched_main, main_notes = patch_main(originals[main_path])
    patched_profiles, profile_notes = patch_profiles(originals[profiles_path])
    patched_worker, worker_notes = patch_worker(originals[worker_path])
    patched = {
        main_path: patched_main,
        profiles_path: patched_profiles,
        worker_path: patched_worker,
    }

    for path, text in patched.items():
        ast.parse(text, filename=str(path))

    changed = [path for path in patched if patched[path] != originals[path]]
    print("DubRoom:", root)
    print("main.py:", main_path)
    print("narrative_profiles.py:", profiles_path)
    print("translation_worker.py:", worker_path)
    for note in main_notes + profile_notes + worker_notes:
        print("-", note)

    if args.dry_run:
        print("DRY RUN:", len(changed), "file(s) would change")
        return 0
    if not changed:
        print("Patch already installed")
        return 0

    backup_dir = backup(root, changed)
    try:
        for path in changed:
            path.write_text(patched[path], encoding="utf-8")
    except Exception:
        for path in changed:
            shutil.copy2(backup_dir / path.relative_to(root), path)
        raise

    print("PATCHED:", len(changed), "file(s)")
    print("BACKUP:", backup_dir)
    if args.clear_voice_cache:
        print("CACHE REMOVED:", clear_cache(root), "artifact(s)")
    print("Restart DubRoom, regenerate the script, then regenerate all voices.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
