# DubRoom Studio — feuille de route produit et technique

Dernière mise à jour : 24 juillet 2026

## 1. Vision

DubRoom Studio est un studio desktop multilingue de doublage vidéo assisté par IA.
L’application doit permettre de partir d’une vidéo source et d’obtenir une version
doublée dans une ou plusieurs langues, avec contrôle éditorial complet :

- transcription et diarisation ;
- traduction tenant compte du contexte global, des personnages et du glossaire ;
- adaptation à la durée, au mouvement des lèvres et à l’intention ;
- casting et génération de voix haute qualité ;
- synchronisation précise par segment ;
- mixage, contrôle qualité et export ;
- restauration et upscaling d’images ou de vidéos.

Le produit s’inspire des bons principes des studios de doublage existants, dont
OmniVoice Studio, mais reste une implémentation propre. Aucun code, nom de marque,
asset ou modèle propriétaire ne doit être copié sans licence compatible.

## 2. Principes non négociables

1. **Timeline au centre** : l’IA prépare et suggère ; l’utilisateur garde la main.
2. **Sections nettes** : chaque outil possède sa zone, sans accumulation de cartes
   imbriquées ni fenêtre modale pour les tâches ordinaires.
3. **Multilingue dès le premier lancement** : interface, RTL, formats locaux,
   langues source/cible et glossaires.
4. **Local-first** : projets, médias, caches et environnements résident sur le
   disque du projet. Les services cloud sont optionnels et explicitement activés.
5. **Qualité mesurable** : aucun résultat n’est seulement marqué « terminé » ;
   chaque segment reçoit des scores et des alertes contrôlables.
6. **Reproductibilité** : versions de modèles, prompts, réglages et décisions de
   montage sont enregistrés dans le projet.
7. **Tests à chaque incrément** : compilation, persistance, pipeline et interface.
8. **Usage responsable des voix** : consentement, provenance et restrictions de
   licence enregistrés dans chaque profil vocal.

## 3. Expérience cible

### 3.1 Onboarding

Huit étapes séparées :

1. langue de l’interface ;
2. bienvenue et confidentialité ;
3. apparence, densité et réduction des animations ;
4. emplacements des projets, modèles, caches et exports ;
5. détection CPU, RAM, GPU et accélération ;
6. langue source, langues cibles et type de contenu ;
7. installation des moteurs nécessaires ;
8. résumé et ouverture du premier projet.

### 3.2 Shell principal

- rail global : Accueil, Projets, Studio, Bibliothèque, Outils, Moteurs, Réglages ;
- barre de titre desktop compacte ;
- activité des traitements en arrière-plan ;
- état local des moteurs et de la machine ;
- recherche et palette de commandes ;
- restauration exacte de la dernière session.

### 3.3 Studio

```text
┌ Scènes / médias ┬──────── Moniteur programme ────────┬ Inspecteur ┐
│ plans           │ vidéo, sous-titres, safe zones     │ segment    │
│ personnages     │ comparaison source / sortie        │ voix       │
│ fichiers        │ contrôles de lecture               │ sync       │
├─────────────────┴────────────────────────────────────┴────────────┤
│ Timeline multipiste : vidéo, source, dialogue, voix, RVC, musique │
└───────────────────────────────────────────────────────────────────┘
```

Les panneaux sont redimensionnables, repliables et mémorisés. Les modes Média,
Script, Casting, Voix, Mixage et Livraison changent le contenu de chaque section,
pas la structure générale.

## 4. Design system « Nocturne »

Palette canonique :

| Rôle | Couleur |
|---|---|
| Canvas | `#090B10` |
| Surface | `#10141C` |
| Raised | `#171D28` |
| Overlay | `#202838` |
| Ligne | `#293246` |
| Texte | `#F4F6FA` |
| Texte secondaire | `#C0C7D2` |
| Muet | `#8F9BAD` |
| Accent violet | `#8B7CFF` |
| Accent chaud | `#FFB86B` |
| Synchronisation | `#45D6E8` |
| Succès | `#47D18C` |
| Danger | `#FF6B7A` |

Règles :

- profondeur par contraste et lignes, pas par multiplication d’ombres ;
- arrondis modérés ;
- animations brèves et fonctionnelles ;
- 3D réservée au Voice Core et aux vues où elle transmet un état ;
- aucune décoration pseudo-futuriste sans fonction ;
- minimum 10 px pour les libellés secondaires, 11–13 px pour les contrôles ;
- navigation complète au clavier et focus visible.

## 5. Architecture

### 5.1 Desktop

- Electron ;
- React + TypeScript + Vite ;
- Tailwind et composants source contrôlés ;
- Motion pour les transitions ;
- Three.js chargé à la demande pour les rares vues 3D ;
- panneaux redimensionnables accessibles ;
- pages lourdes chargées à la demande.

