from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


def request_json(url: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    body = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    request = Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("response", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8766")
    args = parser.parse_args()

    response = json.loads(args.response.read_text(encoding="utf-8"))
    translated = {
        str(item.get("id")): str(item.get("translation") or "").strip()
        for item in response.get("segments", [])
    }
    project_url = f"{args.base_url}/projects/{quote(args.project_id, safe='')}"
    state = request_json(f"{project_url}/analysis/state")
    applied = 0
    missing: list[str] = []
    for segment in state.get("segments", []):
        segment_id = str(segment.get("id") or "")
        text = translated.get(segment_id)
        if text:
            segment["translatedText"] = text
            segment["adaptedText"] = text
            segment["rawTranslation"] = text
            applied += 1
        else:
            missing.append(segment_id)
    state["last_operation"] = "chatgpt_duration_translation"
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    saved = request_json(f"{project_url}/analysis/state", method="PUT", payload=state)
    print(
        json.dumps(
            {
                "ok": True,
                "project_id": args.project_id,
                "applied": applied,
                "missing": missing,
                "revision": saved.get("revision"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
