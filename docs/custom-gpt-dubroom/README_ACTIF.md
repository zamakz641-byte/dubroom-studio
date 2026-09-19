# Fichiers GPT actifs dans DubRoom

## Narrateur unique - histoire complète

- GPT séparé : `DubRoom Narrator Story V1`
- Instructions : `INSTRUCTIONS_CHINESE_NARRATOR_STORY_V1_8000.txt`
- Connaissances : `KNOWLEDGE_NARRATOR_STORY_JSON_V1.txt` et `CODEX-NARRATOR-STORY-EVIDENCE-CONTRACT-V1.txt`
- Révision attendue : `narrator-story-scene-lock-20260811-v1`
- Langue : anglais uniquement
- Format : `dubroom_narrator_story_manifest`, schema 1, `dubbing_mode: narrator_story`
- Synchronisation : chaque phrase doit finir avant la limite dure de sa scène
- Sources : ASR chinois + sous-titres chinois + sous-titres anglais avec provenance
- Audio : silences et SFX protégés conservés; ducking appliqué plus tard au mixage

Ce mode raconte toute l'histoire avec une seule voix. Il ne remplace pas le GPT
Multi-Speaker et n'utilise pas son JSON V3.

## Chinois Multi-Speaker

- Instructions à coller : `INSTRUCTIONS_CHINESE_MULTISPEAKER_V5_ENGLISH_TIMING_8000.txt`
- Connaissance à importer : `KNOWLEDGE_MULTISPEAKER_JSON_R5_ENGLISH_TIMING.txt`
- Révision attendue : `english-timing-strict-20260811-r5`
- Langue cible obligatoire : `en` (anglais uniquement)
- Timing : total des mots de chaque segment entre `minimum` et `maximum`, au plus près de `ideal`
- Format : JSON V3, `dubbing_mode: multi`
- Preuve facultative : `segments[].subtitle_evidence`

Ces deux fichiers sont copiés automatiquement dans le dossier créé par le bouton
**Kit GPT** de DubRoom. Les manifestes V3 sans `subtitle_evidence` restent compatibles.

## Voix unique

- Instructions : `INSTRUCTIONS_A_COLLER.md`
- Connaissance : `CONTRAT_MANIFESTE_DUBROOM.md`
- Format : JSON V2, `dubbing_mode: single`

Les anciennes variantes V2/V3 sont conservées uniquement comme historique.
Elles ne doivent plus être utilisées pour un nouveau projet Multi-Speaker.
