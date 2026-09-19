# DubRoom Multi-Speaker V3 — plan de production

## Règle narrative canonique

- `NARRATOR` est toujours une voix extérieure, à la troisième personne.
- Le protagoniste utilise la voix permanente `mc` uniquement lorsqu’il parle réellement ou lorsqu’une pensée intérieure explicite est présente.
- La voix `female_lead` reste attachée au rôle principal féminin.
- La voix `antagonist` reste attachée à l’antagoniste principal.
- Chaque personnage secondaire récurrent reçoit un `CHAR_###` stable.
- Un changement de timbre, un cri, un chuchotement ou des effets sonores ne créent pas automatiquement un nouveau personnage.

## Responsabilités

1. Paraformer-zh transcrit rapidement le chinois avec CUDA.
2. La diarisation acoustique fournit seulement des indices de changement de voix, de sexe vocal et d’âge approximatif.
3. Le GPT lit toute l’histoire, traduit, résout les identités, sépare les voix présentes dans un même bloc et choisit la direction émotionnelle.
4. DubRoom valide le JSON, attribue les voix permanentes, génère le TTS, synchronise, mixe et exporte.

## Format JSON V3

Chaque segment source reste immuable, mais contient une ou plusieurs `voice_units` ordonnées. Une unité indique le type de parole, le personnage, la clé vocale, la traduction, l’émotion, l’intensité et les événements OmniVoice.

Les types admis sont `narration`, `dialogue`, `inner_monologue`, `system` et `reaction`.

Les silences précédant certains segments exposent un `bridge_slot`. Le GPT peut y placer un court pont narratif seulement s’il est fondé sur le contexte voisin et respecte la durée et le nombre de mots autorisés. Les silences utiles aux réactions, à l’action, à la musique ou aux SFX restent vides.

## Voix permanentes

- Narrateur : voix signature externe.
- MC : voix signature temporaire, remplacée par le clone fourni par l’utilisateur.
- Rôle féminin principal : voix signature marquante.
- Antagoniste : voix signature sombre et distincte.
- Secondaires : classement par rôle, sexe vocal, groupe d’âge et langue, puis attribution cohérente.

## Qualité et sécurité

- Le JSON importé doit conserver les IDs, hashes, timecodes, textes chinois et l’empreinte du projet.
- Une narration en voix MC est refusée.
- Un événement OmniVoice invalide le cache audio afin que la phrase soit réellement régénérée.
- Les tags de réaction ne sont ajoutés que lorsqu’ils sont audibles et justifiés par le contexte.
- Les faits ne peuvent être ni inventés, ni déplacés vers un autre segment.

## Export vidéo

- `balanced` : H.264 haute qualité pour contrôle ou master léger.
- `compact` : H.265, qualité 25, audio AAC 192 kb/s.
- `ultra_compact` : H.265, qualité 28, audio AAC 160 kb/s.
- `master` : conservation maximale pour archivage.

Le profil `compact` est le choix normal. `ultra_compact` sert lorsque la taille est prioritaire.

## Test de validation 15 minutes

1. Préparer les 15 premières minutes et transcrire en chinois sur GPU.
2. Exporter le manifeste V3 avec les indices acoustiques et les créneaux narratifs.
3. Faire traiter le manifeste complet par le GPT configuré avec les instructions et la base de connaissances V3.
4. Importer le JSON brut renvoyé et corriger toute erreur bloquante signalée par DubRoom.
5. Vérifier visuellement les identités et écouter les événements émotionnels.
6. Générer toutes les voix, synchroniser et conserver les SFX.
7. Exporter en H.265 `compact`, puis contrôler le début, le milieu, la fin et les transitions narrateur/personnages.
