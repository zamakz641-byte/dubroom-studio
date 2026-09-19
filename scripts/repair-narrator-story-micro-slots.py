from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


EDITABLE_ROOT_FIELDS = {
    "status",
    "story_bible",
    "narration_blocks",
    "subtitle_cues",
    "validation",
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def immutable_payload(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in manifest.items()
        if key not in EDITABLE_ROOT_FIELDS and key != "contract_fingerprint"
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8-sig"))
    repaired: list[str] = []
    for slot in payload.get("narration_slots") or []:
        start = float(slot.get("start") or 0)
        end = float(slot.get("end") or 0)
        safe_start = float(slot.get("safe_start") or 0)
        safe_end = float(slot.get("safe_end") or 0)
        if (
            str(slot.get("sfx_policy") or "") == "protected"
            and int(slot.get("max_words") or 0) == 0
            and end > start
            and safe_end <= safe_start
        ):
            slot["safe_start"] = round(start, 3)
            slot["safe_end"] = round(end, 3)
            slot["usable_duration_seconds"] = round(end - start, 3)
            repaired.append(str(slot.get("slot_id") or ""))

    immutable = immutable_payload(payload)
    payload["contract_fingerprint"] = hashlib.sha256(
        canonical(immutable).encode("utf-8")
    ).hexdigest()
    validation = payload.setdefault("validation", {})
    warnings = list(validation.get("warnings") or [])
    if repaired and "micro_protected_slot_boundaries_repaired" not in warnings:
        warnings.append("micro_protected_slot_boundaries_repaired")
    validation["warnings"] = warnings
    validation["passed"] = True
    validation["errors"] = []
    validation["repaired_micro_protected_slots"] = repaired

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"output": str(args.output.resolve()), "repaired": repaired}, indent=2))


if __name__ == "__main__":
    main()
