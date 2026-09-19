# DubRoom Multispeaker JSON V2 — Knowledge Base

This format is only for projects whose `dubbing_mode` is `multi`.

## Root structure

```json
{
  "schema_version": 2,
  "kind": "dubroom_translation_manifest",
  "project_id": "project-id",
  "source_language": "zh",
  "target_language": "en",
  "transcript_fingerprint": "immutable",
  "speaker_hints": {
    "SPEAKER_00": {
      "sex": "female",
      "sex_confidence": 0.72,
      "age_group": "unknown",
      "age_confidence": 0.0
    }
  },
  "speaker_sections": [
    {
      "section_id": "section-001",
      "start": "00:00:01.800",
      "end": "00:04:32.100",
      "first_segment_id": "asr-001",
      "last_segment_id": "asr-060",
      "detected_speakers": []
    }
  ],
  "segments": []
}
```

All existing root fields are immutable. `speaker_hints` are measurements, not identities.

## Section detection output

For every `speaker_sections[]`, fill `detected_speakers`:

```json
{
  "character_id": "CHAR_003",
  "character_name": "Lin Feng",
  "character_role": "main",
  "sex": "male",
  "age_group": "young_adult",
  "confidence": 0.91,
  "temporary_clusters": ["SPEAKER_02", "SPEAKER_17"],
  "evidence_segment_ids": ["asr-014", "asr-022"]
}
```

The same character can use several temporary clusters. A cluster can also be unreliable because of overlap or SFX. Narrative evidence takes priority. Reuse character IDs across sections.

Allowed IDs: `CHAR_001` to `CHAR_9999`, `NARRATOR`, `SYSTEM`, `UNKNOWN`.

Allowed sex: `male`, `female`, `uncertain`.

Allowed age groups: `child`, `teen`, `young_adult`, `adult`, `elderly`, `unknown`. Never provide a numeric age.

## Segment structure

```json
{
  "id": "asr-014",
  "source_hash": "immutable",
  "section_id": "section-001",
  "temporary_cluster": "SPEAKER_17",
  "start": "00:00:42.200",
  "end": "00:00:46.800",
  "duration_seconds": 4.6,
  "recommended_words": {"minimum": 9, "ideal": 12, "maximum": 14},
  "context_id": "context-0010",
  "text": "你怎么会在这里",
  "character_id": "CHAR_003",
  "character_name": "Lin Feng",
  "character_role": "main",
  "character_confidence": 0.91,
  "emotion": "surprised",
  "emotion_intensity": 72,
  "omnivoice_tag": "[surprise-ah]",
  "translation": "What are you doing here?"
}
```

Only the final character, emotion, OmniVoice and translation fields are editable. Never change or relocate the source text, timestamps, IDs, hashes, contexts or acoustic cluster.

## Emotion and OmniVoice

Every segment receives one emotion and an intensity from 0 to 100. Emotion describes acting direction. `omnivoice_tag` is a separate optional audible event.

Supported tags: empty, `[laughter]`, `[sigh]`, `[confirmation-en]`, `[question-en]`, `[question-ah]`, `[question-oh]`, `[question-ei]`, `[question-yi]`, `[surprise-ah]`, `[surprise-oh]`, `[surprise-wa]`, `[surprise-yo]`, `[dissatisfaction-hnn]`.

Never place these tags inside `translation`. Never add a reaction not supported by the source or scene. An empty tag is the correct default.

## Import behavior

DubRoom validates hashes and the transcript fingerprint, imports translations, preserves `temporary_cluster` as acoustic evidence, replaces visible speaker labels with stable characters, rebuilds the multispeaker cast and writes `analysis/speaker-resolution.json`.

Two sections that refer to the same person must use the same `character_id`. Two different IDs must not silently share the same identity. Use `UNKNOWN` when context is insufficient.
