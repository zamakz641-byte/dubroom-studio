from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api.app import narrator_story_service as story  # noqa: E402


CHAPTER_RE = re.compile(
    r"\[CHAPTER (?P<number>\d+) \| (?P<start>[\d.]+) \| (?P<end>[\d.]+)\]\s*"
    r"(?P<body>.*?)(?=\n\[CHAPTER|\Z)",
    re.DOTALL,
)
STOPWORDS = {
    "a", "an", "and", "as", "at", "be", "been", "before", "but", "by",
    "for", "from", "had", "has", "have", "he", "her", "his", "in", "into",
    "is", "it", "its", "no", "not", "of", "on", "once", "only", "or", "she",
    "so", "that", "the", "their", "them", "then", "they", "this", "through",
    "to", "too", "until", "was", "were", "when", "while", "with", "would",
}


def word_count(value: str) -> int:
    return len(value.split())


def sentences(value: str) -> list[str]:
    compact = re.sub(r"\s+", " ", value).strip()
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", compact) if item.strip()]


def chunks(value: str, maximum_words: int = 48, target_words: int = 34) -> list[str]:
    result: list[str] = []
    current: list[str] = []
    current_words = 0
    for sentence in sentences(value):
        count = word_count(sentence)
        if count > maximum_words:
            raise ValueError(f"Sentence exceeds {maximum_words} words: {sentence}")
        if current and current_words + count > maximum_words:
            result.append(" ".join(current))
            current = []
            current_words = 0
        current.append(sentence)
        current_words += count
        if current_words >= target_words:
            result.append(" ".join(current))
            current = []
            current_words = 0
    if current:
        if result and word_count(result[-1]) + current_words <= maximum_words:
            result[-1] = f"{result[-1]} {' '.join(current)}"
        else:
            result.append(" ".join(current))
    return result


def tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.lower())
        if len(token) > 2 and token not in STOPWORDS
    }


def similarity(left: str, right: str) -> float:
    left_tokens = tokens(left)
    right_tokens = tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return (overlap / union) * 4.0 + overlap / min(len(left_tokens), len(right_tokens))


def align_chunks(
    chapter_chunks: list[str],
    anchors: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any], int]]:
    aligned: list[tuple[str, dict[str, Any], int]] = []
    previous_index = 0
    for chunk_index, text in enumerate(chapter_chunks):
        expected = round(
            (chunk_index / max(1, len(chapter_chunks) - 1)) * max(0, len(anchors) - 1)
        )
        search_start = max(previous_index, expected - 3)
        search_end = min(len(anchors), expected + 5)
        if search_start >= search_end:
            search_start = min(previous_index, len(anchors) - 1)
            search_end = len(anchors)
        best_index = search_start
        best_score = -math.inf
        for index in range(search_start, search_end):
            semantic = similarity(text, str(anchors[index]["block"].get("text") or ""))
            distance = abs(index - expected)
            score = semantic - distance * 0.65
            if score > best_score:
                best_score = score
                best_index = index
        previous_index = best_index
        aligned.append((text, anchors[best_index], best_index))
    return aligned


