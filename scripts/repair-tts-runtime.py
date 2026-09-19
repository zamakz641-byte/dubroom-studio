from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from app import engine_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair one DubRoom TTS runtime")
    parser.add_argument("engine_id")
    args = parser.parse_args()
    engine = engine_service.get_engine(args.engine_id)
    if (engine.get("adapter") or "") != "native-tts":
        raise SystemExit(f"Not a native TTS engine: {args.engine_id}")
    engine_service.run_install(args.engine_id, repair=True)
    print(
        json.dumps(
            engine_service.get_engine(args.engine_id).get("installation") or {},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