Tauri n’est pas retenu pour le premier cycle : le dépôt dispose déjà d’un runtime
Electron fonctionnel et le changement imposerait Rust, WebView2 et une nouvelle
chaîne de packaging sans bénéfice produit immédiat.

### 5.2 Service local

- FastAPI comme API de contrôle ;
- processus de traitement isolés par moteur ;
- FFmpeg/FFprobe pour les médias ;
- files de jobs persistantes ;
- WebSocket ou événements serveur pour les progrès détaillés ;
- annulation, reprise et journal par étape.

### 5.3 Stockage

```text
data/
  environments/   environnements Python gérés
  cache/          Hugging Face, Torch et téléchargements temporaires
models/           manifestes et poids installés
projects/
  <project-id>/
    project.json
    media/
    analysis/
    translations/
    voices/
    timeline/
    renders/
    exports/
```

Les chemins sont configurables mais doivent, par défaut, rester sur le disque du
projet. Aucune dépendance lourde ne doit être déposée silencieusement sur C:.

### 5.4 Modèle de projet

Objets principaux :

- `Project` : médias, langues, profil qualité, versions des moteurs ;
- `Scene` : plan, contexte, personnages présents, résumé ;
- `Speaker` : identité, rôle, langue, profil vocal et consentement ;
- `Segment` : timecodes source, locuteur, texte, traduction et prises ;
- `Take` : audio généré, moteur, seed, style, durée et scores ;
- `Track` / `Clip` : montage non destructif ;
- `GlossaryEntry` : terme, traduction, prononciation et portée ;
- `QualityFinding` : sévérité, métrique, preuve et résolution ;
- `Job` : étape, dépendances, progression, logs et possibilité de reprise.

Les fichiers JSON restent lisibles et versionnés par schéma. Une base SQLite peut
servir d’index, sans devenir l’unique source des données créatives.

## 6. Pipeline de doublage

### Étape A — Ingestion

- import local ou source distante autorisée ;
- copie ou lien contrôlé vers le média ;
- probe, proxy de lecture, extraction audio et miniatures ;
- détection des coupures de plans ;
- séparation optionnelle voix / musique / effets.

### Étape B — Transcription et alignement

- VAD ;
- ASR multilingue ;
- alignement au mot ou au phonème ;
- diarisation ;
- fusion guidée par la continuité des personnages ;
- éditeur de transcript avec historique.

Sortie minimale : texte, mots horodatés, confiance, langue et locuteur par segment.

### Étape C — Contexte et traduction

Le traducteur reçoit :

- résumé du projet et de la scène ;
- segments voisins ;
- fiche des personnages ;
- registre, tutoiement/vouvoiement et contraintes culturelles ;
- glossaire verrouillé ;
- durée cible et densité syllabique.

Le résultat conserve trois couches :

1. traduction fidèle ;
2. adaptation naturelle ;
3. ligne de doublage contrainte par le temps et les lèvres.

Chaque modification manuelle nourrit une mémoire de traduction locale au projet.

### Étape D — Casting et voix

- profils preset, clonés ou conçus ;
- pré-écoute A/B ;
- voix différente par langue si nécessaire ;
- contrôle du style, de l’émotion et de la prononciation ;
- génération de plusieurs prises ;
- remplacement d’un seul mot ou intervalle sans régénérer toute la scène ;
- traitement haute qualité : débruitage, de-essing, EQ, normalisation et loudness.

### Étape E — Synchronisation

La synchronisation « chirurgicale » combine :

- correspondance de durée ;
- pauses et respirations ;
- alignement mots/visèmes ;
- time-stretch limité et sans changement de hauteur ;
- reformulation automatique si la compression nécessaire dépasse le seuil ;
- poignées manuelles sur la timeline ;
- score par segment : durée, début, fin, lèvres et intelligibilité.

Le lipsync vidéo génératif reste une option séparée, calculée uniquement après
validation de l’audio.

### Étape F — Mixage

- volume et automation par piste ;
- ducking de la musique ;
- conservation des ambiances ;
- spatialisation et canaux ;
- loudness par cible de diffusion ;
- comparaison instantanée source / doublage.

### Étape G — Contrôle qualité et export

- segments manquants ou en chevauchement ;
- traduction non validée ;
- clipping, silence, souffle et saturation ;
- dérive de synchronisation ;
- cohérence des noms et prononciations ;
- rapport de licence des modèles et voix ;
- export vidéo, audio séparé, stems, sous-titres et rapport QC.

## 7. Upscaling image et vidéo

L’outil est une chaîne indépendante :

1. détection du type de contenu : anime, dessin, photo ou vidéo réelle ;
2. débruitage et restauration ;
3. désentrelacement si nécessaire ;
4. interpolation optionnelle ;
5. upscaling par tuiles avec marge ;
6. réduction du scintillement temporel ;
7. reconstruction audio éventuelle ;
8. comparaison avant/après et export.

