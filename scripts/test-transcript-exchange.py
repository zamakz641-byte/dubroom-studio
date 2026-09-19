from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app import main as api_main  # noqa: E402


SOURCE_PROJECT = next(
    path
    for path in (
        ROOT / "projects" / "dubroom-open-source-36min-validation-20260728",
        ROOT / "projects" / "sss-20260808-183800",
    )
    if (path / "analysis" / "state.json").is_file()
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = ROOT / "data" / "test-runs" / f"transcript-exchange-{stamp}"
    projects_root = run_root / "projects"
    project_id = "roundtrip-36min"
    project_dir = projects_root / project_id
    analysis_dir = project_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    source_state_path = SOURCE_PROJECT / "analysis" / "state.json"
    check(source_state_path.is_file(), "The 36-minute validation project is missing")
    original_state = json.loads(source_state_path.read_text(encoding="utf-8"))
    check(len(original_state["segments"]) >= 700, "Expected the full transcript")
    (analysis_dir / "state.json").write_text(
        json.dumps(original_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    project_record = {
        "id": project_id,
        "name": "DubRoom transcript exchange validation",
        "status": "prepared",
        "project_dir": str(project_dir),
        "source_path": None,
        "original_source_path": None,
        "derived_sources": [],
        "media_manifest_path": None,
        "source_language": original_state.get("source_language"),
        "target_language": original_state.get("target_language"),
        "dubbing_mode": "multi",
        "output_aspect": "16:9",
        "performance_profile": "gpu_quality",
        "created_at": datetime.now().astimezone().isoformat(),
        "updated_at": datetime.now().astimezone().isoformat(),
    }
    (project_dir / "project.json").write_text(
        json.dumps(project_record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    api_main.PROJECTS_ROOT = projects_root
    api_main.TRASH_ROOT = run_root / "trash"
    manifest_export = api_main.export_project_transcript(
        project_id,
        api_main.TranscriptExportRequest(format="manifest", chunk_size=60),
    )
    manifest_file = next(
        Path(item["path"])
        for item in manifest_export["files"]
        if item["name"].endswith("-translation-manifest.json")
    )
    compact_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    check(
        compact_manifest.get("kind") == "dubroom_translation_manifest",
        "Compact translation manifest has the wrong kind",
    )
    check(
        compact_manifest.get("schema_version") == 3,
        "Multispeaker manifest did not upgrade to V3 voice units",
    )
    check(
        len(compact_manifest["segments"]) == len(original_state["segments"]),
        "Compact translation manifest lost segments",
    )
    check(
        set(compact_manifest["segments"][0]) == {
            "id",
            "source_hash",
            "start",
            "end",
            "duration_seconds",
            "recommended_words",
            "preceding_gap_seconds",
            "bridge_slot",
            "context_id",
            "section_id",
            "temporary_cluster",
            "text",
            "character_id",
            "character_name",
            "character_role",
            "character_confidence",
            "emotion",
            "emotion_intensity",
            "omnivoice_tag",
            "translation",
            "voice_units",
            "narrator_bridge",
        },
        "Compact translation rows do not expose the resolver contract",
    )
    check(
        compact_manifest["narrative_profile"] == "natural_recap",
        "The selected narrative profile was not exported",
    )
    check(
        compact_manifest["narrative_contract"]["point_of_view"]
        == "external_third_person",
        "Natural recap is not explicitly an external narrator",
    )
    guide_file = next(
        Path(item["path"])
        for item in manifest_export["files"]
        if item["name"] == "DUBROOM-GPT-INSTRUCTIONS.md"
    )
    guide_content = guide_file.read_text(encoding="utf-8")
    check(
        "NARRATIVE MODEL: NARRATOR FIRST" in guide_content
        or "troisième personne" in guide_content,
        "The GPT guide does not enforce the selected translation contract",
    )
    check(
        "is not proof that the protagonist speaks" in guide_content
        and "When uncertain between NARRATOR and MC, choose NARRATOR" in guide_content,
        "The GPT guide can still turn recap narration into false MC monologues",
    )
    check(
        compact_manifest.get("prompt_revision")
        == "narrator-speaker-sfx-safe-20260809-r3",
        "The narrator-first prompt revision is missing from the manifest",
    )
    instructions_txt = next(
        Path(item["path"])
        for item in manifest_export["files"]
        if item["name"] == "DUBROOM-GPT-INSTRUCTIONS-V3.txt"
    )
    knowledge_txt = next(
        Path(item["path"])
        for item in manifest_export["files"]
        if item["name"] == "DUBROOM-MULTISPEAKER-V3-KNOWLEDGE.txt"
    )
    check(
        len(instructions_txt.read_text(encoding="utf-8")) <= 8000,
        "GPT V3 instructions exceed 8000 characters",
    )
    check(
        "voice_units" in knowledge_txt.read_text(encoding="utf-8"),
        "V3 knowledge file is incomplete",
    )

    v3_manifest = json.loads(json.dumps(compact_manifest))
    v3_row = v3_manifest["segments"][0]
    v3_row["voice_units"] = [
        {
            "unit_id": f'{v3_row["id"]}-u01',
            "order": 1,
            "speech_type": "narration",
            "character_id": "NARRATOR",
            "character_name": "Narrator",
            "character_role": "external_narrator",
            "voice_key": "narrator",
            "source_excerpt": v3_row["text"],
            "translation": "The narrator establishes the scene.",
            "emotion": "neutral",
            "emotion_intensity": 30,
            "vocal_events": [],
            "confidence": 0.99,
        },
        {
            "unit_id": f'{v3_row["id"]}-u02',
            "order": 2,
            "speech_type": "dialogue",
            "character_id": "CHAR_001",
            "character_name": "Hero",
            "character_role": "protagonist",
            "voice_key": "mc",
            "source_excerpt": v3_row["text"],
            "translation": "I will handle this myself.",
            "emotion": "determined",
            "emotion_intensity": 75,
            "vocal_events": [{"event": "[confirmation-en]", "position": "before"}],
            "confidence": 0.95,
        },
    ]
    for row in v3_manifest["segments"][1:]:
        row["voice_units"] = [
            {
                "unit_id": f'{row["id"]}-u01',
                "order": 1,
                "speech_type": "narration",
                "character_id": "NARRATOR",
                "character_name": "Narrator",
                "character_role": "external_narrator",
                "voice_key": "narrator",
                "source_excerpt": row["text"],
                "translation": "The narrator continues the complete story.",
                "emotion": "neutral",
                "emotion_intensity": 30,
                "vocal_events": [],
                "confidence": 0.95,
            }
        ]
    v3_manifest["character_registry"] = [
        {
            "character_id": "CHAR_001",
            "character_name": "Hero",
            "character_role": "protagonist",
            "voice_key": "mc",
            "sex": "male",
            "age_group": "young_adult",
            "confidence": 0.95,
        }
    ]
    v3_manifest["status"] = "translated"
    v3_file = run_root / "returned-v3-units.json"
    v3_file.write_text(
        json.dumps(v3_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    v3_preview = api_main.preview_project_transcript_import(
        project_id,
        api_main.TranscriptImportRequest(path=str(v3_file)),
    )
    check(
        v3_preview["can_apply"]
        and v3_preview["matched_count"] == len(original_state["segments"]),
        "Valid V3 voice units were rejected",
    )
    expanded_v3, expanded_entries = api_main._expand_v3_voice_units(
        [api_main.SegmentRecord.model_validate(original_state["segments"][0])],
        {v3_row["id"]: v3_preview["entries"][0]},
    )
    check(len(expanded_v3) == 2, "A mixed narrator/dialogue segment was not split")
    check(
        {segment.speechType for segment in expanded_v3} == {"narration", "dialogue"}
        and set(expanded_entries) == {f'{v3_row["id"]}-u01', f'{v3_row["id"]}-u02'},
        "Expanded V3 lines lost their voice type or identity",
    )
    v3_project_id = "roundtrip-v3-units"
    v3_project_dir = projects_root / v3_project_id
    (v3_project_dir / "analysis").mkdir(parents=True, exist_ok=True)
    (v3_project_dir / "analysis" / "state.json").write_text(
        json.dumps(original_state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (v3_project_dir / "project.json").write_text(
        json.dumps(
            {
                **project_record,
                "id": v3_project_id,
                "name": "DubRoom V3 voice unit validation",
                "project_dir": str(v3_project_dir),
                "dubbing_mode": "multi",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    v3_imported = api_main.import_project_transcript(
        v3_project_id,
        api_main.TranscriptImportRequest(
            path=str(v3_file),
            revision=original_state["revision"],
        ),
    )
    v3_imported_state = v3_imported["state"]
    check(
        len(v3_imported_state["segments"]) == len(original_state["segments"]) + 1,
        "V3 import did not persist both voices from one mixed source segment",
    )
    check(
        v3_imported_state["segments"][1]["omnivoiceEvents"]
        and v3_imported_state["segments"][1]["voiceKey"] == "mc",
        "V3 import lost the MC voice key or OmniVoice event",
    )
    expressive_segment = api_main.SegmentRecord.model_validate(
        v3_imported_state["segments"][1]
    )
    check(
        api_main._omnivoice_segment_text(expressive_segment).startswith(
            "[confirmation-en]"
        ),
        "Validated OmniVoice events were not inserted into synthesis text",
    )
    # The normal workflow remains a simple V2 manifest. V3 is reserved for
    # projects that explicitly selected Multi-Speaker at creation time.
    project_record["dubbing_mode"] = "single"
    (project_dir / "project.json").write_text(
        json.dumps(project_record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    compact_manifest["segments"][0]["translation"] = (
        "Première traduction française importée depuis le manifeste."
    )
    compact_manifest["segments"][0]["character_id"] = "CHAR_001"
    compact_manifest["segments"][0]["character_name"] = "Héros"
    compact_manifest["segments"][0]["character_role"] = "main"
    compact_manifest["segments"][0]["character_confidence"] = 0.91
    manifest_file.write_text(
        json.dumps(compact_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest_preview = api_main.preview_project_transcript_import(
        project_id,
        api_main.TranscriptImportRequest(path=str(manifest_file)),
    )
    check(manifest_preview["parsed_count"] == 1, "Manifest translation was not parsed")
    check(manifest_preview["matched_count"] == 1, "Manifest ID was not matched")
    check(manifest_preview["can_apply"], "Valid compact manifest was blocked")

    raw_text_file = run_root / "chatgpt-raw-result.txt"
    raw_text_file.write_text(
        "```json\n" + manifest_file.read_text(encoding="utf-8") + "\n```",
        encoding="utf-8",
    )
    raw_text_preview = api_main.preview_project_transcript_import(
        project_id,
        api_main.TranscriptImportRequest(path=str(raw_text_file)),
    )
    check(
        raw_text_preview["matched_count"] == 1 and raw_text_preview["can_apply"],
        "Raw or fenced ChatGPT JSON saved as TXT was not recognized",
    )

    chat_export = api_main.export_project_transcript(
        project_id,
        api_main.TranscriptExportRequest(format="chat", chunk_size=60),
    )
    check(
        chat_export["segment_count"] == len(original_state["segments"]),
        "Chat export lost transcript segments",
    )
    single_manifest_export = api_main.export_project_transcript(
        project_id,
        api_main.TranscriptExportRequest(format="manifest", chunk_size=60),
    )
    single_manifest_path = next(
        Path(item["path"])
        for item in single_manifest_export["files"]
        if item["name"].endswith("-translation-manifest.json")
    )
    single_manifest = json.loads(single_manifest_path.read_text(encoding="utf-8"))
    check(
        single_manifest["schema_version"] == 2
        and single_manifest["dubbing_mode"] == "single"
        and "voice_units" not in single_manifest["segments"][0],
        "Single-speaker projects incorrectly received the Multi-Speaker V3 contract",
    )
    chat_files = [
        Path(item["path"])
        for item in chat_export["files"]
        if "-chat-" in item["name"] and item["name"].endswith(".md")
    ]
    check(len(chat_files) >= 10, "The long transcript was not split into chat parts")

    returned_chat = run_root / "returned-chat-part.md"
    chat_content = chat_files[0].read_text(encoding="utf-8")
    check(
        "Narrative profile: natural_recap" in chat_content
        and "third person" in chat_content,
        "Chat Pack lost the selected narrative contract",
    )
    chat_content = re.sub(
        r"CHARACTER_ID:\s*\nCHARACTER_NAME:\s*\nCHARACTER_ROLE:\s*\nCHARACTER_CONFIDENCE:\s*\nEMOTION:\s*neutral\s*\nEMOTION_INTENSITY:\s*0\s*\nOMNIVOICE_TAG:\s*\nTARGET:\s*\n\[\[/DUBROOM_SEGMENT\]\]",
        "CHARACTER_ID: CHAR_001\nCHARACTER_NAME: Héros\n"
        "CHARACTER_ROLE: main\nCHARACTER_CONFIDENCE: 0.90\n"
        "EMOTION: surprised\nEMOTION_INTENSITY: 70\n"
        "OMNIVOICE_TAG: [surprise-ah]\n"
        "TARGET: Traduction française de test, naturelle et complète.\n"
        "[[/DUBROOM_SEGMENT]]",
        chat_content,
    )
    returned_chat.write_text(chat_content, encoding="utf-8")
    chat_preview = api_main.preview_project_transcript_import(
        project_id,
        api_main.TranscriptImportRequest(path=str(returned_chat)),
    )
    check(chat_preview["matched_count"] == 60, "Chat part IDs were not preserved")
    check(chat_preview["can_apply"], "Valid returned Chat Pack was blocked")

    manifest_path = next(
        Path(item["path"])
        for item in chat_export["files"]
        if item["name"].endswith("-exchange.json")
    )
    exchange = json.loads(manifest_path.read_text(encoding="utf-8"))
    exchange["speaker_sections"] = [
        {
            "section_id": "section-001",
            "detected_speakers": [
                {
                    "character_id": "CHAR_001",
                    "sex": "male",
                    "age_group": "young_adult",
                    "confidence": 0.92,
                },
                {
                    "character_id": "CHAR_002",
                    "sex": "female",
                    "age_group": "adult",
                    "confidence": 0.89,
                },
            ],
        }
    ]
    for index, row in enumerate(exchange["segments"], start=1):
        row["target_text"] = (
            f"Traduction française externe du segment {index}, "
            "conservant le sens et les informations."
        )
        row["character_id"] = "CHAR_001" if index % 2 else "CHAR_002"
        row["character_name"] = "Héros" if index % 2 else "Rivale"
        row["character_role"] = "main" if index % 2 else "supporting"
        row["character_confidence"] = 0.9
    returned_json = run_root / "returned-full-script.json"
    returned_json.write_text(
        json.dumps(exchange, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    preview = api_main.preview_project_transcript_import(
        project_id,
        api_main.TranscriptImportRequest(path=str(returned_json)),
    )
    segment_count = len(original_state["segments"])
    check(preview["matched_count"] == segment_count, "Full JSON import lost IDs")
    check(preview["changed_count"] == segment_count, "Changed rows were miscounted")
    check(preview["can_apply"], "Valid full JSON import was blocked")
    check(not preview["duplicate_ids"], "Unexpected duplicate IDs")
    check(not preview["source_mismatch_ids"], "Unexpected source hash mismatch")

    imported = api_main.import_project_transcript(
        project_id,
        api_main.TranscriptImportRequest(
            path=str(returned_json),
            revision=preview["revision"],
        ),
    )
    check(imported["next_stage"] == "voice_generation", "Wrong next pipeline stage")
    check(
        len(imported["changed_ids"]) == segment_count,
        "Not every changed line was imported",
    )
    imported_state = imported["state"]
    check(
        imported_state["last_operation"] == "external_translation_and_speaker_resolution",
        "Import operation was not recorded",
    )
    check(
        imported_state["revision"] == original_state["revision"] + 1,
        "Revision did not advance atomically",
    )
    imported_speakers = {
        speaker["character_id"]: speaker for speaker in imported_state["speakers"]
    }
    check(
        imported_speakers["CHAR_001"]["detected_sex"] == "male"
        and imported_speakers["CHAR_001"]["detected_age_group"] == "young_adult",
        "GPT speaker traits were not copied to the voice casting record",
    )
    check(
        imported_speakers["CHAR_002"]["detected_sex"] == "female"
        and imported_speakers["CHAR_002"]["detected_age_group"] == "adult",
        "Second GPT speaker traits were not copied to the voice casting record",
    )
    imported_state_model = api_main.ProjectAnalysisState.model_validate(imported_state)
    check(
        api_main._multispeaker_resolution_ready(project_dir, imported_state_model),
        "GPT-resolved multi-speaker projects still require acoustic diarization",
    )
    merged_take_index = api_main._voice_takes_by_member_id(
        [
            {
                "segment_id": "seg-001",
                "member_ids": ["seg-001", "seg-002", "seg-003"],
            }
        ]
    )
    check(
        set(merged_take_index) == {"seg-001", "seg-002", "seg-003"},
        "Merged voice takes do not mark every member segment as ready",
    )

    immutable_fields = ("id", "start", "end", "sourceText")
    for before, after in zip(
        original_state["segments"],
        imported_state["segments"],
        strict=True,
    ):
        for field in immutable_fields:
            check(
                before[field] == after[field],
                f"Import changed immutable field {field} for {before['id']}",
            )
        check(
            after["acousticSpeaker"] == before["speaker"],
            f"Acoustic evidence was not preserved for {before['id']}",
        )
        check(after["translatedText"], f"Missing imported text for {after['id']}")
        check(
            after["translatedText"] == after["adaptedText"],
            f"Voice script was not reset to imported text for {after['id']}",
        )
        check(
            not after["voiceAudioReady"],
            f"Stale generated voice was kept for {after['id']}",
        )

    try:
        api_main.import_project_transcript(
            project_id,
            api_main.TranscriptImportRequest(
                path=str(returned_json),
                revision=preview["revision"],
            ),
        )
        raise AssertionError("Stale preview was not rejected")
    except HTTPException as exc:
        check(exc.status_code == 409, "Stale preview returned the wrong error")

    for subtitle_format in ("srt", "vtt"):
        response = api_main.export_project_transcript(
            project_id,
            api_main.TranscriptExportRequest(
                format=subtitle_format,
                chunk_size=60,
            ),
        )
        subtitle_path = next(
            Path(item["path"])
            for item in response["files"]
            if item["name"].endswith(f".{subtitle_format}")
        )
        subtitle_preview = api_main.preview_project_transcript_import(
            project_id,
            api_main.TranscriptImportRequest(path=str(subtitle_path)),
        )
        check(
            subtitle_preview["matched_count"] == segment_count,
            f"{subtitle_format.upper()} round-trip lost segment IDs",
        )

    report = {
        "status": "passed",
        "project": project_id,
        "segment_count": segment_count,
        "context_count": chat_export["context_count"],
        "manifest_roundtrip": True,
        "single_speaker_v2": True,
        "raw_json_txt_import": True,
        "chat_file_count": len(chat_files),
        "chat_part_matched": chat_preview["matched_count"],
        "json_matched": preview["matched_count"],
        "changed": len(imported["changed_ids"]),
        "next_stage": imported["next_stage"],
        "immutable_fields_verified": list(immutable_fields),
        "stale_revision_rejected": True,
        "srt_roundtrip": True,
        "vtt_roundtrip": True,
        "run_root": str(run_root),
    }
    report_path = run_root / "report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
