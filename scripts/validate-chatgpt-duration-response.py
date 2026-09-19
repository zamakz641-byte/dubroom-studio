from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("request", type=Path)
    parser.add_argument("response", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    request = json.loads(args.request.read_text(encoding="utf-8"))
    response = json.loads(args.response.read_text(encoding="utf-8"))
    expected = request.get("segments", [])
    received = response.get("segments", [])
    by_id = {str(item.get("id")): item for item in received}
    duplicate_count = len(received) - len(by_id)
    rows = []
    for source in expected:
        segment_id = str(source["id"])
        translated = str(by_id.get(segment_id, {}).get("translation") or "").strip()
        actual = len(re.sub(r"\s+", "", translated))
        budget = source["budget_non_space_characters"]
        pace = request["voice_calibration"][
            "median_non_space_characters_per_second"
        ]
        estimated_duration = actual / pace if pace else 0
        target_duration = float(source["target_duration_seconds"])
        if not translated:
            status = "missing"
        elif actual < int(budget["minimum"]):
            status = "short"
        elif actual > int(budget["maximum"]):
            status = "long"
        else:
            status = "fit"
        rows.append(
            {
                "id": segment_id,
                "status": status,
                "translation": translated,
                "characters": actual,
                "minimum": int(budget["minimum"]),
                "ideal": int(budget["ideal"]),
                "maximum": int(budget["maximum"]),
                "target_duration_seconds": target_duration,
                "estimated_duration_seconds": round(estimated_duration, 3),
                "estimated_coverage": round(estimated_duration / target_duration, 3)
                if target_duration
                else 1.0,
            }
        )
    counts = {
        status: sum(item["status"] == status for item in rows)
        for status in ("fit", "short", "long", "missing")
    }
    report = {
        "ok": counts["missing"] == 0 and duplicate_count == 0,
        "counts": counts,
        "duplicates": duplicate_count,
        "unexpected_ids": sorted(set(by_id) - {str(item["id"]) for item in expected}),
        "segments": rows,
    }
    output = args.output or args.response.with_name("validation.json")
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"report": str(output), **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