Les réglages doivent afficher VRAM estimée, temps estimé, taille finale et risque
d’artefacts. Aucun filtre ne remplace silencieusement l’original.

## 8. Stratégie multilingue

Interface initiale : français, anglais, espagnol, portugais, allemand, japonais,
coréen, chinois simplifié et arabe.

Exigences :

- aucune chaîne brute dans les composants métier ;
- vérification automatique des clés ;
- RTL réel pour l’arabe ;
- formats locaux pour dates, nombres et durées ;
- fallback explicite ;
- pseudo-localisation pour tester l’expansion ;
- test des écrans à 1120×700 et 1366×715 au minimum ;
- langue du projet indépendante de la langue de l’interface.

## 9. Phases et critères de sortie

### P0 — Runtime stable — terminé

- fenêtre ouverte sans attendre les moteurs ;
- environnement Python minimal sur le disque du projet ;
- caches IA redirigés ;
- baseline Git ;
- split, EDL et mute testés.

### P1 — Nocturne et onboarding — terminé

- palette et composants ;
- huit étapes multilingues ;
- Voice Core 3D adaptatif ;
- réduction des animations ;
- pages chargées à la demande ;
- audit sans texte coupé ni clé affichée.

### P2 — Architecture du Studio — en cours

- dock vertical accessible et persistant ;
- panneaux gauche/droit redimensionnables ;
- extraction du moniteur, du storyboard, de l’inspecteur et de la timeline ;
- état de disposition sauvegardé par projet ou profil ;
- raccourcis pour afficher/masquer chaque zone.

Critère de sortie : aucun composant de page métier supérieur à environ 500 lignes
sans justification, redimensionnement clavier/souris testé, vues minimum et laptop
sans débordement.

### P3 — Timeline professionnelle

- modèle de temps unique et précision image ;
- pistes et clips non destructifs ;
- waveform réelle ;
- zoom, scroll, snapping et sélection multiple ;
- trim, split, ripple delete, glisser-déposer et undo/redo ;
- marqueurs, régions In/Out et raccourcis ;
- tests de persistance et d’export EDL.

### P4 — Pipeline IA minimal utilisable

- ingestion ;
- ASR + alignement ;
- diarisation ;
- traduction contextuelle ;
- génération d’une voix ;
- montage automatique des prises ;
- export d’un court projet de référence.

### P5 — Qualité haut de gamme

- casting multi-voix ;
- dictionnaire de prononciation ;
- prises A/B ;
- synchronisation avancée ;
- mixage et QC ;
- jeux d’évaluation reproductibles.

### P6 — Upscaling

- photo ;
- anime/image ;
- vidéo par tuiles ;
- estimation VRAM ;
- reprise après interruption ;
- comparaison et rapport.

### P7 — Packaging Windows

- installation et désinstallation propres ;
- choix du disque pour les données lourdes ;
- signature ;
- mise à jour ;
- diagnostic exportable ;
- test sur machine propre sans outils développeur.

### P8 — Bêta

- projets réels courts puis longs ;
- tests de panne et reprise ;
- test de migration des projets ;
- accessibilité ;
- licences et consentements ;
- documentation utilisateur ;
- mesure du temps de traitement et de la qualité.

## 10. Matrice de tests

À chaque changement :

- vérification TypeScript ;
- build Vite ;
- validation des traductions et de l’encodage ;
- test ciblé de la fonction modifiée.

À chaque jalon :

- API et schémas ;
- persistance après redémarrage ;
- workflow Electron réel ;
- audit visuel aux deux tailles minimales ;
- raccourcis clavier ;
- mode animation réduite ;
- erreur moteur, disque plein, job annulé et reprise ;
- export et lecture du fichier produit.

Avant bêta :

- corpus de référence multilingue ;
- métriques WER/alignement/durée/loudness ;
- revue humaine de naturel, fidélité et jeu ;
- performance CPU, GPU 6 Go, GPU 8–12 Go ;
- projet de 5 minutes, 30 minutes et long format.

## 11. Sécurité, confidentialité et licences

- serveur local lié à `127.0.0.1` ;
- validation stricte des chemins ;
- aucune clé dans les logs ou fichiers de projet ;
- secrets dans le stockage sécurisé du système ;
- confirmation avant envoi cloud ;
- manifeste de provenance pour chaque modèle ;
- consentement obligatoire pour les voix clonées ;
- suppression et export des données utilisateur ;
- audit des dépendances avant chaque version ;
- pas de correction automatique forcée des dépendances avec rupture majeure.

## 12. Définition de « terminé »

Une fonctionnalité est terminée quand :

1. son état vide, normal, occupé et en erreur existe ;
2. elle est utilisable au clavier ;
3. son texte est traduit ;
4. elle persiste quand cela est attendu ;
5. elle possède au moins un test pertinent ;
6. elle passe le build et l’audit visuel ;
7. elle ne télécharge rien hors du disque choisi sans accord ;
8. son effet est documenté dans l’historique du projet.
