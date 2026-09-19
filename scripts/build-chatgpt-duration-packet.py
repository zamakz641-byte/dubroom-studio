from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("--voice-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    project = args.project.resolve()
    manifest = json.loads(
        (project / "analysis" / "asr_manifest.json").read_text(encoding="utf-8")
    )
    media = json.loads(
        (project / "analysis" / "media_manifest.json").read_text(encoding="utf-8")
    )
    voice_report = json.loads(args.voice_report.read_text(encoding="utf-8"))
    profile_id, profile = next(iter(voice_report["profiles"].items()))
    pace = float(profile["characters_per_audio_second"]["median"])
    source_segments = manifest.get("segments", [])
    video_duration = float(
        media.get("media", {}).get("duration_seconds")
        or manifest.get("duration")
        or 0
    )

    segments: list[dict[str, Any]] = []
    for index, segment in enumerate(source_segments):
        start = float(segment.get("start") or 0)
        asr_end = float(segment.get("end") or start)
        next_start = (
            float(source_segments[index + 1].get("start") or asr_end)
            if index + 1 < len(source_segments)
            else video_duration
        )
        window_end = max(asr_end, next_start)
        duration = max(0.4, window_end - start)
        ideal = max(4, round(duration * pace * 0.97))
        minimum = max(3, round(duration * pace * 0.90))
        maximum = max(minimum + 2, round(duration * pace * 1.03))
        segments.append(
            {
                "id": str(segment["id"]),
                "start_seconds": round(start, 3),
                "end_seconds": round(window_end, 3),
                "target_duration_seconds": round(duration, 3),
                "source_text": str(segment.get("text") or "").strip(),
                "budget_non_space_characters": {
                    "minimum": minimum,
                    "ideal": ideal,
                    "maximum": maximum,
                },
            }
        )

    rules = [
        "Keep every id exactly once and in the original order.",
        "Translate and adapt English into idiomatic spoken French, not literal French.",
        "Preserve every fact, name, number, action, point of view and causal relation.",
        "Do not invent story events or generic filler.",
        "Keep the first-person narrator and the tense coherent across adjacent segments.",
        "Each translation must remain inside its own scene; never move information to another id.",
        "Aim for the ideal non-space character count and remain between minimum and maximum whenever meaning permits.",
        "For a short draft, expand naturally through explicit subject, cause, consequence or visual action already present in the source.",
        "For a long draft, compress syntax without removing information.",
        "Use punctuation to preserve natural pauses; do not create long ellipses merely to consume time.",
        "Return strict JSON only, matching the response schema. Do not include explanations outside JSON.",
    ]
    packet = {
        "schema_version": 1,
        "task": "duration_aware_segment_translation",
        "created_at": datetime.now().isoformat(),
        "project_id": media.get("project_id"),
        "source_language": "en",
        "target_language": "fr",
        "narrative_context": {
            "title": "The World Is -100 °C, But I Built a Heated TOWER with Future Weapons!",
            "format": "first-person dramatic recap voice-over",
            "continuity": "A newly reincarnated architect-governor must survive a frozen frontier camp revolt and discovers an upgrade system.",
        },
        "voice_calibration": {
            "profile_id": profile_id,
            "median_non_space_characters_per_second": round(pace, 4),
            "natural_internal_pause_median_seconds": voice_report["overall"][
                "internal_silence_seconds"
            ]["median"],
            "allowed_post_tts_retiming": {
                "maximum_video_speed": 1.08,
                "minimum_audio_speed": 0.96,
                "preserve_pitch": True,
            },
        },
        "rules": rules,
        "response_schema": {
            "segments": [
                {
                    "id": "same id as request",
                    "translation": "French voice-over text only",
                }
            ]
        },
        "segments": segments,
    }
    output_dir = args.output_dir or project / "analysis" / "chatgpt-duration"
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_path = output_dir / "request.json"
    packet_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    instruction_path = output_dir / "INSTRUCTIONS.md"
    instruction_path.write_text(
        "# Réécriture française guidée par la durée\n\n"
        "Lis `request.json` comme un contrat strict. Traduis les segments en français "
        "oral naturel en respectant leurs budgets temporels. Retourne uniquement un objet "
        'JSON de la forme `{\"segments\":[{\"id\":\"asr-001\",\"translation\":\"…\"}]}`. '
        "DubRoom recomptera lui-même les caractères et refusera les identifiants manquants, "
        "dupliqués ou déplacés.\n",
        encoding="utf-8",
    )
    template_path = output_dir / "response-template.json"
    template_path.write_text(
        json.dumps(
            {
                "segments": [
                    {"id": item["id"], "translation": ""}
                    for item in segments
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    total_seconds = sum(item["target_duration_seconds"] for item in segments)
    total_ideal = sum(
        item["budget_non_space_characters"]["ideal"] for item in segments
    )
    print(
        json.dumps(
            {
                "ok": True,
                "packet": str(packet_path),
                "instructions": str(instruction_path),
                "response_template": str(template_path),
                "segments": len(segments),
                "target_seconds": round(total_seconds, 3),
                "ideal_non_space_characters": total_ideal,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
