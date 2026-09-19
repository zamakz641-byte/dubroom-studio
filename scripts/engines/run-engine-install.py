from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a DubRoom engine installer directly.")
    parser.add_argument("engine_id")
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()

    workspace = Path(__file__).resolve().parents[2]
    os.environ.setdefault("DUBROOM_WORKSPACE_ROOT", str(workspace))
    os.environ.setdefault("HF_HOME", str(workspace / "data" / "cache" / "huggingface"))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("TORCH_HOME", str(workspace / "data" / "cache" / "torch"))
    os.environ.setdefault("PIP_CACHE_DIR", str(workspace / "data" / "cache" / "pip"))
    sys.path.insert(0, str(workspace))

    from services.api.app.engine_service import run_install

    run_install(args.engine_id, repair=args.repair, credentials={})


if __name__ == "__main__":
    main()
