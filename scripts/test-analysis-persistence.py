from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.main import (  # noqa: E402
    ProjectAnalysisState,
    SegmentRecord,
    _read_or_create_analysis_state,
    _write_analysis_state,
)


def segment() -> SegmentRecord:
    return SegmentRecord(
        id="asr-001",
        left=0,
        width=10,
        lane=0,
        speaker="Narrator",
        label="ASR 1",
        color="#39c6bd",
        start="00:00:00.000",
        end="00:00:03.000",
        sourceText="He entered the gate.",
        translatedText="",
        adaptedText="",
        emotion="Neutral",
        intensity=35,
        pace=100,
        fit=0,
        locked=False,
    )


def main() -> None:
    with TemporaryDirectory(prefix="dubroom-state-") as temporary:
        project_dir = Path(temporary)
        state = ProjectAnalysisState(
            speakers=[],
            segments=[segment()],
            updated_at="2026-01-01T00:00:00+00:00",
            source_language="en",
            target_language="fr",
            narrative_profile="natural_recap",
        )
        _write_analysis_state(project_dir, state)
        assert state.revision == 1

        state.segments[0].translatedText = "Il franchit le portail."
        state.narrative_profile = "mc_first_person"
        state.last_operation = "translation"
        _write_analysis_state(project_dir, state)
        assert state.revision == 2

        state_path = project_dir / "analysis" / "state.json"
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert saved["segments"][0]["sourceText"] == "He entered the gate."
        assert saved["segments"][0]["translatedText"] == "Il franchit le portail."
        assert saved["narrative_profile"] == "mc_first_person"
        assert (project_dir / "analysis" / "history" / "state-r00000002.json").is_file()

        state_path.write_text("{corrupt", encoding="utf-8")
        recovered = _read_or_create_analysis_state(project_dir)
        assert recovered.segments[0].sourceText == "He entered the gate."
        assert recovered.segments[0].translatedText == "Il franchit le portail."
        assert recovered.narrative_profile == "mc_first_person"
        assert recovered.revision >= 2

        empty_overwrite = recovered.model_copy(
            deep=True,
            update={"segments": [], "last_operation": "stale_ui_state"},
        )
        try:
            _write_analysis_state(project_dir, empty_overwrite)
        except ValueError as exc:
            assert "refusing to overwrite" in str(exc)
        else:
            raise AssertionError("A stale empty state overwrote a populated script")
        still_populated = _read_or_create_analysis_state(project_dir)
        assert len(still_populated.segments) == 1
        assert still_populated.segments[0].translatedText == "Il franchit le portail."

        lost_project = project_dir / "lost-project"
        analysis_dir = lost_project / "analysis"
        analysis_dir.mkdir(parents=True)
        empty_state = ProjectAnalysisState(
            speakers=[],
            segments=[],
            updated_at="2026-01-01T00:00:00+00:00",
            source_language="en",
            target_language="fr",
        )
        _write_analysis_state(lost_project, empty_state)
        (analysis_dir / "asr_manifest.json").write_text(
            json.dumps(
                {
                    "duration": 3,
                    "language": "en",
                    "segments": [
                        {
                            "id": "asr-001",
                            "start": 0,
                            "end": 3,
                            "text": "He entered the gate.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (analysis_dir / "translation_final.json").write_text(
            json.dumps(
                {
                    "translations": [
                        {
                            "id": "asr-001",
                            "raw_text": "Il entra dans le portail.",
                            "text": "À cet instant, il franchit le portail.",
                            "fidelity_score": 100,
                            "fidelity_issues": [
                                "candidate added content not present in source"
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        restored_artifacts = _read_or_create_analysis_state(lost_project)
        assert len(restored_artifacts.segments) == 1
        assert restored_artifacts.segments[0].sourceText == "He entered the gate."
        assert (
            restored_artifacts.segments[0].translatedText
            == "À cet instant, il franchit le portail."
        )
        assert restored_artifacts.segments[0].fidelityIssues == [
            {
                "type": "model_review",
                "detail": "candidate added content not present in source",
            }
        ]
        assert restored_artifacts.last_operation == "artifact_recovery"
        round_trip = ProjectAnalysisState.model_validate_json(
            (analysis_dir / "state.json").read_text(encoding="utf-8")
        )
        assert len(round_trip.segments) == 1

    print(
        json.dumps(
            {
                "ok": True,
                "checks": [
                    "atomic revision increments",
                    "transcript and translation coexist",
                    "narrative profile persistence",
                    "automatic recovery from corrupt state",
                    "ASR and translation artifact recovery",
                    "fidelity audit schema normalisation",
                    "stale empty-state overwrite protection",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
