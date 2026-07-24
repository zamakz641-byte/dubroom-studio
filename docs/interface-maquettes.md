# Maquettes interface - Anime/Manga/Manhua Dubbing Studio

Date de creation: 2026-05-16

## Decision de demarrage

On commence par les maquettes de l'interface avant de creer toute la structure technique.

Raison:

- L'application est d'abord un outil de studio: timeline, video, speakers, texte, voix, export.
- La structure du projet doit suivre les vrais ecrans et workflows, pas l'inverse.
- Les composants UI vont determiner les modules frontend: player, timeline, inspector, segment editor,
  speaker manager, project dashboard.
- Le pipeline IA sera plus facile a brancher si l'interface montre deja clairement chaque etape.

Ordre retenu:

1. Maquettes UX et ecrans principaux.
2. Design system visuel.
3. Structure du projet Electron/React/Python.
4. Implementation du shell desktop.
5. Pipeline media minimal.
6. Integration IA progressive.

## Style produit cible

L'interface doit ressembler a un vrai studio de doublage local:

- sombre, precise, lisible;
- pas une landing page marketing;
- pas un simple formulaire IA;
- beaucoup d'informations mais bien rangees;
- timeline centrale comme dans un outil de montage;
- feedback temps reel sur les jobs IA;
- correction manuelle rapide partout.

Mots cles visuels:

- studio desktop;
- timeline audio/video;
- controle professionnel;
- manga/anime sans tomber dans une interface jouet;
- accent couleur pour speakers/personnages;
- panneaux denses mais respirants.

## Ecrans a maquettiser

### 1. Dashboard projets

But:

- voir les projets recents;
- creer/importer un nouveau projet;
- ouvrir les exports precedents;
- voir les modeles installes et l'etat de la machine.

Elements:

- barre laterale gauche: Projects, Voices, Models, Settings.
- liste/cartes compactes de projets.
- bouton principal: Import Video.
- indicateurs: GPU, storage, model cache.

### 2. Import video

But:

- importer une video;
- choisir langue source et langue cible;
- choisir mode rapide/qualite;
- creer le dossier projet.

Elements:

- zone drag and drop.
- metadata preview: duree, resolution, fps, audio channels.
- options: target language, subtitles, keep original music, detect speakers.
- bouton: Start Analysis.

### 3. Studio principal

But:

- espace central de travail apres analyse.

