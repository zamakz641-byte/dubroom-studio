from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app import main  # noqa: E402


def main_cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_id")
    parser.add_argument("job_type")
    parser.add_argument("--job-id")
    parser.add_argument("--options", default="{}")
    args = parser.parse_args()
    project_dir = main._require_project_dir(args.project_id)
    options = json.loads(args.options)
    job_id = args.job_id
    if not job_id:
        now = datetime.now(timezone.utc).isoformat()
        queued = main._create_queued_job(args.project_id, args.job_type, now, options)
        main._write_job(project_dir, queued)
        job_id = queued.id
    elif options == {}:
        queued = main._read_job(project_dir, job_id)
        if queued:
            options = dict(queued.options or {})
    main._execute_project_job(args.project_id, job_id, args.job_type, options)
    completed = main._read_job(project_dir, job_id)
    print(json.dumps(completed.model_dump(mode="json") if completed else {}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main_cli()
