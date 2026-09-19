from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

from fastapi import BackgroundTasks, HTTPException


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api.app import local_voice_service
from services.api.app import main as api


def main() -> None:
    assertions: list[str] = []
    with tempfile.TemporaryDirectory(prefix="dubroom-project-modes-") as folder:
        root = Path(folder)
        with mock.patch.object(api, "PROJECTS_ROOT", root / "projects"):
            single = api.create_project(
                api.ProjectCreateRequest(
                    name="Single voice test",
                    dubbing_mode="single",
                    content_type="manga_recap",
                )
            )
            assert single.dubbing_mode == "single"
            try:
                api.create_project_job(
                    single.id,
                    api.JobCreateRequest(type="diarization"),
                    BackgroundTasks(),
                )
                raise AssertionError("Single-voice project accepted diarization")
            except HTTPException as exc:
                assert exc.status_code == 409
            assertions.append("Single-voice projects skip speaker detection")

        voice_root = root / "voice-profiles"
        with (
            mock.patch.object(local_voice_service, "ROOT", voice_root),
            mock.patch.object(local_voice_service, "INDEX_PATH", voice_root / "profiles.json"),
        ):
            profile = local_voice_service.create_profile(
                {
                    "name": "Aiko",
                    "language": "fr",
                    "voice_type": "cloned",
                    "default_engine": "tts-omnivoice-hq",
                    "gender": "female",
                    "age_group": "young_adult",
                    "primary_role": "female_lead",
                    "roles": ["female_lead"],
                    "usage_scope": "both",
                }
            )
            assert profile["gender"] == "female"
            assert profile["language"] == "fr"
            assert profile["primary_role"] == "female_lead"
            assert profile["usage_scope"] == "both"
            assert profile["multi_speaker_compatible"] is True
            assertions.append("Clone/design/recording profiles share precise casting metadata")

    print(f"Project mode and voice metadata tests passed: {len(assertions)} assertions")
    for assertion in assertions:
        print(f"- {assertion}")


if __name__ == "__main__":
    main()
