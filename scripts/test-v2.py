from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.export_service import plan_export
from services.api.app import main as api_main


def test_exact_count() -> None:
    plan = plan_export(1_203.5, {
        "delivery": "shorts",
        "segment_strategy": "count",
        "segment_count": 20,
    })
    assert plan["output_count"] == 20
    assert len(plan["regions"]) == 20
    assert plan["regions"][0]["start"] == 0
    assert plan["regions"][-1]["end"] == 1_203.5
    for left, right in zip(plan["regions"], plan["regions"][1:]):
        assert left["end"] == right["start"]


def test_target_duration() -> None:
    plan = plan_export(1_501, {
        "delivery": "shorts",
        "segment_strategy": "duration",
        "segment_duration_seconds": 600,
    })
    assert plan["output_count"] == 3
    assert [region["duration"] for region in plan["regions"]] == [600, 600, 301]


def test_warning_and_manual_regions() -> None:
    many = plan_export(100, {
        "delivery": "shorts",
        "segment_strategy": "count",
        "segment_count": 51,
    })
    assert "export.many_files" in many["warnings"]

    manual = plan_export(100, {
        "delivery": "shorts",
        "segment_strategy": "manual",
        "segment_ranges": [
            {"id": "intro", "name": "Intro", "start": 2, "end": 12, "framing": "blur"},
            {"id": "outro", "name": "Outro", "start": 90, "end": 100, "enabled": False},
        ],
    })
    assert manual["regions"][0]["framing"] == "blur"
    assert manual["output_count"] == 1


def test_recoverable_project_trash() -> None:
    original_projects_root = api_main.PROJECTS_ROOT
    original_trash_root = api_main.TRASH_ROOT
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        projects = root / "projects"
        source = root / "original-source.mp4"
        source.write_bytes(b"source stays outside the project")
        api_main.PROJECTS_ROOT = projects
        api_main.TRASH_ROOT = projects / ".trash"
        try:
            record = api_main.create_project(api_main.ProjectCreateRequest(name="Trash safety test"))
            record.source_path = str(source)
            api_main._write_project_record(projects / record.id, record)

            trashed = api_main.trash_project(record.id)
            assert source.exists()
            assert len(api_main.list_project_trash()["projects"]) == 1

            restored = api_main.restore_project_from_trash(trashed["trash_id"])
            assert restored.id == record.id
            assert (projects / record.id).exists()

            trashed_again = api_main.trash_project(record.id)
            assert api_main.permanently_delete_project(trashed_again["trash_id"])["deleted"]
            assert source.exists()
            assert not api_main.list_project_trash()["projects"]
        finally:
            api_main.PROJECTS_ROOT = original_projects_root
            api_main.TRASH_ROOT = original_trash_root


if __name__ == "__main__":
    test_exact_count()
    test_target_duration()
    test_warning_and_manual_regions()
    test_recoverable_project_trash()
    print("V2 export planner and project trash tests passed")
