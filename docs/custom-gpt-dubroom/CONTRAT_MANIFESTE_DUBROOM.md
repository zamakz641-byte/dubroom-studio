# Contrat du manifeste de traduction DubRoom

Ce document est un fichier de référence pour **DubRoom Script Director**.

## But

DubRoom Studio exporte la transcription d’un projet sous la forme d’un manifeste JSON. Le GPT remplit les traductions, puis DubRoom réimporte le fichier et associe chaque texte cible au segment d’origine.

## Structure minimale

```json
{
  "schema_version": 2,
  "kind": "dubroom_translation_manifest",
  "project_id": "identifiant-du-projet",
  "project_name": "Nom du projet",
  "source_language": "en",
  "target_language": "fr",
  "revision": 2,
  "created_at": "2026-07-29T00:00:00Z",
  "status": "ready_for_translation",
  "duration": 60.01,
  "transcript_fingerprint": "empreinte-a-conserver",
  "instructions": "Consignes fournies par DubRoom",
  "speaker_hints": {
    "SPEAKER_17": {"sex": "male", "sex_confidence": 0.72, "age_group": "unknown", "age_confidence": 0.0}
  },
  "segments": [
    {
      "id": "asr-001",
      "source_hash": "empreinte-du-segment",
      "temporary_cluster": "SPEAKER_17",
      "start": "00:00:01.000",
      "end": "00:00:06.120",
      "duration_seconds": 5.12,
      "recommended_words": {
        "minimum": 10,
        "ideal": 13,
        "maximum": 16
      },
      "context_id": "context-0001",
      "text": "The source sentence can continue in the next segment",
      "character_id": "",
      "character_name": "",
      "character_role": "",
      "character_confidence": null,
      "translation": ""
    }
  ]
}
```

## Champs immuables

Le GPT ne doit modifier aucun champ racine et ne doit jamais modifier :

- `segments[].id`
- `segments[].source_hash`
- `segments[].temporary_cluster`
- `segments[].start` et `segments[].end`
- `segments[].duration_seconds`
- `segments[].recommended_words`
- `segments[].context_id`
- `segments[].text`

Seuls `segments[].translation`, `character_id`, `character_name`, `character_role` et
`character_confidence` doivent être remplis.

## Frontières de segments

Les frontières viennent de l’alignement audio et ne correspondent pas toujours à la ponctuation. Par exemple :

```text
asr-001: The door
asr-002: had barely opened before someone started scolding him.
```

Ces deux fragments forment une seule phrase. Le GPT doit reconstruire le sens global,
puis écrire deux fragments cibles naturels. Chaque information reste dans l’ID source
qui la porte. Le GPT ne doit ni traduire les fragments sans contexte, ni déplacer une
proposition vers un autre ID.

## Locuteurs

`temporary_cluster` vient de Sherpa et reste un indice technique immuable. Ce n’est pas
l’identité finale : un même personnage peut avoir plusieurs clusters lorsqu’il crie,
chuchote ou change d’émotion. Le GPT résout les personnages grâce à l’histoire complète,
aux noms, aux réponses entre personnages et à la continuité des scènes. Les indices
`sex` et `age_group` sont secondaires et prudents ; aucun âge numérique précis ne doit
être inventé. Plusieurs segments et clusters peuvent partager le même `character_id`.

## Durée

`duration_seconds` représente la place disponible dans la vidéo pour la voix générée. La traduction doit être assez dense pour éviter un long silence, mais rester prononçable naturellement sans accélération artificielle.

La qualité narrative reste prioritaire sur un comptage mécanique. Le comptage de mots est un estimateur initial, pas une raison de remplir le texte avec des mots inutiles.

## Import dans DubRoom

DubRoom reconnaît notamment le champ `translation`. Il vérifie la révision et l’empreinte de transcription afin d’éviter d’appliquer un ancien script au mauvais montage. Le fichier rendu doit donc provenir du manifeste exact fourni dans la conversation.