Layout cible:

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ Top bar: project name | Analyze | Generate Voices | Preview | Export       │
├───────────────┬───────────────────────────────────────────────┬─────────────┤
│ Left panel    │ Video preview                                  │ Inspector   │
│ scenes        │ Transcript overlay optional                    │ segment     │
│ speakers      ├───────────────────────────────────────────────┤ voice       │
│ voices        │ Timeline: waveform + colored speaker segments  │ emotion     │
│ jobs          │                                               │ timing      │
└───────────────┴───────────────────────────────────────────────┴─────────────┘
```

Elements:

- lecteur video.
- timeline waveform.
- segments colores par speaker.
- curseur de lecture.
- panneau speakers/personnages.
- inspecteur du segment selectionne.
- statut IA/job progress.

### 4. Editeur transcription/traduction

But:

- corriger le texte source;
- corriger la traduction;
- adapter le texte a la duree du segment.

Elements:

- tableau segments.
- colonnes: timecode, speaker, source text, translated text, adapted text, duration fit.
- score visuel: ok, too long, too short.
- actions: regenerate translation, shorten, expand, lock segment.

### 5. Speakers/personnages

But:

- transformer `SPEAKER_00` en personnage reel.
- assigner une voix par personnage.

Elements:

- liste speakers avec couleurs.
- extraits audio reference.
- rename speaker.
- merge/split speaker.
- assign voice profile.
- save as recurring character.

### 6. Voice lab

But:

- creer/gerer les voix.
- tester le TTS par personnage.

Elements:

- voice profiles.
- reference audio.
- moteur TTS choisi.
- emotion test: neutral, angry, shout, sad, whisper.
- phrase de test.
- bouton generate preview.

### 7. Export

But:

- produire la video finale.

Elements:

- options: MP4, audio only, subtitles.
- bitrate/resolution.
- loudness normalization.
- include original music.
- export queue.
- final preview.

## Etats importants a prevoir dans les maquettes

- Projet vide.
- Analyse en cours.
- Analyse terminee avec segments.
- Segment selectionne.
- Segment avec traduction trop longue.
- Speaker inconnu.
- TTS en generation.
- Erreur modele/manque de VRAM.
- Export termine.

## Premier concept visuel a creer

Priorite: maquette du `Studio principal`, parce que c'est l'ecran qui determine toute l'application.

Le concept doit montrer:

- top bar avec actions principales;
- panneau gauche avec speakers/scenes/jobs;
- preview video au centre;
- timeline audio/video en bas;
- panneau droit inspecteur;
- segments colores par personnage;
- texte source/traduit visible dans l'inspecteur;
- controls de voix/emotion/sync.

## Journal maquettes

### 2026-05-16

- Creation du fichier `docs/interface-maquettes.md`.
- Decision: commencer par les maquettes avant la structure technique.
- Definition des ecrans principaux et du premier ecran prioritaire: Studio principal.
- Validation utilisateur de la premiere direction visuelle.
- Sauvegarde de la maquette acceptee: `docs/assets/studio-main-mockup-v1.png`.
- Debut de l'implementation du shell desktop base sur cette maquette.
- Transformation de la maquette codee en shell interactif: selection segment/speaker, edition texte,
  emotions, sliders, lock et progression de generation.
- Ajout d'un panneau metadata dans la preview video pour afficher les infos reelles apres import:
  fichier, duree, resolution, FPS et audio.
- Le bouton Analyze declenche maintenant la preparation audio: extraction WAV, creation de projet et
  remplacement de la waveform mockee par une waveform reelle.
- La preview centrale affiche maintenant la vraie video importee via un lecteur `<video>`; la scene
  illustree reste seulement l'etat vide avant import.
- Passe de nettoyage UI apres retour utilisateur:
  - suppression du menu Electron par defaut;
  - video separee des cartes d'information;
  - metadata et sous-titre deplaces dans une colonne laterale dediee;
  - timeline et panneaux resserres pour reduire l'impression de melange.
- Separation des workflows en vues principales:
  - Studio: preview video, timeline et inspecteur segment;
  - Transcript: table dediee source/traduction/adaptation;
  - Speakers: gestion personnages et profils voix;
  - Export: reglages de sortie et readiness checks.
- Correction de navigation:
  - vues principales: Dashboard, Projects, Studio, Settings;
  - Studio devient la vue principale de travail;
  - Timeline, Transcript, Speakers et Export deviennent des sous-vues Studio.
- La topbar globale est reduite a une barre projet/statut compacte; les actions lourdes passent dans
  un rail de commandes contextuel du Studio.
- Refonte professionnelle:
  - onboarding premier lancement;
  - shell Desktop plus calme inspire Fluent/WinUI;
  - themes persistants;
  - Dashboard/Projects/Studio/Settings comme vues principales;
  - composants UI source-style shadcn et tokens Tailwind;
  - reduction des accents agressifs et separation plus nette des zones de travail.

### 2026-05-17

- Maquette implementee en vraie interface React/Tailwind:
  - onboarding en plein ecran au premier lancement;
  - navigation principale compacte inspiree WinUI NavigationView;
  - Studio comme espace de travail principal;
  - Timeline, Transcript, Speakers et Export separes pour eviter le melange des panneaux;
  - Dashboard et Projects avec etats vides, projets recents et reprise du projet actif;
  - Settings avec selection de theme, profil machine et options de preview.
- Direction visuelle ajustee:
  - moins de cyan et moins de contraste agressif;
  - surfaces neutres, espacements plus reguliers, typographie plus dense;
  - pas d'overlay video permanent sauf le sous-titre optionnel controle par reglage;
  - cartes reservees aux panneaux utiles ou aux elements repetes.
