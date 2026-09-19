from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from functools import lru_cache
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


def sentences(value: str) -> list[str]:
    compact = re.sub(r"\s+", " ", value).strip()
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+", compact) if item.strip()]


def word_count(value: str) -> int:
    return len(value.split())


def allocate(
    chapter_sentences: list[str],
    candidates: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], str]]:
    counts = [word_count(item) for item in chapter_sentences]
    sentence_total = len(chapter_sentences)
    slot_total = len(candidates)

    @lru_cache(maxsize=None)
    def solve(slot_index: int, sentence_index: int) -> tuple[float, tuple[int, ...]]:
        if sentence_index == sentence_total:
            return (0.20 * (slot_total - slot_index), tuple(0 for _ in range(slot_total - slot_index)))
        if slot_index == slot_total:
            return (math.inf, ())

        remaining_capacity = sum(
            int(item["slot"].get("max_words") or 0)
            for item in candidates[slot_index:]
        )
        remaining_words = sum(counts[sentence_index:])
        if remaining_capacity < remaining_words:
            return (math.inf, ())

        best_cost, best_plan = solve(slot_index + 1, sentence_index)
        best_cost += 0.85
        best_plan = (0,) + best_plan

        slot = candidates[slot_index]["slot"]
        maximum = int(slot.get("max_words") or 0)
        ideal = max(1, int(slot.get("ideal_words") or 0))
        packed_words = 0
        for take in range(1, min(10, sentence_total - sentence_index) + 1):
            packed_words += counts[sentence_index + take - 1]
            if packed_words > maximum:
                break
            tail_cost, tail_plan = solve(slot_index + 1, sentence_index + take)
            if not math.isfinite(tail_cost):
                continue
            word_fill_cost = ((packed_words - ideal) ** 2) / (ideal + 1)
            progress_after = (sentence_index + take) / max(1, sentence_total)
            slot_progress = (slot_index + 1) / max(1, slot_total)
            timeline_cost = abs(progress_after - slot_progress) * 6.0
            cost = tail_cost + word_fill_cost + timeline_cost
            if cost < best_cost:
                best_cost = cost
                best_plan = (take,) + tail_plan
        return best_cost, best_plan

    cost, plan = solve(0, 0)
    if not math.isfinite(cost):
        longest = max((word_count(item) for item in chapter_sentences), default=0)
        raise ValueError(
            f"Could not allocate chapter: sentences={sentence_total}, slots={slot_total}, "
            f"words={sum(counts)}, longest_sentence={longest}"
        )

    result: list[tuple[dict[str, Any], str]] = []
    sentence_index = 0
    for candidate, take in zip(candidates, plan, strict=True):
        if take:
            text = " ".join(chapter_sentences[sentence_index : sentence_index + take])
            result.append((candidate, text))
            sentence_index += take
    if sentence_index != sentence_total:
        raise AssertionError(f"Allocation lost sentences: {sentence_index}/{sentence_total}")
    return result


def subtitle_lines(text: str) -> list[str]:
    words = text.split()
    if len(words) <= 12:
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
    slots = {str(item["slot_id"]): item for item in source.get("narration_slots") or []}
    existing_blocks = {
        str(block["slot_id"]): block
        for block in source.get("narration_blocks") or []
    }
    existing = [
        {
            "block": existing_blocks.get(
                str(slot["slot_id"]),
                {
                    "delivery": "neutral",
                    "delivery_intensity": 42,
                    "evidence_ids": list(slot.get("allowed_evidence_ids") or []),
                },
            ),
            "slot": slot,
        }
        for slot in sorted(
            slots.values(),
            key=lambda item: float(item.get("safe_start") or item.get("start") or 0),
        )
        if str(slot.get("sfx_policy") or "") != "protected"
        and int(slot.get("max_words") or 0) > 0
    ]
    script_text = args.script.read_text(encoding="utf-8-sig")
    chapters = list(CHAPTER_RE.finditer(script_text))
    if not chapters:
        raise ValueError("No chapter markers found")

    allocated: list[tuple[dict[str, Any], str]] = []
    chapter_stats: list[dict[str, Any]] = []
    for match in chapters:
        chapter_number = int(match.group("number"))
        start = float(match.group("start"))
        end = float(match.group("end"))
        chapter_sentences = sentences(match.group("body"))
        candidates = [
            item
            for item in existing
            if start <= float(item["slot"]["safe_start"]) < end
            and str(item["slot"].get("sfx_policy") or "") != "protected"
        ]
        chapter_allocated = allocate(chapter_sentences, candidates)
        allocated.extend(chapter_allocated)
        chapter_stats.append(
            {
                "chapter": chapter_number,
                "start": start,
                "end": end,
                "source_words": sum(word_count(item) for item in chapter_sentences),
                "source_sentences": len(chapter_sentences),
                "used_slots": len(chapter_allocated),
            }
        )

    narration_blocks: list[dict[str, Any]] = []
    subtitle_cues: list[dict[str, Any]] = []
    for index, (candidate, text) in enumerate(allocated, start=1):
        old = candidate["block"]
        slot = candidate["slot"]
        count = word_count(text)
        maximum = int(slot.get("max_words") or 0)
        if count > maximum:
            raise ValueError(f"{slot['slot_id']} exceeds its word budget: {count}>{maximum}")
        block_id = f"NAR_{index:04d}"
        narration_blocks.append(
            {
                "block_id": block_id,
                "scene_id": slot["scene_id"],
                "slot_id": slot["slot_id"],
                "planned_start": slot["safe_start"],
                "hard_end": slot["safe_end"],
                "text": text,
                "word_count": count,
                "delivery": old.get("delivery") or "neutral",
                "delivery_intensity": int(old.get("delivery_intensity") or 42),
                "evidence_ids": list(old.get("evidence_ids") or slot.get("allowed_evidence_ids") or [])[:64],
                "ducking_profile": (
                    "none"
                    if str(slot.get("sfx_policy") or "") == "clear"
                    else str(slot.get("recommended_ducking_profile") or "narration_standard")
                ),
            }
        )
        subtitle_cues.append(
            {
                "cue_id": f"SUB_{index:04d}",
                "block_id": block_id,
                "start": slot["safe_start"],
                "end": slot["safe_end"],
                "lines": subtitle_lines(text),
            }
        )

    result["status"] = "scripted"
    result["narration_blocks"] = narration_blocks
    result["subtitle_cues"] = subtitle_cues
    story_bible = result.setdefault("story_bible", {})
    story_bible["narrative_revision"] = "connected-seven-arc-codex-20260811-v3"
    story_bible["narrative_method"] = (
        "A complete seven-arc master narration was written before timeline allocation; "
        "sentences were then assigned chronologically within immutable slot word budgets."
    )
    result["validation"] = {
        "passed": False,
        "errors": [],
        "warnings": ["sfx_analysis_not_supplied"],
        "narrative_revision": "connected-seven-arc-codex-20260811-v3",
        "chapter_stats": chapter_stats,
        "total_narration_words": sum(item["word_count"] for item in narration_blocks),
        "narration_block_count": len(narration_blocks),
        "subtitle_cue_count": len(subtitle_cues),
    }
    validation = story.validate_completed_manifest(source, result)
    result["validation"].update(validation)
    if not validation["passed"]:
        raise ValueError("Connected manifest validation failed: " + "; ".join(validation["errors"]))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "validation": result["validation"],
            },
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