def subtitle_lines(text: str) -> list[str]:
    words = text.split()
    if len(words) <= 14:
        return [text]
    midpoint = len(words) // 2
    return [" ".join(words[:midpoint]), " ".join(words[midpoint:])]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    source = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    result = copy.deepcopy(source)
    old_slots = {str(item["slot_id"]): item for item in source.get("narration_slots") or []}
    old_blocks = list(source.get("narration_blocks") or [])
    script_text = args.script.read_text(encoding="utf-8-sig")
    chapter_matches = list(CHAPTER_RE.finditer(script_text))
    if not chapter_matches:
        raise ValueError("No connected-story chapters found")

    plans: list[dict[str, Any]] = []
    chapter_stats: list[dict[str, Any]] = []
    for match in chapter_matches:
        number = int(match.group("number"))
        chapter_start = float(match.group("start"))
        chapter_end = float(match.group("end"))
        chapter_chunks = chunks(match.group("body"))
        anchors = [
            {"block": block, "slot": old_slots[str(block["slot_id"])]}
            for block in old_blocks
            if chapter_start <= float(block["planned_start"]) < chapter_end
        ]
        if not anchors:
            raise ValueError(f"Chapter {number} has no timeline anchors")
        aligned = align_chunks(chapter_chunks, anchors)
        natural_windows = [round(word_count(item[0]) / 2.15 + 1.0, 3) for item in aligned]
        cursor = chapter_start + 0.15
        for position, (text, anchor, anchor_index) in enumerate(aligned):
            count = word_count(text)
            natural_window = natural_windows[position]
            anchor_start = float(anchor["block"]["planned_start"])
            remaining_window = sum(natural_windows[position:]) + max(
                0, len(natural_windows) - position - 1
            ) * 0.65
            latest_start = chapter_end - 0.15 - remaining_window
            start = max(cursor, min(anchor_start, latest_start))
            end = start + natural_window
            end = min(end, chapter_end - 0.15)
            if end <= start:
                raise ValueError(f"Chapter {number} has no remaining timeline for: {text}")

            evidence_ids: list[str] = []
            for nearby in anchors[max(0, anchor_index - 1) : min(len(anchors), anchor_index + 2)]:
                for evidence_id in nearby["block"].get("evidence_ids") or nearby["slot"].get("allowed_evidence_ids") or []:
                    if evidence_id not in evidence_ids:
                        evidence_ids.append(str(evidence_id))
            plans.append(
                {
                    "chapter": number,
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": text,
                    "word_count": count,
                    "delivery": anchor["block"].get("delivery") or "neutral",
                    "delivery_intensity": int(anchor["block"].get("delivery_intensity") or 42),
                    "evidence_ids": evidence_ids[:96],
                }
            )
            cursor = end + 0.65
        chapter_stats.append(
            {
                "chapter": number,
                "start": chapter_start,
                "end": chapter_end,
                "word_count": sum(word_count(item) for item in chapter_chunks),
                "narration_blocks": len(chapter_chunks),
            }
        )

    scenes: list[dict[str, Any]] = []
    narration_slots: list[dict[str, Any]] = []
    narration_blocks: list[dict[str, Any]] = []
    subtitle_cues: list[dict[str, Any]] = []
    for index, plan in enumerate(plans, start=1):
        scene_id = f"SCN_V3_{index:04d}"
        slot_id = f"SLOT_V3_{index:04d}"
        block_id = f"NAR_{index:04d}"
        cue_id = f"SUB_{index:04d}"
        duration = round(float(plan["end"]) - float(plan["start"]), 3)
        maximum = max(int(plan["word_count"]), math.floor(duration * 2.35))
        scenes.append(
            {
                "scene_id": scene_id,
                "start": plan["start"],
                "end": plan["end"],
                "source": "semantic_story_anchor_v3",
                "chapter": plan["chapter"],
            }
        )
        narration_slots.append(
            {
                "slot_id": slot_id,
                "scene_id": scene_id,
                "start": plan["start"],
                "end": plan["end"],
                "duration_seconds": duration,
                "safe_start": plan["start"],
                "safe_end": plan["end"],
                "usable_duration_seconds": duration,
                "ideal_words": int(plan["word_count"]),
                "max_words": maximum,
                "sfx_policy": "duckable",
                "recommended_ducking_profile": "narration_standard",
                "allowed_evidence_ids": plan["evidence_ids"],
            }
        )
        narration_blocks.append(
            {
                "block_id": block_id,
                "scene_id": scene_id,
                "slot_id": slot_id,
                "planned_start": plan["start"],
                "hard_end": plan["end"],
                "text": plan["text"],
                "word_count": plan["word_count"],
                "delivery": plan["delivery"],
                "delivery_intensity": plan["delivery_intensity"],
                "evidence_ids": plan["evidence_ids"],
                "ducking_profile": "narration_standard",
            }
        )
        subtitle_cues.append(
            {
                "cue_id": cue_id,
                "block_id": block_id,
                "start": plan["start"],
                "end": plan["end"],
                "lines": subtitle_lines(str(plan["text"])),
            }
        )

    result["scenes"] = scenes
    result["narration_slots"] = narration_slots
    result["sfx_intervals"] = []
    source_tracks = list(result.get("source_tracks") or [])
    source_tracks.append(
        {
            "kind": "narrative_timeline_v3",
            "origin": "codex_semantic_alignment",
            "revision": "connected-seven-arc-semantic-20260811-v3",
            "sfx_analysis": "not_supplied",
        }
    )
    result["source_tracks"] = source_tracks
    result["status"] = "scripted"
    result["narration_blocks"] = narration_blocks
    result["subtitle_cues"] = subtitle_cues
    result.setdefault("story_bible", {})["narrative_revision"] = (
        "connected-seven-arc-semantic-20260811-v3"
    )
    result["story_bible"]["narrative_method"] = (
        "Codex wrote the complete story in seven connected arcs, grouped it into natural "
        "spoken paragraphs, and aligned each paragraph to the nearest matching source event."
    )
    result["contract_fingerprint"] = story._fingerprint(story.immutable_payload(result))
    result["validation"] = {
        "passed": False,
        "errors": [],
        "warnings": ["sfx_analysis_not_supplied"],
        "narrative_revision": "connected-seven-arc-semantic-20260811-v3",
        "chapter_stats": chapter_stats,
        "total_narration_words": sum(item["word_count"] for item in narration_blocks),
        "narration_block_count": len(narration_blocks),
        "subtitle_cue_count": len(subtitle_cues),
    }
    validation = story.validate_completed_manifest(result, result)
    result["validation"].update(validation)
    if not validation["passed"]:
        raise ValueError("Semantic connected manifest failed: " + "; ".join(validation["errors"]))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"output": str(args.output.resolve()), "validation": result["validation"]},
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
