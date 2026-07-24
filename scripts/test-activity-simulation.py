from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app import activity_service


def main() -> None:
    with TemporaryDirectory(prefix="dubroom-activity-") as temporary:
        activity_service.SIMULATION_ROOT = Path(temporary)

        run = activity_service.create_simulation()
        run_id = run["run_id"]
        assert len(run["activities"]) == len(activity_service.PIPELINE_STEPS)
        assert all(item["status"] == "queued" for item in run["activities"])

        activity_service.run_simulation(run_id, step_delay=0.001)
        completed = [
            item
            for item in activity_service.list_activities()
            if item.get("metadata", {}).get("run_id") == run_id
        ]
        assert len(completed) == len(activity_service.PIPELINE_STEPS)
        assert all(item["status"] == "completed" for item in completed)
        assert all(item["progress"] == 100 for item in completed)

        cancelled_run = activity_service.create_simulation()
        first = cancelled_run["activities"][0]
        activity_service.cancel_simulation(first["source_id"])
        cancelled = [
            item
            for item in activity_service.list_activities()
            if item.get("metadata", {}).get("run_id") == cancelled_run["run_id"]
        ]
        assert all(item["status"] == "cancelled" for item in cancelled)

        removed = activity_service.clear_simulations()
        assert removed == len(activity_service.PIPELINE_STEPS) * 2

        print(
            json.dumps(
                {
                    "ok": True,
                    "pipeline_steps": len(completed),
                    "statuses": sorted({item["status"] for item in completed}),
                    "cancel_recovery": True,
                    "model_weights_used": False,
                    "test_files_remaining": len(list(Path(temporary).glob("*.json"))),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
